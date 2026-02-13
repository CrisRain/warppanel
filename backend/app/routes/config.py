from fastapi import APIRouter, Depends, HTTPException
from ..controllers.auth_controller import AuthHandler
from ..controllers.config_controller import ConfigManager
from ..controllers.warp_controller import WarpController
from ..utils.logger import log_collector
import logging
import asyncio

router = APIRouter()
logger = logging.getLogger(__name__)
auth_handler = AuthHandler.get_instance()
config_mgr = ConfigManager.get_instance()

@router.post("/password")
async def set_password(request: dict, user: str = Depends(auth_handler.get_current_user)):
    """Update panel password"""
    pwd = request.get("password")
    if pwd is None:
        raise HTTPException(status_code=400, detail="Password required")
    
    config_mgr.set("panel_password", pwd)
    return {"success": True}

@router.get("/ports")
async def get_ports(user: str = Depends(auth_handler.get_current_user)):
    """Get current port configuration"""
    return {
        "socks5_port": config_mgr.socks5_port,
        "panel_port": config_mgr.panel_port,
    }

@router.post("/ports")
async def set_ports(request: dict, user: str = Depends(auth_handler.get_current_user)):
    """
    Update port configuration.
    """
    new_socks5 = request.get("socks5_port")
    new_panel = request.get("panel_port")

    # Validate
    try:
        if new_socks5 is not None:
            new_socks5 = int(new_socks5)
            if not (1 <= new_socks5 <= 65535):
                raise ValueError
        if new_panel is not None:
            new_panel = int(new_panel)
            if not (1 <= new_panel <= 65535):
                raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid port number (must be 1-65535)")

    current_socks5 = config_mgr.socks5_port
    current_panel = config_mgr.panel_port

    socks5_changed = new_socks5 is not None and new_socks5 != current_socks5
    panel_changed = new_panel is not None and new_panel != current_panel

    final_socks5 = new_socks5 if new_socks5 is not None else current_socks5
    final_panel = new_panel if new_panel is not None else current_panel

    # Persist
    config_mgr.set("socks5_port", final_socks5)
    config_mgr.set("panel_port", final_panel)

    result = {
        "success": True,
        "socks5_port": final_socks5,
        "panel_port": final_panel,
        "socks5_changed": socks5_changed,
        "panel_changed": panel_changed,
        "restart_required": panel_changed,
    }

    # Apply SOCKS5 port change immediately (reconnect)
    if socks5_changed:
        logger.info(f"SOCKS5 port changed to {final_socks5}, reconnecting...")
        
        # Use simple disconnect/connect flow, backend picks up new port from WarpController factory or passed to it
        controller = WarpController.get_instance()
        await controller.disconnect()
        
        # Controller factory needs to be updated. 
        # Actually WarpController.update_socks5_port does the job of updating the static var
        WarpController.update_socks5_port(final_socks5)
        
        # When we call get_instance() again, it should use the updated port if creating new, 
        # or we might need to manually set it if reusing.
        # update_socks5_port already updates it on the instance if it exists.
        
        await asyncio.sleep(1)
        await controller.connect()

    if panel_changed:
        logger.info(f"Panel port changed to {final_panel} — will take effect after restart")

    return result


