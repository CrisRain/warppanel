# controller-app/app/warp_controller.py
"""
WarpController - Factory for WARP backend controllers
Automatically selects between usque and official backends based on environment
"""
import os
import logging
from typing import Union
from .usque_controller import UsqueController
from .official_controller import OfficialController

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WarpController:
    """Factory class for WARP backend controllers"""
    
    _instance: Union[UsqueController, OfficialController, None] = None
    _current_backend: str = None
    
    @classmethod
    def get_instance(cls) -> Union[UsqueController, OfficialController]:
        """
        Get the current WARP controller instance.
        Creates new instance if backend changed or doesn't exist.
        """
        backend = os.getenv("WARP_BACKEND", "usque").lower()
        
        # Create new instance if needed
        if cls._instance is None or cls._current_backend != backend:
            logger.info(f"Initializing WARP controller with backend: {backend}")
            cls._current_backend = backend
            
            if backend == "usque":
                cls._instance = UsqueController()
            elif backend == "official":
                cls._instance = OfficialController()
            else:
                raise ValueError(f"Unknown WARP_BACKEND: {backend}. Use 'usque' or 'official'")
        
        return cls._instance
    
    @classmethod
    def switch_backend(cls, new_backend: str) -> Union[UsqueController, OfficialController]:
        """
        Switch to a different backend.
        Note: This changes the environment variable but doesn't restart the container.
        For full switching, the container needs to be restarted with the new backend.
        """
        if new_backend not in ["usque", "official"]:
            raise ValueError(f"Invalid backend: {new_backend}. Use 'usque' or 'official'")
        
        logger.info(f"Switching backend from {cls._current_backend} to {new_backend}")
        
        # Disconnect current backend
        if cls._instance:
            try:
                cls._instance.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting current backend: {e}")
        
        # Ensure port 1080 is released before switching
        import socket
        import time
        logger.info("Waiting for port 1080 to be released...")
        for _ in range(10): # Wait up to 5 seconds
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', 1080)) != 0:
                    # Port is free
                    break
            time.sleep(0.5)
        
        # Force kill if still occupied (last resort)
        try:
            import psutil
            for conn in psutil.net_connections():
                if conn.laddr.port == 1080 and conn.status == 'LISTEN':
                    logger.warning(f"Port 1080 still in use by PID {conn.pid}, killing...")
                    try:
                        psutil.Process(conn.pid).kill()
                    except:
                        pass
        except ImportError:
            pass
        except Exception:
            pass
        
        # Update environment and reset instance
        os.environ["WARP_BACKEND"] = new_backend
        cls._instance = None
        cls._current_backend = None
        
        # Return new instance
        return cls.get_instance()
    
    @classmethod
    def get_current_backend(cls) -> str:
        """Get the name of the current backend"""
        return cls._current_backend or os.getenv("WARP_BACKEND", "usque")
    
    @classmethod
    def reset(cls):
        """Reset the controller instance"""
        if cls._instance:
            try:
                cls._instance.disconnect()
            except:
                pass
        cls._instance = None
        cls._current_backend = None
