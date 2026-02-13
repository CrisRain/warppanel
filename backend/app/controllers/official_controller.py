# controller-app/app/official_controller.py
"""
OfficialController - WARP backend implementation using official Cloudflare client
Supports proxy mode with MASQUE / WireGuard protocols
"""
import asyncio
import logging
import os
from typing import Dict
from .base_controller import WarpBackendController

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OfficialController(WarpBackendController):

    def __init__(self, socks5_port: int = 1080):
        super().__init__(socks5_port=socks5_port)
        self.mute_backend_logs = False
        self.preferred_protocol = "masque" 

    @property
    def mode(self) -> str:
        return "proxy"

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def execute_command(self, command: str):
        """Execute warp-cli command"""
        try:
            rc, stdout, stderr = await self._run_command(command, timeout=10)
            if rc != 0:
                logger.error(f"Command '{command}' failed: {stderr.strip()}")
                return None
            return stdout.strip()
        except Exception as e:
            logger.error(f"Error executing '{command}': {e}")
            return None

    async def _is_daemon_responsive(self) -> bool:
        """Check if warp-svc is running AND responsive"""
        try:
            rc, stdout, _ = await self._run_command("supervisorctl status warp-svc")
            if rc != 0 or "RUNNING" not in stdout:
                return False
            
            # Use a short timeout for responsiveness check
            rc, _, _ = await self._run_command("warp-cli --accept-tos status", timeout=2)
            return rc == 0
        except Exception:
            return False

    async def _check_daemon_running(self) -> bool:
        return await self._is_daemon_responsive()

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Connect to WARP in proxy mode"""
        return await self._connect_proxy()

    async def _connect_proxy(self) -> bool:
        """Connect in proxy mode"""
        # Ensure registration exists first
        if not os.path.exists("/var/lib/cloudflare-warp/reg.json"):
            logger.info("No registration found, attempting to register...")
            await self.execute_command("warp-cli --accept-tos registration new")
            
        if not await self._is_daemon_responsive():
            logger.info("Daemon not ready, restarting services...")
            await self._stop_services()
            if not await self._start_services_proxy():
                logger.error("Failed to start official WARP services (proxy)")
                return False

        await self._ensure_socat()

        logger.info("Connecting WARP (official, proxy mode)...")
        
        # Reset mode first to ensure clean state
        await self.execute_command("warp-cli --accept-tos disconnect")
        
        # Configure
        await self.execute_command("warp-cli --accept-tos mode proxy")
        await self.execute_command("warp-cli --accept-tos proxy port 40001")
        await self.execute_command("warp-cli --accept-tos tunnel protocol set MASQUE")
        
        # Connect
        res = await self.execute_command("warp-cli --accept-tos connect")
        if res and "Error" in res:
             logger.error(f"Connect command returned error: {res}")

        await asyncio.sleep(2)

        if await self.wait_for_status("connected", timeout=30): 
            self.mute_backend_logs = True
            self._invalidate_status_cache()
            logger.info("Official WARP proxy connection successful")
            return True

        # Diagnostic log
        status = await self.execute_command("warp-cli --accept-tos status")
        logger.error(f"Official WARP proxy connection failed. Status: {status}")
        return False


    async def disconnect(self) -> bool:
        """Disconnect from WARP and stop services"""
        logger.info(f"Disconnecting WARP (official, proxy mode)...")
        self._invalidate_status_cache()

        try:
            await self.execute_command("warp-cli --accept-tos disconnect")
            await self.wait_for_status("disconnected", timeout=5)
        except Exception:
            pass

        await self._stop_services()
        logger.info("WARP disconnected successfully")
        return True

    # ------------------------------------------------------------------
    # Service management
    # ------------------------------------------------------------------

    async def _start_services_proxy(self) -> bool:
        """Start services for proxy mode"""
        try:
            logger.info("Starting background services (proxy mode)...")
            self.mute_backend_logs = False

            try:
                rc, _, _ = await self._run_command("supervisorctl start warp-svc")
                if rc != 0:
                     logger.error("Failed to start warp-svc")
                     return False
            except Exception:
                logger.error("Failed to start warp-svc")
                return False

            await asyncio.sleep(3)
            await self._ensure_socat()

            for _ in range(30):
                if await self._is_daemon_responsive():
                    logger.info("warp-svc is ready")
                    return await self._configure_warp_proxy()
                await asyncio.sleep(1)

            logger.error("Timed out waiting for warp-svc")
            return False
        except Exception as e:
            logger.error(f"Error starting proxy services: {e}")
            return False

    async def _configure_warp_proxy(self) -> bool:
        """Apply WARP configuration for proxy mode"""
        try:
            if not os.path.exists("/var/lib/cloudflare-warp/reg.json"):
                logger.info("Registering new WARP account...")
                await self.execute_command("warp-cli --accept-tos registration delete")
                await self.execute_command("warp-cli --accept-tos registration new")

            await self.execute_command("warp-cli --accept-tos tunnel protocol set MASQUE")
            await self.execute_command("warp-cli --accept-tos mode proxy")
            await self.execute_command("warp-cli --accept-tos proxy port 40001")
            return True
        except Exception as e:
            logger.error(f"Error configuring WARP proxy: {e}")
            return False


    async def _stop_services(self):
        """Stop all possible services (safe for both modes)"""
        logger.info("Stopping official services...")
        try:
            await self._run_command("supervisorctl stop socat")
            await self._run_command("supervisorctl stop warp-svc")
        except Exception as e:
            logger.error(f"Error stopping services: {e}")

    # ------------------------------------------------------------------
    # Auxiliary proxy helpers
    # ------------------------------------------------------------------

    async def _ensure_socat(self):
        """Ensure socat service is running with the correct SOCKS5 port (proxy mode only)"""
        if self.mode != "proxy":
            return

        # Update supervisor config if port differs from default
        await self._update_supervisor_socat_port()

        sys_active = False
        try:
            rc, stdout, _ = await self._run_command("supervisorctl status socat")
            sys_active = rc == 0 and "RUNNING" in stdout
        except Exception:
            pass

        port_open = await self._is_port_open(self.socks5_port)

        if sys_active and port_open:
            return

        logger.info(f"Starting socat service (port {self.socks5_port})...")
        try:
            # Stop first to pick up config changes
            await self._run_command("supervisorctl stop socat")
            await asyncio.sleep(0.3)
            await self._run_command("supervisorctl start socat")
            await asyncio.sleep(1)
            if not await self._is_port_open(self.socks5_port):
                logger.warning(f"Socat started but port {self.socks5_port} not listening yet")
                await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Error starting socat: {e}")

    async def _update_supervisor_socat_port(self):
        """Update the socat supervisor config to use the current socks5_port."""
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

                new_cmd = f"command=/usr/bin/socat TCP-LISTEN:{self.socks5_port},reuseaddr,bind=0.0.0.0,fork TCP:127.0.0.1:40001"
                updated = _re.sub(
                    r"command=/usr/bin/socat TCP-LISTEN:\d+,reuseaddr,bind=0\.0\.0\.0,fork TCP:127\.0\.0\.1:40001",
                    new_cmd,
                    content,
                )
                if updated != content:
                    with open(conf_path, "w") as f:
                        f.write(updated)
                    await self._run_command("supervisorctl reread")
                    await self._run_command("supervisorctl update")
                    logger.info(f"Updated socat supervisor config to port {self.socks5_port}")
            except Exception as e:
                logger.warning(f"Failed to update socat config in {conf_path}: {e}")


    # ------------------------------------------------------------------
    # Connectivity checks
    # ------------------------------------------------------------------

    async def is_connected(self) -> bool:
        """Check if WARP is connected"""
        if not await self._check_daemon_running():
            return False
        try:
            rc, stdout, _ = await self._run_command("warp-cli --accept-tos status", timeout=3)
            if rc != 0:
                return False
            output = stdout.lower()
            return "connected" in output and "disconnected" not in output
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    
    async def _get_status_uncached(self) -> Dict:
        base = await super()._get_status_uncached()
        base["backend"] = "official"
        return base
        


