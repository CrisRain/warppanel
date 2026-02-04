import asyncio
import logging
from collections import deque
from datetime import datetime
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .warp_controller import WarpController

# Configuration
SOCKS5_PORT = 1080

# Filter for noisy connection logs
class ConnectionFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return "connection open" not in msg and "connection closed" not in msg

# Custom handler
class LogCollector(logging.Handler):
    def __init__(self, maxlen=100):
        super().__init__()
        self.logs = deque(maxlen=maxlen)
        self.formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        self._loop = None
    
    def set_loop(self, loop):
        """设置事件循环引用"""
        self._loop = loop
    
    def emit(self, record):
        # Filter is applied at handler level, so we don't need to check here
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
            'level': record.levelname,
            'logger': record.name,
            'message': self.format(record)
        }
        self.logs.append(log_entry)
        
        # Broadcast to all websocket clients (线程安全)
        try:
            if self._loop and self._loop.is_running():
                # 从其他线程安全地调度到事件循环
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(broadcast_log(log_entry))
                )
        except Exception:
            pass  # 忽略广播失败

log_collector = LogCollector(maxlen=200)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add collector to root logger
root_logger = logging.getLogger()
root_logger.addHandler(log_collector)

# Apply filter to ALL handlers (console + collector)
conn_filter = ConnectionFilter()
for handler in root_logger.handlers:
    handler.addFilter(conn_filter)
    
# Also suppress uvicorn access logs if needed (optional, but "connection open" usually comes from uvicorn.error/asgi)
logging.getLogger("uvicorn.access").addFilter(conn_filter)
logging.getLogger("uvicorn.error").addFilter(conn_filter)

# Broadcast log helper - manager will be defined later
async def broadcast_log(log_entry):
    """Broadcast log entry to all connected websocket clients"""
    try:
        # manager is defined later, so we use globals() to access it
        if 'manager' in globals():
            await globals()['manager'].broadcast({'type': 'log', 'data': log_entry})
    except:
        pass

app = FastAPI(title="WARP Single Client")

# 启动事件：设置事件循环引用
@app.on_event("startup")
async def startup_event():
    """应用启动时设置事件循环"""
    loop = asyncio.get_running_loop()
    log_collector.set_loop(loop)
    logger.info("Event loop configured for log broadcasting")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Controller Instance removed, access via factory pattern

# Initialize controller on startup
@app.on_event("startup")
async def init_controller():
    logger.info("Initializing WARP controller...")
    controller = WarpController.get_instance()
    
    # Attempt to connect/start backend at startup
    logger.info("Starting WARP backend...")
    # Run in background task to avoid blocking startup
    asyncio.create_task(connect_in_background(controller))

async def connect_in_background(controller):
    logger.info("Starting WARP backend (background)...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, controller.connect)

# Serve Frontend
# We assume the frontend build is copied to /app/static in the Docker image
if os.path.exists("/app/static"):
    app.mount("/assets", StaticFiles(directory="/app/static/assets"), name="assets")

    @app.get("/")
    async def read_index():
        return FileResponse('/app/static/index.html')

else:
    logger.warning("Static files directory /app/static not found. Frontend will not be served.")

# Helper for running blocking functions
async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)

@app.get("/api/status")
async def get_status():
    return await run_blocking(WarpController.get_instance().get_status)

@app.get("/api/backend/current")
async def get_current_backend():
    """Get current backend type"""
    controller = WarpController.get_instance()
    backend = await run_blocking(WarpController.get_current_backend)
    
    is_connected = False
    if hasattr(controller, 'is_connected'):
        is_connected = await run_blocking(controller.is_connected)
        
    return {
        "backend": backend,
        "connected": is_connected
    }

@app.post("/api/backend/switch")
async def switch_backend(request: dict):
    """Switch WARP backend"""
    new_backend = request.get("backend")
    
    if new_backend not in ["usque", "official"]:
        raise HTTPException(status_code=400, detail="Invalid backend. Use 'usque' or 'official'")
    
    try:
        # Switch backend using factory
        controller = await run_blocking(WarpController.switch_backend, new_backend)
        
        # Try to connect with new backend (optional, but good UX)
        if await run_blocking(controller.connect):
            return {"success": True, "backend": new_backend, "status": "connected"}
        else:
            return {"success": True, "backend": new_backend, "status": "disconnected", "warning": "Backend switched but failed to connect immediately"}
            
    except Exception as e:
        logger.error(f"Switch backend failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/connect")
async def connect():
    controller = WarpController.get_instance()
    success = await run_blocking(controller.connect)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to connect WARP")
    return await run_blocking(controller.get_status)

@app.post("/api/disconnect")
async def disconnect():
    controller = WarpController.get_instance()
    success = await run_blocking(controller.disconnect)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to disconnect WARP")
    return await run_blocking(controller.get_status)

@app.post("/api/rotate")
async def rotate_ip():
    """
    轮换 IP 地址（简单模式：断开重连）
    """
    controller = WarpController.get_instance()
    
    # Use built-in rotate if available
    if hasattr(controller, 'rotate_ip_simple'):
        success = await run_blocking(controller.rotate_ip_simple)
    else:
        # Fallback manual rotation
        await run_blocking(controller.disconnect)
        await asyncio.sleep(1)
        success = await run_blocking(controller.connect)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to rotate (reconnect failed)")
    
    return await run_blocking(controller.get_status)


@app.get("/api/logs")
async def get_logs(limit: int = 100):
    """
    获取最近的日志记录
    
    Args:
        limit: 返回的日志数量限制（默认100）
    """
    logs = list(log_collector.logs)
    return {
        "total": len(logs),
        "logs": logs[-limit:]
    }


# WebSocket for real-time updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass # Handle broken pipes

manager = ConnectionManager()

@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial status
        initial_status = await run_blocking(WarpController.get_instance().get_status)
        await websocket.send_json({"type": "status", "data": initial_status})
        
        # Poll and push status updates every few seconds? 
        # Or just rely on client polling/actions?
        # Let's add a background poller for this socket session or global
        while True:
            # Wait for messages (keepalive) or just sleep and push
            # Simple keepalive:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            except asyncio.TimeoutError:
                # Timeout is fine, just push status
                pass
                
            status = await run_blocking(WarpController.get_instance().get_status)
            await websocket.send_json({"type": "status", "data": status})
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# Fallback for SPA (Catch-all)
# Must be defined last to avoid shadowing other routes
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # Don't catch API or WebSocket routes
    if full_path.startswith("api") or full_path.startswith("ws"):
         raise HTTPException(status_code=404)
    
    # Check if file exists in static/assets (handled by mount, but just in case)
    if os.path.exists(f"/app/static/{full_path}"):
        return FileResponse(f"/app/static/{full_path}")
        
    return FileResponse('/app/static/index.html')

