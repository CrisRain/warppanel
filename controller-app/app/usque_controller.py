# controller-app/app/usque_controller.py
"""
UsqueController - WARP backend implementation using usque
Supports both proxy mode (SOCKS5) and TUN mode
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
    """Control usque MASQUE WARP client (proxy + TUN modes)"""

    # Class-level status cache
    _status_cache = None
    _status_cache_time = 0
    _STATUS_CACHE_TTL = 8  # seconds

    def __init__(self, config_path="/var/lib/warp/config.json", socks5_port=1080, http_port=8080):
        self.config_path = config_path
        self.socks5_port = socks5_port
        self.http_port = http_port
        self.process: Optional[subprocess.Popen] = None
        self._cached_ip_info: Optional[Dict] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 120  # Cache IP info for 120 seconds
        self._mode = os.getenv("WARP_MODE", "proxy")  # 'proxy' or 'tun'

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> bool:
        """Switch between proxy and tun mode. Disconnects first."""
        if mode not in ("proxy", "tun"):
            logger.error(f"Invalid mode: {mode}. Use 'proxy' or 'tun'")
            return False
        if mode == self._mode:
            logger.info(f"Already in {mode} mode")
            return True

        logger.info(f"Switching usque mode from {self._mode} to {mode}")
        self.disconnect()
        time.sleep(2)
        self._mode = mode
        os.environ["WARP_MODE"] = mode
        self._invalidate_status_cache()
        return True

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Initialize usque backend (register if needed)"""
        try:
            config_dir = os.path.dirname(self.config_path)
            os.makedirs(config_dir, exist_ok=True)

            if not os.path.exists(self.config_path):
                logger.info("Config not found, registering new usque account...")
                process = subprocess.Popen(
                    ["usque", "register"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=config_dir,
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

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Start usque in the current mode"""
        if not self.initialize():
            logger.error("Failed to initialize usque backend")
            return False

        if self.is_connected():
            logger.info(f"usque already running in {self._mode} mode")
            return True

        if self._mode == "tun":
            return self._connect_tun()
        else:
            return self._connect_proxy()

    def _connect_proxy(self) -> bool:
        """Start usque SOCKS5 proxy via supervisor"""
        try:
            logger.info("Starting usque service (proxy mode)...")
            # Ensure clean state (clear FATAL/BACKOFF from previous runs)
            subprocess.run(["supervisorctl", "stop", "usque"], check=False)
            time.sleep(0.5)
            subprocess.run(["supervisorctl", "start", "usque"], check=True)

            logger.info("Waiting for usque proxy to become ready...")
            for _ in range(15):
                if self._is_proxy_connected():
                    logger.info("usque proxy started successfully")
                    self._start_http_proxy()
                    return True
                time.sleep(1)

            logger.error("usque proxy failed to start (timeout)")
            return False
        except Exception as e:
            logger.error(f"Failed to start usque proxy: {e}")
            return False

    def _connect_tun(self) -> bool:
        """Start usque nativetun + set up routing + start gost proxy listeners."""
        try:
            logger.info("Starting usque service (TUN mode: nativetun)...")
            # Ensure clean state
            subprocess.run(["supervisorctl", "stop", "usque"], check=False)
            subprocess.run(["supervisorctl", "stop", "usque-tun"], check=False)
            subprocess.run(["supervisorctl", "stop", "tun-proxy"], check=False)
            time.sleep(0.5)

            # Save original default route before TUN modifies anything
            orig_gw, orig_iface, orig_ip = self._get_default_route()

            # Start usque nativetun (creates tun0 interface)
            subprocess.run(["supervisorctl", "start", "usque-tun"], check=True)

            logger.info("Waiting for TUN interface to come up...")
            for _ in range(20):
                if self._tun_interface_exists():
                    break
                time.sleep(1)
            else:
                logger.error("TUN interface failed to appear (timeout)")
                return False

            # Set up routing with policy-based split
            self._setup_tun_routing(orig_gw, orig_iface, orig_ip)

            # Start gost as plain SOCKS5 + HTTP listener;
            # since default route is now through tun0, traffic goes through WARP
            logger.info("Starting tun-proxy (gost SOCKS5 + HTTP)...")
            subprocess.run(["supervisorctl", "start", "tun-proxy"], check=True)

            for _ in range(10):
                if self._is_port_open(self.socks5_port):
                    logger.info("usque TUN mode started successfully")
                    return True
                time.sleep(1)

            logger.error("tun-proxy failed to start (timeout)")
            return False
        except Exception as e:
            logger.error(f"Failed to start usque TUN: {e}")
            return False

    def disconnect(self) -> bool:
        """Stop all usque services (both modes, prevents stale FATAL states)"""
        try:
            logger.info("Stopping usque services...")
            # Always stop ALL services to avoid leftover FATAL/BACKOFF states
            subprocess.run(["supervisorctl", "stop", "tun-proxy"], check=False)
            subprocess.run(["supervisorctl", "stop", "http-proxy"], check=False)
            subprocess.run(["supervisorctl", "stop", "usque-tun"], check=False)
            subprocess.run(["supervisorctl", "stop", "usque"], check=False)

            # Clean up TUN routing if tun0 was active
            self._cleanup_tun_routing()

            self.process = None
            self._invalidate_status_cache()
            return True
        except Exception as e:
            logger.error(f"Error stopping usque: {e}")
            return False

    # ------------------------------------------------------------------
    # Auxiliary proxy helpers
    # ------------------------------------------------------------------

    def _start_http_proxy(self):
        """Start HTTP proxy that chains through SOCKS5 (proxy mode)"""
        try:
            res = subprocess.run(
                ["supervisorctl", "status", "http-proxy"],
                capture_output=True, text=True,
            )
            if "RUNNING" in res.stdout:
                return
            logger.info("Starting HTTP proxy (proxy mode)...")
            subprocess.run(["supervisorctl", "start", "http-proxy"], check=False)
        except Exception as e:
            logger.warning(f"Failed to start HTTP proxy: {e}")

    # ------------------------------------------------------------------
    # TUN routing helpers
    # ------------------------------------------------------------------

    def _get_default_route(self):
        """Get original default gateway, interface, and container IP."""
        gw, iface, ip = None, None, None
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=5,
            )
            line = result.stdout.strip().split('\n')[0]
            parts = line.split()
            if 'via' in parts and 'dev' in parts:
                gw = parts[parts.index('via') + 1]
                iface = parts[parts.index('dev') + 1]
        except Exception as e:
            logger.warning(f"Could not get default route: {e}")
            return None, None, None

        # Get primary IP on that interface
        if iface:
            try:
                result = subprocess.run(
                    ["ip", "-4", "-o", "addr", "show", "dev", iface],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.strip().split('\n'):
                    if 'inet ' in line:
                        # Format: "N: eth0  inet 172.18.0.2/16 ..."
                        ip = line.split('inet ')[1].split('/')[0]
                        break
            except Exception:
                pass

        if gw and iface:
            logger.info(f"Original default route: via {gw} dev {iface}, IP {ip}")
        return gw, iface, ip

    def _tun_interface_exists(self) -> bool:
        """Check if a tun interface (tun0, tun1, ...) exists."""
        try:
            result = subprocess.run(
                ["ip", "link", "show", "type", "tun"],
                capture_output=True, text=True, timeout=5,
            )
            return "tun" in result.stdout
        except Exception:
            return False

    def _get_tun_interface_name(self) -> Optional[str]:
        """Get the name of the first tun interface."""
        try:
            result = subprocess.run(
                ["ip", "-o", "link", "show", "type", "tun"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    # Format: "N: tunX: ..."
                    parts = line.split(':')
                    if len(parts) >= 2:
                        return parts[1].strip()
        except Exception:
            pass
        return None

    def _get_warp_endpoint(self) -> Optional[str]:
        """Read endpoint_v4 from usque config.json."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                return config.get("endpoint_v4")
        except Exception as e:
            logger.warning(f"Could not read endpoint from config: {e}")
        return None

    def _setup_tun_routing(self, orig_gw: Optional[str], orig_iface: Optional[str], orig_ip: Optional[str]):
        """Set up policy-based routing for usque nativetun.

        Strategy:
        1. Create routing table 100 with original default gateway
        2. Add ip rule: traffic from container's own IP uses table 100
           (ensures panel/proxy response traffic bypasses the TUN)
        3. Route the WARP endpoint through original gateway (prevent loop)
        4. Set default route through tun interface (all other traffic → WARP)
        """
        tun_name = self._get_tun_interface_name() or "tun0"
        endpoint = self._get_warp_endpoint()

        # 1. Policy routing: response traffic from our IP uses original gateway
        if orig_gw and orig_iface and orig_ip:
            logger.info(f"Setting up policy route: from {orig_ip} → table 100 via {orig_gw} dev {orig_iface}")
            subprocess.run(
                f"ip route add default via {orig_gw} dev {orig_iface} table 100",
                shell=True, check=False,
            )
            # Copy connected-subnet routes so ARP works in table 100
            res = subprocess.run(
                f"ip route show dev {orig_iface} scope link",
                capture_output=True, text=True, shell=True,
            )
            for line in res.stdout.strip().split('\n'):
                subnet = line.split()[0] if line.strip() else None
                if subnet:
                    subprocess.run(
                        f"ip route add {subnet} dev {orig_iface} table 100",
                        shell=True, check=False,
                    )
            # Remove stale rule, then add
            subprocess.run(f"ip rule del from {orig_ip} lookup 100 2>/dev/null", shell=True, check=False)
            subprocess.run(f"ip rule add from {orig_ip} lookup 100", shell=True, check=False)
        else:
            logger.warning("Missing orig_gw/iface/ip, skipping policy route (panel may be inaccessible in TUN mode)")

        # 2. Route WARP endpoint through original gateway (prevent routing loop)
        if orig_gw and orig_iface and endpoint:
            logger.info(f"Routing WARP endpoint {endpoint} via {orig_gw} dev {orig_iface}")
            subprocess.run(
                f"ip route add {endpoint}/32 via {orig_gw} dev {orig_iface}",
                shell=True, check=False,
            )

        # 3. Set default route through TUN
        subprocess.run(
            f"ip route replace default dev {tun_name}",
            shell=True, check=False,
        )
        logger.info(f"TUN routing configured: default via {tun_name}, policy from {orig_ip} via table 100")

    def _cleanup_tun_routing(self):
        """Remove TUN routing: policy rule, table 100, endpoint route."""
        try:
            # Remove ip rule for container IP
            result = subprocess.run(
                "ip rule show", shell=True,
                capture_output=True, text=True,
            )
            for line in result.stdout.strip().split('\n'):
                if 'lookup 100' in line:
                    # Extract "from X.X.X.X"
                    parts = line.split()
                    if 'from' in parts:
                        ip = parts[parts.index('from') + 1]
                        subprocess.run(f"ip rule del from {ip} lookup 100", shell=True, check=False)

            # Flush table 100
            subprocess.run("ip route flush table 100 2>/dev/null", shell=True, check=False)

            # Remove endpoint route
            endpoint = self._get_warp_endpoint()
            if endpoint:
                subprocess.run(
                    f"ip route del {endpoint}/32 2>/dev/null",
                    shell=True, check=False,
                )
            # Default route will be restored automatically when tun goes down
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Connectivity checks
    # ------------------------------------------------------------------

    def _is_port_open(self, port: int) -> bool:
        """Check if port is listening using ss"""
        try:
            result = subprocess.run(
                ["ss", "-lnt", f"sport = :{port}"],
                capture_output=True, text=True,
            )
            return f":{port}" in result.stdout
        except Exception:
            return False

    def _is_proxy_connected(self) -> bool:
        """Check if usque SOCKS5 proxy is running"""
        try:
            res = subprocess.run(
                ["supervisorctl", "status", "usque"],
                capture_output=True, text=True,
            )
            if res.returncode != 0 or "RUNNING" not in res.stdout:
                return False
        except Exception:
            return False
        return self._is_port_open(self.socks5_port)

    def _is_tun_connected(self) -> bool:
        """Check if usque nativetun is running and tun interface exists."""
        try:
            res = subprocess.run(
                ["supervisorctl", "status", "usque-tun"],
                capture_output=True, text=True,
            )
            if res.returncode != 0 or "RUNNING" not in res.stdout:
                return False
        except Exception:
            return False
        return self._tun_interface_exists()

    def is_connected(self) -> bool:
        """Check if usque is running in current mode"""
        if self._mode == "tun":
            return self._is_tun_connected()
        return self._is_proxy_connected()

    # ------------------------------------------------------------------
    # Status / IP Info
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Get connection status and IP information (cached)"""
        now = time.time()
        if (
            UsqueController._status_cache is not None
            and now - UsqueController._status_cache_time < UsqueController._STATUS_CACHE_TTL
        ):
            return UsqueController._status_cache

        status = self._get_status_uncached()
        UsqueController._status_cache = status
        UsqueController._status_cache_time = now
        return status

    def _invalidate_status_cache(self):
        UsqueController._status_cache = None
        UsqueController._status_cache_time = 0

    def _get_status_uncached(self) -> Dict:
        base_status = {
            "backend": "usque",
            "status": "disconnected",
            "ip": "Unknown",
            "location": "Unknown",
            "city": "Unknown",
            "country": "Unknown",
            "isp": "Cloudflare WARP",
            "warp_protocol": "MASQUE",
            "warp_mode": self._mode,
            "connection_time": "Unknown",
            "network_type": "Unknown",
            "proxy_address": f"socks5://127.0.0.1:{self.socks5_port}",
            "http_proxy_address": f"http://127.0.0.1:{self.http_port}",
            "details": {},
        }

        if not self.is_connected():
            self._cached_ip_info = None
            return base_status

        base_status["status"] = "connected"

        now = time.time()
        if self._cached_ip_info and (now - self._cache_time) < self._cache_ttl:
            base_status.update(self._cached_ip_info)
            return base_status

        ip_info = self._fetch_ip_info()
        if ip_info:
            self._cached_ip_info = ip_info
            self._cache_time = now
            base_status.update(ip_info)
        elif self._cached_ip_info:
            base_status.update(self._cached_ip_info)

        return base_status

    def _fetch_ip_info(self) -> Optional[Dict]:
        """Fetch IP info. Proxy mode: via SOCKS5. TUN mode: direct (traffic goes through tun)."""
        try:
            if self._mode == "tun":
                cmd = [
                    "curl", "-s", "--max-time", "5",
                    "http://ip-api.com/json/?fields=status,message,query,country,city,isp",
                ]
            else:
                cmd = [
                    "curl",
                    "-x", f"socks5h://127.0.0.1:{self.socks5_port}",
                    "-s", "--max-time", "5",
                    "http://ip-api.com/json/?fields=status,message,query,country,city,isp",
                ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)

            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get("status") == "success":
                    isp_value = data.get("isp") or "Cloudflare WARP"
                    return {
                        "ip": data.get("query") or "Unknown",
                        "country": data.get("country") or "Unknown",
                        "city": data.get("city") or "Unknown",
                        "location": data.get("country") or "Unknown",
                        "isp": isp_value,
                        "details": {"isp": isp_value},
                    }
                else:
                    logger.warning("IP API returned failure: %s", data.get("message"))
        except subprocess.TimeoutExpired:
            logger.warning("Timeout getting IP info")
        except Exception as e:
            logger.error(f"Error getting IP info: {e}")

        return None

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def wait_for_status(self, target_status: str, timeout: int = 15) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            if target_status == "connected" and self.is_connected():
                self._invalidate_status_cache()
                return True
            elif target_status == "disconnected" and not self.is_connected():
                self._invalidate_status_cache()
                return True
            time.sleep(2)
        return False

    def rotate_ip_simple(self) -> bool:
        """Rotate IP by reconnecting"""
        logger.info("Rotating IP (disconnect + reconnect)...")
        self.disconnect()
        self.wait_for_status("disconnected", timeout=5)
        time.sleep(2)
        if self.connect():
            return self.wait_for_status("connected", timeout=15)
        return False

    def set_custom_endpoint(self, endpoint: str) -> bool:
        """Set custom endpoint in config.json and restart"""
        try:
            if not os.path.exists(self.config_path):
                logger.error("Config file not found")
                return False

            with open(self.config_path, "r") as f:
                config = json.load(f)

            if not endpoint:
                logger.info("Resetting custom endpoint (usque)...")
                config.pop("endpoint_v4", None)
            else:
                logger.info(f"Setting custom endpoint to {endpoint} (usque)...")
                config["endpoint_v4"] = endpoint

            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=2)

            logger.info(f"Updated usque endpoint to: {endpoint}")
            self.disconnect()
            time.sleep(5)
            return self.connect()
        except Exception as e:
            logger.error(f"Failed to set custom endpoint: {e}")
            return False

    # ------------------------------------------------------------------
    # Geo helpers
    # ------------------------------------------------------------------

    def _get_city_from_colo(self, colo: str) -> str:
        city_map = {
            "LAX": "Los Angeles", "SJC": "San Jose", "ORD": "Chicago",
            "IAD": "Ashburn", "EWR": "Newark", "MIA": "Miami",
            "DFW": "Dallas", "SEA": "Seattle", "ATL": "Atlanta",
            "LHR": "London", "CDG": "Paris", "FRA": "Frankfurt",
            "AMS": "Amsterdam", "SIN": "Singapore", "HKG": "Hong Kong",
            "NRT": "Tokyo", "SYD": "Sydney", "ICN": "Seoul",
            "BOM": "Mumbai", "GRU": "São Paulo", "YVR": "Vancouver",
            "YYZ": "Toronto", "MEL": "Melbourne", "DXB": "Dubai",
        }
        return city_map.get(colo.upper(), colo)

    def _get_country_name(self, loc_code: str) -> str:
        country_map = {
            "US": "United States", "CN": "China", "JP": "Japan",
            "GB": "United Kingdom", "DE": "Germany", "FR": "France",
            "CA": "Canada", "AU": "Australia", "SG": "Singapore",
            "IN": "India", "BR": "Brazil", "KR": "South Korea",
            "NL": "Netherlands", "SE": "Sweden", "IT": "Italy",
            "ES": "Spain", "RU": "Russia", "HK": "Hong Kong",
            "TW": "Taiwan", "MX": "Mexico", "AR": "Argentina",
        }
        return country_map.get(loc_code.upper(), loc_code)
