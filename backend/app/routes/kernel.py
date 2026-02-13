from fastapi import APIRouter, Depends, HTTPException
from ..controllers.auth_controller import AuthHandler
from ..controllers.kernel_controller import KernelVersionManager
from ..controllers.warp_controller import WarpController
import logging
import asyncio

router = APIRouter()
logger = logging.getLogger(__name__)
auth_handler = AuthHandler.get_instance()
kernel_mgr = KernelVersionManager.get_instance()

# Helper for running blocking functions
async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)

@router.get("/versions")
async def get_kernel_versions(backend: str = None, user: str = Depends(auth_handler.get_current_user)):
    """List available versions for the specified backend (or current backend)"""
    if not backend:
        backend = WarpController.get_current_backend()
        
    versions = await run_blocking(kernel_mgr.list_versions, backend)
    # Get current active version (configured)
    current_active = await run_blocking(kernel_mgr.get_active_version, backend)
    
    # Get detailed info (installed version, latest version)
    info = await run_blocking(kernel_mgr.get_installed_version_info, backend)
    
    return {
        "backend": backend,
        "versions": versions,
        "current": current_active,
        "installed_version": info.get("version"),
        "latest_version": info.get("latest_version"),
        "update_available": info.get("update_available")
    }

@router.get("/all-versions")
async def get_all_kernel_versions(user: str = Depends(auth_handler.get_current_user)):
    """Get version info for all backends"""
    backends = ["usque", "official"]
    results = {}
    
    for backend in backends:
        try:
            versions = await run_blocking(kernel_mgr.list_versions, backend)
            current_active = await run_blocking(kernel_mgr.get_active_version, backend)
            info = await run_blocking(kernel_mgr.get_installed_version_info, backend)
            
            results[backend] = {
                "versions": versions,
                "current": current_active,
                "installed_version": info.get("version"),
                "latest_version": info.get("latest_version"),
                "update_available": info.get("update_available")
            }
        except Exception as e:
            logger.error(f"Error getting info for {backend}: {e}")
            results[backend] = {"error": str(e)}
            
    return results

@router.post("/check-update")
async def check_update(request: dict, user: str = Depends(auth_handler.get_current_user)):
    """Manually check for updates"""
    backend = request.get("backend", "usque")
    logger.info(f"Checking for updates for {backend}...")
    
    latest = await run_blocking(kernel_mgr.check_for_updates, backend)
    
    if latest:
        return {"success": True, "latest_version": latest}
    return {"success": False, "message": "No update found or check failed"}

@router.post("/update")
async def perform_update(request: dict, user: str = Depends(auth_handler.get_current_user)):
    """Perform update to latest version"""
    backend = request.get("backend", "usque")
    
    logger.info(f"Triggering manual update for {backend}...")
    updated = await run_blocking(kernel_mgr.auto_update, backend)
    
    if updated:
         # Restart if successful
         controller = WarpController.get_instance()
         await controller.disconnect()
         await asyncio.sleep(1)
         await controller.connect()
         return {"success": True, "message": "Updated and restarted"}
    else:
         return {"success": False, "message": "Update failed or already up to date"}

@router.post("/version")
async def set_kernel_version(request: dict, user: str = Depends(auth_handler.get_current_user)):
    """Set the active version for a backend"""
    backend = request.get("backend")
    version = request.get("version")
    
    if not backend or not version:
        raise HTTPException(status_code=400, detail="Missing backend or version")
    
    success = await run_blocking(kernel_mgr.set_active_version, backend, version)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to set version (invalid version or backend)")
        
    # If we updated the currently running backend, we should restart it
    current_backend = WarpController.get_current_backend()
    if backend == current_backend:
        logger.info(f"Version changed for active backend {backend}, restarting...")
        controller = WarpController.get_instance()
        await controller.disconnect()
        await asyncio.sleep(1)
        await controller.connect()
        
    return {
        "success": True,
        "backend": backend,
        "version": version
    }
