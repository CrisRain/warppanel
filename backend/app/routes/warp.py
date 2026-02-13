from fastapi import APIRouter, Depends, HTTPException
from ..controllers.auth_controller import AuthHandler
from ..controllers.warp_controller import WarpController
import logging
import asyncio

router = APIRouter()
logger = logging.getLogger(__name__)
auth_handler = AuthHandler.get_instance()

@router.get("/backend/current")
async def get_current_backend(user: str = Depends(auth_handler.get_current_user)):
    """Get current backend type"""
    controller = WarpController.get_instance()
    backend = WarpController.get_current_backend()
    
    is_connected = False
    if hasattr(controller, 'is_connected'):
        is_connected = await controller.is_connected()
        
    return {
        "backend": backend,
        "connected": is_connected
    }

@router.post("/backend/switch")
async def switch_backend(request: dict, user: str = Depends(auth_handler.get_current_user)):
    """Switch WARP backend"""
    new_backend = request.get("backend")
    
    if new_backend not in ["usque", "official"]:
        raise HTTPException(status_code=400, detail="Invalid backend. Use 'usque' or 'official'")
    
    previous_backend = WarpController.get_current_backend()
    # previous_mode = WarpController.get_current_mode()
    
    logger.info(f"API: Switching backend from {previous_backend} to {new_backend}")
    
    try:
        # Switch backend using factory
        controller = await WarpController.switch_backend(new_backend)
        
        # Try to connect with new backend
        logger.info(f"API: Connecting with new backend {new_backend}...")
        connect_success = await controller.connect()
        status = await controller.get_status()
        
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

@router.post("/connect")
async def connect(user: str = Depends(auth_handler.get_current_user)):
    controller = WarpController.get_instance()
    success = await controller.connect()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to connect WARP")
    return await controller.get_status()

@router.post("/disconnect")
async def disconnect(user: str = Depends(auth_handler.get_current_user)):
    controller = WarpController.get_instance()
    success = await controller.disconnect()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to disconnect WARP")
    return await controller.get_status()

@router.post("/rotate")
async def rotate_ip(user: str = Depends(auth_handler.get_current_user)):
    """
    轮换 IP 地址（简单模式：断开重连）
    """
    controller = WarpController.get_instance()
    
    # Use built-in rotate if available
    if hasattr(controller, 'rotate_ip_simple'):
        success = await controller.rotate_ip_simple()
    else:
        # Fallback manual rotation
        await controller.disconnect()
        await asyncio.sleep(1)
        success = await controller.connect()
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to rotate (reconnect failed)")
    
    return await controller.get_status()
