import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# New Imports
from .utils.logger import setup_logging, log_collector
from .utils.connection import manager
from .controllers.warp_controller import WarpController
from .controllers.config_controller import ConfigManager


# Correct imports based on file moves
from .controllers.kernel_controller import KernelVersionManager
from .controllers.auth_controller import AuthHandler

# Routes
from .routes import system, auth, config, warp, kernel

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize Config
config_mgr = ConfigManager.get_instance()
# AuthHandler initialized in routes but good to have if needed (e.g. middleware)
auth_handler = AuthHandler.get_instance()

SOCKS5_PORT = config_mgr.socks5_port
PANEL_PORT = config_mgr.panel_port

# Limit thread pool
_thread_pool = ThreadPoolExecutor(max_workers=4)

app = FastAPI(title="WARP Single Client")

# Inject manager into log_collector
log_collector.manager = manager

# Startup Events
@app.on_event("startup")
async def startup_event():
    """App startup configuration."""
    loop = asyncio.get_running_loop()
    log_collector.set_loop(loop)
    logger.info("Event loop configured for log broadcasting")

    logger.info(f"Initializing WARP controller (SOCKS5={SOCKS5_PORT}, Panel={PANEL_PORT})...")
    controller = WarpController.get_instance(socks5_port=SOCKS5_PORT)
    
    logger.info("Starting WARP backend...")
    asyncio.create_task(connect_in_background(controller))
    asyncio.create_task(status_broadcast_loop())
    asyncio.create_task(auto_update_task())

# Tasks (kept here or moved to utils/tasks.py - keeping here for simplicity as they tie everything together)
async def connect_in_background(controller):
    logger.info("Starting WARP backend (background)...")
    await controller.connect()

async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_thread_pool, func, *args)

async def auto_update_task():
    try:
        await run_blocking(KernelVersionManager.get_instance().adopt_system_installation, "usque")
    except Exception as e:
        logger.warning(f"Failed to adopt system installation: {e}")

    logger.info("Running kernel auto-update check...")
    try:
        await run_blocking(KernelVersionManager.get_instance().auto_update, "usque")
    except Exception as e:
        logger.error(f"Auto-update failed: {e}")

async def status_broadcast_loop(interval: float = 10.0):
    while True:
        try:
            if manager.active_connections:
                status = await WarpController.get_instance().get_status()
                await manager.broadcast({"type": "status", "data": status})
                await asyncio.sleep(interval)
            else:
                await asyncio.sleep(5.0)
        except Exception:
            await asyncio.sleep(interval)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
# /api/status, /api/version, /api/logs
app.include_router(system.router, prefix="/api", tags=["System"])

# /api/auth/login, /api/auth/check
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])

# /api/config/*
app.include_router(config.router, prefix="/api/config", tags=["Config"])

# /api/kernel/*
app.include_router(kernel.router, prefix="/api/kernel", tags=["Kernel"])

# Warp routes (mixed paths: /api/connect, /api/backend/..., /api/rotate)
app.include_router(warp.router, prefix="/api", tags=["Warp"])


# WebSocket
@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial status
        try:
            initial_status = await WarpController.get_instance().get_status()
            await websocket.send_json({"type": "status", "data": initial_status})
        except (RuntimeError, WebSocketDisconnect):
            # Connection might have closed immediately
            return

        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send a ping or keep-alive if needed, or just continue waiting
                continue
            except WebSocketDisconnect:
                break
            
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        # Handle "Cannot call 'send' once a close message has been sent."
        pass
    finally:
        manager.disconnect(websocket)


# Static Files & Catch-all
STATIC_DIR = os.getenv("STATIC_DIR", "/app/static")
if not os.path.exists(STATIC_DIR):
    # Try relative path for local development
    local_static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
    if os.path.exists(local_static):
        STATIC_DIR = local_static

if os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=f"{STATIC_DIR}/assets"), name="assets")

    @app.get("/")
    async def read_index():
        return FileResponse(f'{STATIC_DIR}/index.html')
else:
    logger.warning(f"Static files directory {STATIC_DIR} not found. Frontend will not be served.")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api") or full_path.startswith("ws"):
         raise HTTPException(status_code=404)
    
    if os.path.exists(f"{STATIC_DIR}/{full_path}"):
        return FileResponse(f"{STATIC_DIR}/{full_path}")
        
    return FileResponse(f'{STATIC_DIR}/index.html')
