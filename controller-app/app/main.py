import asyncio
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .warp_controller import WarpController

# Configuration
SOCKS5_PORT = 1080

# Limit thread pool to avoid unbounded thread creation
_thread_pool = ThreadPoolExecutor(max_workers=4)

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
        self._pending_logs: deque = deque(maxlen=maxlen)
        self.formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        self._loop = None
        self._flush_scheduled = False
    
    def set_loop(self, loop):
        """设置事件循环引用"""
        self._loop = loop
    
    def emit(self, record):
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
            'level': record.levelname,
            'logger': record.name,
            'message': self.format(record)
        }
        self.logs.append(log_entry)
        self._pending_logs.append(log_entry)
        
        # Schedule a single flush instead of one task per log line
        if not self._flush_scheduled:
            self._flush_scheduled = True
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(self._schedule_flush)
            except Exception:
                self._flush_scheduled = False
    
    def _schedule_flush(self):
        asyncio.create_task(self._flush_pending_logs())
    
    async def _flush_pending_logs(self):
        """Batch-broadcast pending logs to reduce task creation overhead"""
        await asyncio.sleep(0.1)  # 100ms debounce
        self._flush_scheduled = False
        if 'manager' not in globals():
            return
        mgr = globals()['manager']
        while self._pending_logs:
            entry = self._pending_logs.popleft()
            await mgr.broadcast({'type': 'log', 'data': entry})

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
    # Start shared status broadcaster
    asyncio.create_task(status_broadcast_loop())

async def connect_in_background(controller):
    logger.info("Starting WARP backend (background)...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, controller.connect)

async def status_broadcast_loop(interval: float = 10.0):
    """Periodically broadcast status to all connected clients.
    Uses a single polling loop to avoid per-connection polling overhead.
    Interval increased to 10s to reduce subprocess spawning.
    """
    while True:
        try:
            if manager.active_connections:
                status = await run_blocking(WarpController.get_instance().get_status)
                await manager.broadcast({"type": "status", "data": status})
                await asyncio.sleep(interval)
            else:
                # No clients connected, no need to poll frequently
                await asyncio.sleep(5.0)
        except Exception:
            await asyncio.sleep(interval)

# Serve Frontend
# We assume the frontend build is copied to /app/static in the Docker image
if os.path.exists("/app/static"):
    app.mount("/assets", StaticFiles(directory="/app/static/assets"), name="assets")

    @app.get("/")
    async def read_index():
        return FileResponse('/app/static/index.html')

else:
    logger.warning("Static files directory /app/static not found. Frontend will not be served.")

# Helper for running blocking functions (uses bounded thread pool)
async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_thread_pool, func, *args)

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
    
    previous_backend = WarpController.get_current_backend()
    previous_mode = WarpController.get_current_mode()
    
    logger.info(f"API: Switching backend from {previous_backend} to {new_backend}")
    
    try:
        # Switch backend using factory
        controller = await run_blocking(WarpController.switch_backend, new_backend)
        
        # Try to connect with new backend
        logger.info(f"API: Connecting with new backend {new_backend}...")
        connect_success = await run_blocking(controller.connect)
        status = await run_blocking(controller.get_status)
        
        return {
            "success": True, 
            "previous_backend": previous_backend,
            "backend": new_backend, 
            "connected": connect_success,
            "mode": getattr(controller, 'mode', 'proxy'),
            "status": status,
        }
            
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

@app.post("/api/config/endpoint")
async def set_endpoint(request: dict):
    """Set custom endpoint address (IP:PORT)"""
    endpoint = request.get("endpoint", "").strip()
    controller = WarpController.get_instance()
    
    if hasattr(controller, 'set_custom_endpoint'):
        success = await run_blocking(controller.set_custom_endpoint, endpoint)
        if success:
             return {"success": True, "endpoint": endpoint}
        else:
             raise HTTPException(status_code=500, detail="Failed to set endpoint")
    else:
        raise HTTPException(status_code=501, detail="Backend does not support custom endpoints")


@app.post("/api/config/mode")
async def set_mode(request: dict):
    """Switch between proxy and TUN mode"""
    mode = request.get("mode", "").strip().lower()

    if mode not in ("proxy", "tun"):
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'proxy' or 'tun'")

    controller = WarpController.get_instance()
    previous_mode = getattr(controller, 'mode', 'proxy')

    if not hasattr(controller, 'set_mode'):
        raise HTTPException(status_code=501, detail="Backend does not support mode switching")

    logger.info(f"API: Switching mode from {previous_mode} to {mode}")
    
    success = await run_blocking(controller.set_mode, mode)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to switch mode")

    # Reconnect in new mode
    logger.info(f"API: Connecting in {mode} mode...")
    connect_success = await run_blocking(controller.connect)
    status = await run_blocking(controller.get_status)

    return {
        "success": True,
        "previous_mode": previous_mode,
        "mode": mode,
        "connected": connect_success,
        "status": status,
    }


@app.get("/api/config/mode")
async def get_mode():
    """Get current operating mode and configuration"""
    controller = WarpController.get_instance()
    return {
        "mode": WarpController.get_current_mode(),
        "backend": WarpController.get_current_backend(),
        "protocol": getattr(controller, 'preferred_protocol', 'masque'),
        "connected": await run_blocking(controller.is_connected) if hasattr(controller, 'is_connected') else False,
    }


@app.get("/api/config/protocol")
async def get_protocol():
    """Get current tunnel protocol"""
    controller = WarpController.get_instance()
    backend = WarpController.get_current_backend()
    mode = WarpController.get_current_mode()
    protocol = getattr(controller, 'preferred_protocol', 'masque')
    
    # WireGuard availability
    wireguard_available = backend == "official" and mode == "tun"
    
    return {
        "protocol": protocol,
        "backend": backend,
        "mode": mode,
        "wireguard_available": wireguard_available,
    }

@app.post("/api/config/protocol")
async def set_protocol(request: dict):
    """Set tunnel protocol. WireGuard only available for official backend in TUN mode."""
    protocol = request.get("protocol", "masque").strip().lower() or "masque"

    if protocol not in ("masque", "wireguard"):
        raise HTTPException(status_code=400, detail="Invalid protocol. Use 'masque' or 'wireguard'")

    controller = WarpController.get_instance()
    backend = WarpController.get_current_backend()
    current_mode = getattr(controller, 'mode', 'proxy')
    previous_protocol = getattr(controller, 'preferred_protocol', 'masque')

    # WireGuard validation
    if protocol == "wireguard":
        if backend != "official":
            raise HTTPException(status_code=400, detail="WireGuard is only available with the official backend")
        if current_mode != "tun":
            raise HTTPException(status_code=400, detail="WireGuard is only available in TUN mode. Please switch to TUN mode first.")

    logger.info(f"API: Switching protocol from {previous_protocol} to {protocol}")

    if hasattr(controller, 'set_protocol'):
        success = await run_blocking(controller.set_protocol, protocol)
        if success:
            status = await run_blocking(controller.get_status)
            return {
                "success": True, 
                "previous_protocol": previous_protocol,
                "protocol": protocol,
                "backend": backend,
                "mode": current_mode,
                "status": status,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to set protocol")
    else:
        if protocol == "wireguard":
            raise HTTPException(status_code=501, detail="This backend does not support WireGuard")
        return {"success": True, "protocol": "masque", "backend": backend}


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
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        # Clean up broken connections to prevent memory leak
        for conn in dead_connections:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

manager = ConnectionManager()

@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial status
        initial_status = await run_blocking(WarpController.get_instance().get_status)
        await websocket.send_json({"type": "status", "data": initial_status})
        
        # Keep connection alive without per-connection polling
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            
    except WebSocketDisconnect:
        pass
    finally:
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

