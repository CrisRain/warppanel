# controller-app/app/usque_controller.py
"""
UsqueController - WARP backend implementation using usque
"""
import subprocess
import logging
import psutil
import time
import json
import os
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
        """Start usque SOCKS5 proxy via systemd"""
        # Ensure initialized (registered)
        if not self.initialize():
            logger.error("Failed to initialize usque backend")
            return False

        if self.is_connected():
            logger.info("usque already running")
            return True
            
        try:
            logger.info("Starting usque service...")
            # Use systemctl to start service
            subprocess.run(["systemctl", "start", "usque"], check=True)
            
            # Wait for startup
            time.sleep(3)
            
            if self.is_connected():
                logger.info("usque started successfully")
                return True
            else:
                logger.error("usque service failed to start or is inactive")
                return False
        
        except Exception as e:
            logger.error(f"Failed to start usque: {e}")
            return False
    
    def disconnect(self) -> bool:
        """Stop usque via systemd"""
        try:
            logger.info("Stopping usque service...")
            subprocess.run(["systemctl", "stop", "usque"], check=False)
            self.process = None # Clear legacy process handle if any
            return True
        except Exception as e:
            logger.error(f"Error stopping usque: {e}")
            return False
    
    def _is_port_open(self, port: int) -> bool:
        """Check if port is listening using ss"""
        try:
            # ss -lnt sport = :<port>
            # Use basic string matching for robustness
            result = subprocess.run(
                ["ss", "-lnt", f"sport = :{port}"],
                capture_output=True,
                text=True
            )
            return f":{port}" in result.stdout
        except Exception:
            return False

    def is_connected(self) -> bool:
        """Check if usque is running via systemd"""
        # 1. Check service status
        try:
            res = subprocess.run(
                ["systemctl", "is-active", "usque"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            is_active = (res.returncode == 0)
        except Exception:
            is_active = False
        
        if not is_active:
            return False

        # 2. Check if port is listening (faster than curl)
        if not self._is_port_open(self.socks5_port):
            return False

        # 3. Check actual connectivity
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
    
    def set_custom_endpoint(self, endpoint: str) -> bool:
        """Set custom endpoint in config.json and restart"""
        try:
            # Validate format: usque config usually takes IP or IP:PORT?
            # User request: "usque的endpoint不能加端口" -> usque endpoint CANNOT have port? 
            # If so, we should STRIP port if present or Validate to NOT have port.
            # OR maybe user means "I provided port and it failed, so it shouldn't require one".
            # Let's relax validation. 
            # If user explicitly says "cannot add port", maybe they mean the input shouldn't have it.
            # But earlier we saw config had "162.159.192.1:443".
            # Wait, let's re-read the user request carefully: "usque的endpoint不能加端口"
            # It translates to "usque's endpoint cannot add port".
            # This might mean:
            # 1. The code I added forcing IP:PORT is wrong because usque handles it differently or user wants IP only.
            # 2. Or providing port breaks it.
            # Given the previous config showed ports, maybe my validation is too strict or blocked valid input.
            # Let's remove the strict IP:PORT check and just allow non-empty strings.
            # And if user provides IP:PORT, let it pass. If IP only, let it pass.
            
            # Actually, looking at the previous traces, the user previously successfully set it with port via python script.
            # "d['endpoint_v4']='162.159.192.1:443'"
            # So port IS allowed in config.
            # The user might be saying my VALIDATION rejected their input which maybe didn't have a port?
            # OR the user tried to put a port and it failed for some reason?
            # But the user said "usque endpoint cannot add port".
            # This is ambiguous. It could mean "I can't add a port" (system prevents it) or "It MUST NOT have a port".
            # But since config had 443, it likely CAN have a port.
            # I will assume the user wants me to REMOVE the validation that REQUIRES a port.
            
            if not os.path.exists(self.config_path):
                logger.error("Config file not found")
                return False
            
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            if not endpoint:
                # Reset/Clear
                if "endpoint_v4" in config:
                    del config["endpoint_v4"]
            else:
                config["endpoint_v4"] = endpoint
            
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            logger.info(f"Updated usque endpoint to: {endpoint}")
            
            # Restart if connected
            if self.is_connected():
                self.disconnect()
                time.sleep(1)
                return self.connect()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to set custom endpoint: {e}")
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
