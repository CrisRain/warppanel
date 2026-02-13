from fastapi import APIRouter, Depends
from ..controllers.auth_controller import AuthHandler
from ..controllers.warp_controller import WarpController
from ..utils.version import get_app_version
from ..utils.logger import log_collector
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
auth_handler = AuthHandler.get_instance()

@router.get("/status")
async def get_status(user: str = Depends(auth_handler.get_current_user)):
    return await WarpController.get_instance().get_status()

@router.get("/version")
async def get_version():
    """Get application version"""
    return {"version": get_app_version()}

@router.get("/logs")
async def get_logs(limit: int = 100, user: str = Depends(auth_handler.get_current_user)):
    """
    Get recent logs. 
    """
    logs = list(log_collector.logs)
            
    return {
        "total": len(logs),
        "logs": logs[-limit:]
    }
