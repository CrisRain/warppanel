# controller-app/app/usque_controller.py
"""
UsqueController - WARP backend implementation using usque
Supports both proxy mode (SOCKS5) and TUN mode
"""
import asyncio
import logging
import json
import os
from typing import Optional, Dict
from .kernel_controller import KernelVersionManager
from .base_controller import WarpBackendController

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UsqueController(WarpBackendController):

    def __init__(self, config_path=None, socks5_port=1080):
        super().__init__(socks5_port=socks5_port)
        self.config_path = config_path or os.getenv("USQUE_CONFIG_PATH", "/var/lib/warp/config.json")
        self.process = None

    @property
    def mode(self) -> str:
        return "proxy"

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Initialize usque backend (register if needed)"""
        try:
            config_dir = os.path.dirname(self.config_path)
            os.makedirs(config_dir, exist_ok=True)

            if not os.path.exists(self.config_path):
                logger.info("Config not found, registering new usque account...")
                
                binary_path = KernelVersionManager.get_instance().get_binary_path('usque')
                process = await asyncio.create_subprocess_exec(
                    binary_path, "register",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=config_dir,
                )
                stdout, stderr = await process.communicate(input=b"y\n")

                if process.returncode == 0:
                    logger.info("usque registration successful")
                    return True
                else:
                    logger.error(f"usque registration failed: {stderr.decode()}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error initializing usque: {e}")
            return False

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Start usque in proxy mode"""
        if not await self.initialize():
            logger.error("Failed to initialize usque backend")
            return False

        if await self.is_connected():
            logger.info("usque already running")
            return True

        return await self._connect_proxy()

    async def _connect_proxy(self) -> bool:
        """Start usque SOCKS5 proxy via supervisor"""
        try:
            logger.info(f"Starting usque service (proxy mode, port {self.socks5_port})...")
            # Update supervisor config if port changed
            await self._update_supervisor_usque_port()

            # Ensure clean state (clear FATAL/BACKOFF from previous runs)
            await self._run_command("supervisorctl stop usque")
            await asyncio.sleep(0.5)
            rc, _, _ = await self._run_command("supervisorctl start usque")
            if rc != 0:
                logger.error("Failed to start usque via supervisor")
                return False

            logger.info("Waiting for usque proxy to become ready...")
            for _ in range(15):
                if await self._is_proxy_connected():
                    logger.info("usque proxy started successfully")
                    return True
                await asyncio.sleep(1)

            logger.error("usque proxy failed to start (timeout)")
            return False
        except Exception as e:
            logger.error(f"Failed to start usque proxy: {e}")
            return False

    async def _update_supervisor_usque_port(self):
        """Update the usque supervisor config to use the current socks5_port."""
        import re as _re
        conf_paths = [
            "/etc/supervisor/conf.d/supervisord.conf",
            "/etc/supervisor/conf.d/warppool.conf",
        ]
        for conf_path in conf_paths:
            if not os.path.isfile(conf_path):
                continue
            try:
                with open(conf_path, "r") as f:
                    content = f.read()

                # Match: command=.../usque -c ... socks -b 0.0.0.0 -p <PORT>
                # Using regex to find existing port and replace
                # Assuming command structure
                new_cmd = f"command=/usr/local/bin/usque -c /var/lib/warp/config.json socks -b 0.0.0.0 -p {self.socks5_port}"
                updated = _re.sub(
                    r"command=/usr/local/bin/usque -c /var/lib/warp/config\.json socks -b 0\.0\.0\.0 -p \d+",
                    new_cmd,
                    content,
                )
                if updated != content:
                    with open(conf_path, "w") as f:
                        f.write(updated)
                    await self._run_command("supervisorctl reread")
                    await self._run_command("supervisorctl update")
                    logger.info(f"Updated usque supervisor config to port {self.socks5_port}")
            except Exception as e:
                logger.warning(f"Failed to update usque config in {conf_path}: {e}")

    async def disconnect(self) -> bool:
        """Stop usque service"""
        try:
            logger.info("Stopping usque services...")
            
            await self._run_command("supervisorctl stop usque")
            
            self.process = None
            self._invalidate_status_cache()
            return True
        except Exception as e:
            logger.error(f"Error stopping usque: {e}")
            return False

    # ------------------------------------------------------------------
    # Connectivity checks
    # ------------------------------------------------------------------

    async def _is_proxy_connected(self) -> bool:
        """Check if usque SOCKS5 proxy is running"""
        try:
            rc, stdout, _ = await self._run_command("supervisorctl status usque")
            if rc != 0 or "RUNNING" not in stdout:
                return False
        except Exception:
            return False
        return await self._is_port_open(self.socks5_port)

    async def is_connected(self) -> bool:
        """Check if usque is running"""
        return await self._is_proxy_connected()

    # ------------------------------------------------------------------
    # Status (Override common method if needed, otherwise use Base)
    # ------------------------------------------------------------------
    
    async def _get_status_uncached(self) -> Dict:
        # Get base status
        base = await super()._get_status_uncached()
        base["backend"] = "usque" # Explicitly set backend name if needed
        return base

    # ------------------------------------------------------------------
    # Custom operations
    # ------------------------------------------------------------------


