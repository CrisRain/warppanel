# controller-app/app/official_controller.py
"""
OfficialController - WARP backend implementation using official Cloudflare client
"""
import subprocess
import logging
import os
import time
import threading
from typing import Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OfficialController:
    """Control official Cloudflare WARP client"""
    
    def __init__(self, socks5_port: int = 1080):
        self.socks5_port = socks5_port
        self.mute_backend_logs = False

    def _stream_logs(self, process, name):
        """Read logs from process and log them until muted"""
        try:
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                # Only log if not muted
                if not self.mute_backend_logs:
                    logger.debug(f"[{name}] {line.strip()}")
        except Exception:
            pass

    def execute_command(self, command: str):
        """Execute warp-cli command"""
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                logger.error(f"Command '{command}' failed: {result.stderr.strip()}")
                return None
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"Error executing '{command}': {e}")
            return None

    def connect(self) -> bool:
        """Connect to WARP"""
        # Ensure daemon and proxy are running and responsive
        if not self._is_daemon_responsive():
            logger.info("Daemon not ready, restarting services...")
            # If process exists but not responsive, kill it first
            self._stop_services()
            if not self._start_services():
                logger.error("Failed to start official WARP services")
                return False
        
        # Ensure socat is running (in case daemon was running but proxy died)
        self._ensure_socat()

        logger.info("Connecting WARP (official)...")
        # Explicitly set mode and port again just in case, similar to entrypoint.sh acting every time
        self.execute_command("warp-cli --accept-tos mode proxy")
        self.execute_command("warp-cli --accept-tos proxy port 40001")
        
        output = self.execute_command("warp-cli --accept-tos connect")
        # Output logging removed as per user request
        
        # Wait a moment for state change
        time.sleep(2)
        
        if self.wait_for_status("connected", timeout=600):
            # Mute backend logs after successful connection
            self.mute_backend_logs = True
            logger.info("Official WARP connection successful")
            return True
        
        # Debug why it failed
        # status_output = self.execute_command("warp-cli --accept-tos status")
        logger.error("Official WARP connection failed")
        return False

    def disconnect(self) -> bool:
        """Disconnect from WARP and stop services"""
        logger.info("Disconnecting WARP (official)...")
        
        # Try graceful disconnect first
        try:
            self.execute_command("warp-cli --accept-tos disconnect")
            self.wait_for_status("disconnected", timeout=5)
        except:
            pass
            
        # Stop background services
        self._stop_services()
        return True

    def _is_daemon_responsive(self) -> bool:
        """Check if warp-svc is running AND responsive"""
        try:
            # 1. Check systemd status
            # systemctl is-active returns 0 if active
            res = subprocess.run(
                ["systemctl", "is-active", "warp-svc"], 
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if res.returncode != 0:
                return False

            # 2. Check responsiveness
            # warp-cli status returns error code if daemon unreachable
            result = subprocess.run(
                "warp-cli --accept-tos status", 
                shell=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                timeout=2
            )
            return result.returncode == 0
            
        except Exception:
            return False

    def _check_daemon_running(self) -> bool:
        """Deprecated: Use _is_daemon_responsive"""
        return self._is_daemon_responsive()

    def _start_services(self) -> bool:
        """Start warp-svc via systemd and socat"""
        try:
            logger.info("Starting background services (systemd)...")
            
            # Reset mute flag on start
            self.mute_backend_logs = False
            
            # 1. Start warp-svc via systemd
            # This handles dbus and dependencies automatically
            try:
                subprocess.run(["systemctl", "start", "warp-svc"], check=True)
            except subprocess.CalledProcessError:
                logger.error("Failed to start warp-svc via systemctl")
                return False
            
            # logging removed as per user request
            time.sleep(3)
            
            # Start socat early as requested
            self._ensure_socat()
            
            # 3. Wait for readiness and configure
            for i in range(30):
                if self._is_daemon_responsive():
                    logger.info("warp-svc is ready")
                    
                    if self._configure_warp():
                        return True
                    else:
                        return False
                time.sleep(1)
                
            logger.error("Timed out waiting for warp-svc to become responsive")
            return False
        except Exception as e:
            logger.error(f"Error starting services: {e}")
            return False

    def _configure_warp(self) -> bool:
        """Apply WARP configuration (Register, MASQUE, Proxy Mode)"""
        try:
            # Register if needed
            if not os.path.exists("/var/lib/cloudflare-warp/reg.json"):
                logger.info("Registering new WARP account...")
                self.execute_command("warp-cli --accept-tos registration delete")
                self.execute_command("warp-cli --accept-tos registration new")
            
            # Force WireGuard protocol (default) to avoid MASQUE issues seen in logs
            # implicitly resets protocol if it was changed
            self.execute_command("warp-cli --accept-tos tunnel protocol set MASQUE")
            
            # Configure Proxy Mode
            self.execute_command("warp-cli --accept-tos mode proxy")
            self.execute_command("warp-cli --accept-tos proxy port 40001")
            
            return True
        except Exception as e:
            logger.error(f"Error configuring WARP: {e}")
            return False

    def _stop_services(self):
        """Stop warp-svc and socat"""
        logger.info("Stopping official services (systemd)...")
        try:
            # Stop socat via systemd
            subprocess.run(["systemctl", "stop", "socat"], check=False)
            
            # Stop warp-svc via systemd
            subprocess.run(["systemctl", "stop", "warp-svc"], check=False)
            
        except Exception as e:
            logger.error(f"Error stopping services: {e}")

    def _is_port_open(self, port: int) -> bool:
        """Check if port is listening using ss"""
        try:
            result = subprocess.run(
                ["ss", "-lnt", f"sport = :{port}"],
                capture_output=True,
                text=True
            )
            return f":{port}" in result.stdout
        except Exception:
            return False

    def _ensure_socat(self):
        """Ensure socat service is running and listening"""
        sys_active = False
        try:
            # Check if socat service is active
            res = subprocess.run(
                ["systemctl", "is-active", "socat"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            sys_active = res.returncode == 0
        except Exception:
            pass
            
        # Also check if it's actually listening
        port_open = self._is_port_open(self.socks5_port)
            
        if sys_active and port_open:
            return

        logger.info("Starting socat service...")
        try:
            subprocess.run(["systemctl", "start", "socat"], check=True)
            
            # Wait a moment for port to open
            time.sleep(1)
            
            # Verify port
            if not self._is_port_open(self.socks5_port):
                logger.warning(f"Socat started but port {self.socks5_port} is not listening yet")
                # Maybe wait a bit longer?
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Error starting socat: {e}")

    def is_connected(self) -> bool:
        """Check if WARP is connected and daemon is running"""
        if not self._check_daemon_running():
            return False
            
        try:
            # Run status command silently
            result = subprocess.run(
                "warp-cli --accept-tos status", 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                return False
                
            output = result.stdout.lower()
            return "connected" in output and "disconnected" not in output
        except Exception:
            return False

    def get_status(self) -> Dict:
        """Get connection status and IP information"""
        base_status = {
            "backend": "official",
            "status": "disconnected",
            "ip": "Unknown",
            "location": "Unknown",
            "city": "Unknown",
            "country": "Unknown",
            "isp": "Cloudflare WARP",
            "warp_protocol": "MASQUE",
            "connection_time": "Unknown",
            "network_type": "Unknown",
            "proxy_address": f"socks5://127.0.0.1:{self.socks5_port}",
            "details": {}
        }
        
        if not self.is_connected():
            return base_status
        
        base_status["status"] = "connected"
        
        # Get IP info through the proxy
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-x", f"socks5h://127.0.0.1:{self.socks5_port}",
                    "-s",
                    "--max-time", "10",
                    "https://www.cloudflare.com/cdn-cgi/trace"
                ],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode == 0 and result.stdout:
                info = {}
                for line in result.stdout.split('\n'):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        info[k.strip()] = v.strip()
                
                base_status["ip"] = info.get("ip", "Unknown")
                base_status["location"] = info.get("loc", "Unknown")
                
                colo = info.get("colo", "")
                if colo:
                    base_status["city"] = self._get_city_from_colo(colo)
                
                loc_code = info.get("loc", "")
                if loc_code:
                    base_status["country"] = self._get_country_name(loc_code)
                
                base_status["details"]["trace"] = info
                
        except subprocess.TimeoutExpired:
            # logger.warning("Timeout getting IP info through proxy")
            pass
        except Exception as e:
            # logger.error(f"Error getting IP info: {e}")
            pass
        
        return base_status

    def wait_for_status(self, target_status: str, timeout: int = 15) -> bool:
        """Wait for specific connection status"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_status()
            if status.get("status") == target_status:
                return True
            time.sleep(1)
        return False

    def rotate_ip_simple(self) -> bool:
        """Rotate IP by disconnecting and reconnecting"""
        logger.info("Rotating IP (official: disconnect + reconnect)...")
        
        self.disconnect()
        # After disconnect, services are stopped. 
        # But connect() restarts them.
        
        # We need to wait a bit
        time.sleep(2)
        
        if self.connect():
            return self.wait_for_status("connected", timeout=15)
        
        return False

    def set_custom_endpoint(self, endpoint: str) -> bool:
        """Set custom endpoint using warp-cli"""
        try:
            if not endpoint:
                # Reset
                logger.info("Resetting custom endpoint (official)...")
                cmd = "warp-cli --accept-tos tunnel endpoint reset"
            else:
                # Set
                logger.info(f"Setting custom endpoint to {endpoint} (official)...")
                cmd = f"warp-cli --accept-tos tunnel endpoint set {endpoint}"
            
            res = self.execute_command(cmd)
            # warp-cli usually returns minimal output on success, or "Success"
            # execute_command returns stdout (string) or None on failure.
            
            # Restart/Reconnect might be needed? 
            # Usually endpoint changes apply immediately or on next connect.
            # Let's force reconnect to be safe and consistent with usque behavior
            if self.is_connected():
                # self.disconnect() # Disconnect is slow/heavy
                # Just disconnect logic?
                # Actually official client might just need a reconnect.
                # Let's try to just return True, caller might decide to reconnect?
                # But usque reconnects. Let's be consistent.
                self.disconnect()
                time.sleep(2)
                return self.connect()

            return True

        except Exception as e:
            logger.error(f"Failed to set custom endpoint: {e}")
            return False

    def _get_city_from_colo(self, colo: str) -> str:
        """Map Cloudflare colo code to city"""
        city_map = {
            "LAX": "Los Angeles", "SJC": "San Jose", "ORD": "Chicago",
            "IAD": "Ashburn", "EWR": "Newark", "MIA": "Miami",
            "DFW": "Dallas", "SEA": "Seattle", "ATL": "Atlanta",
            "LHR": "London", "CDG": "Paris", "FRA": "Frankfurt",
            "AMS": "Amsterdam", "SIN": "Singapore", "HKG": "Hong Kong",
            "NRT": "Tokyo", "SYD": "Sydney", "ICN": "Seoul",
            "BOM": "Mumbai", "GRU": "São Paulo"
        }
        return city_map.get(colo.upper(), colo)

    def _get_country_name(self, loc_code: str) -> str:
        """Map country code to name"""
        country_map = {
            "US": "United States", "CN": "China", "JP": "Japan",
            "GB": "United Kingdom", "DE": "Germany", "FR": "France",
            "CA": "Canada", "AU": "Australia", "SG": "Singapore",
            "IN": "India", "BR": "Brazil", "KR": "South Korea",
            "NL": "Netherlands", "SE": "Sweden", "IT": "Italy",
            "ES": "Spain", "RU": "Russia", "HK": "Hong Kong",
            "TW": "Taiwan"
        }
        return country_map.get(loc_code.upper(), loc_code)
