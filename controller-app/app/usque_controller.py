# controller-app/app/usque_controller.py
"""
UsqueController - WARP backend implementation using usque
"""
import subprocess
import logging
import psutil
import time
from typing import Optional, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UsqueController:
    """Control usque MASQUE WARP client"""
    
    def __init__(self, config_path="/var/lib/warp/config.json", socks5_port=1080):
        self.config_path = config_path
        self.socks5_port = socks5_port
        self.process: Optional[subprocess.Popen] = None
    
    def initialize(self) -> bool:
        """Initialize usque backend (register if needed)"""
        import os
        try:
            # Create config dir
            config_dir = os.path.dirname(self.config_path)
            os.makedirs(config_dir, exist_ok=True)
            
            # Register if config doesn't exist
            if not os.path.exists(self.config_path):
                logger.info("Config not found, registering new usque account...")
                # Run usque register
                # input "y" to confirm license if needed, though 'usque register' usually just works or needs interactive.
                # entrypoint used: echo "y" | usque register
                process = subprocess.Popen(
                    ["usque", "register"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=config_dir # Run in dir so it might save there? entrypoint cd-ed there
                )
                stdout, stderr = process.communicate(input="y\n")
                
                if process.returncode == 0:
                    logger.info("usque registration successful")
                    return True
                else:
                    logger.error(f"usque registration failed: {stderr}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error initializing usque: {e}")
            return False

    def connect(self) -> bool:
        """Start usque SOCKS5 proxy"""
        # Ensure initialized (registered)
        if not self.initialize():
            logger.error("Failed to initialize usque backend")
            return False

        if self.is_connected():
            logger.info("usque already running")
            return True
            
        try:
            cmd = [
                "usque",
                "-c", self.config_path,
                "socks",
                "-b", "0.0.0.0",
                "-p", str(self.socks5_port),

            ]
            
            logger.info(f"Starting usque: {' '.join(cmd)}")
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Wait for startup
            time.sleep(3)
            
            # Check if process is still running
            if self.process.poll() is None:
                logger.info("usque started successfully")
                return True
            else:
                stderr = self.process.stderr.read().decode() if self.process.stderr else ""
                logger.error(f"usque process exited: {stderr}")
                return False
        
        except Exception as e:
            logger.error(f"Failed to start usque: {e}")
            return False
    
    def disconnect(self) -> bool:
        """Stop usque"""
        if self.process:
            try:
                logger.info("Stopping usque...")
                self.process.terminate()
                self.process.wait(timeout=5)
                logger.info("usque stopped successfully")
                self.process = None
                return True
            except subprocess.TimeoutExpired:
                logger.warning("usque didn't stop gracefully, killing...")
                self.process.kill()
                self.process = None
                return False
            except Exception as e:
                logger.error(f"Error stopping usque: {e}")
                return False
        
        # Try to kill any usque process on the port
        try:
            for conn in psutil.net_connections():
                if conn.laddr.port == self.socks5_port and conn.status == 'LISTEN':
                    proc = psutil.Process(conn.pid)
                    if 'usque' in proc.name().lower():
                        proc.kill()
                        logger.info(f"Killed usque process (PID: {conn.pid})")
        except:
            pass
        
        return True
    
    def is_connected(self) -> bool:
        """Check if usque is running AND connected (can reach Cloudflare)"""
        # 1. Check if process/port is listening first (quick check)
        is_running = False
        if self.process and self.process.poll() is None:
            is_running = True
        else:
            # Check if port is listening
            try:
                for conn in psutil.net_connections():
                    if conn.laddr.port == self.socks5_port and conn.status == 'LISTEN':
                        is_running = True
                        break
            except:
                pass
        
        if not is_running:
            return False

        # 2. Check actual connectivity
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-x", f"socks5h://127.0.0.1:{self.socks5_port}",
                    "-s",
                    "--max-time", "5",
                    "https://www.cloudflare.com/cdn-cgi/trace"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def get_status(self) -> Dict:
        """Get connection status and IP information"""
        base_status = {
            "backend": "usque",
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
            logger.warning("Timeout getting IP info through proxy")
        except Exception as e:
            logger.error(f"Error getting IP info: {e}")
        
        return base_status
    
    def wait_for_status(self, target_status: str, timeout: int = 15) -> bool:
        """Wait for specific status"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_status()
            if status.get("status") == target_status:
                return True
            time.sleep(1)
        return False
    
    def rotate_ip_simple(self) -> bool:
        """Rotate IP by reconnecting"""
        logger.info("Rotating IP (disconnect + reconnect)...")
        
        # Disconnect
        self.disconnect()
        self.wait_for_status("disconnected", timeout=5)
        
        # Wait a bit
        time.sleep(2)
        
        # Reconnect
        if self.connect():
            return self.wait_for_status("connected", timeout=15)
        
        return False
    
    def _get_city_from_colo(self, colo: str) -> str:
        """Map Cloudflare colo code to city name"""
        city_map = {
            "LAX": "Los Angeles", "SJC": "San Jose", "ORD": "Chicago",
            "IAD": "Ashburn", "EWR": "Newark", "MIA": "Miami",
            "DFW": "Dallas", "SEA": "Seattle", "ATL": "Atlanta",
            "LHR": "London", "CDG": "Paris", "FRA": "Frankfurt",
            "AMS": "Amsterdam", "SIN": "Singapore", "HKG": "Hong Kong",
            "NRT": "Tokyo", "SYD": "Sydney", "ICN": "Seoul",
            "BOM": "Mumbai", "GRU": "São Paulo", "YVR": "Vancouver",
            "YYZ": "Toronto", "MEL": "Melbourne", "DXB": "Dubai"
        }
        return city_map.get(colo.upper(), colo)
    
    def _get_country_name(self, loc_code: str) -> str:
        """Map country code to full name"""
        country_map = {
            "US": "United States", "CN": "China", "JP": "Japan",
            "GB": "United Kingdom", "DE": "Germany", "FR": "France",
            "CA": "Canada", "AU": "Australia", "SG": "Singapore",
            "IN": "India", "BR": "Brazil", "KR": "South Korea",
            "NL": "Netherlands", "SE": "Sweden", "IT": "Italy",
            "ES": "Spain", "RU": "Russia", "HK": "Hong Kong",
            "TW": "Taiwan", "MX": "Mexico", "AR": "Argentina"
        }
        return country_map.get(loc_code.upper(), loc_code)
