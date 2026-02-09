# controller-app/app/official_controller.py
"""
OfficialController - WARP backend implementation using official Cloudflare client
Supports proxy mode and TUN mode with MASQUE / WireGuard protocols
"""
import subprocess
import logging
import os
import time
import threading
import json
from typing import Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OfficialController:
    """Control official Cloudflare WARP client (proxy + TUN modes)"""

    # Class-level status cache
    _status_cache = None
    _status_cache_time = 0
    _STATUS_CACHE_TTL = 8  # seconds

    def __init__(self, socks5_port: int = 1080, http_port: int = 8080):
        self.socks5_port = socks5_port
        self.http_port = http_port
        self.mute_backend_logs = False
        self.preferred_protocol = "masque"  # 'masque' or 'wireguard' (wireguard only in TUN)
        self._mode = os.getenv("WARP_MODE", "proxy")  # 'proxy' or 'tun'
        self._cached_ip_info = None
        self._cache_time: float = 0
        self._cache_ttl: float = 120
        # TUN routing state
        self._saved_gateway = None
        self._saved_interface = None
        self._saved_ip = None

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> bool:
        """Switch between proxy and tun mode."""
        if mode not in ("proxy", "tun"):
            logger.error(f"Invalid mode: {mode}")
            return False
        if mode == self._mode:
            logger.info(f"Already in {mode} mode")
            return True

        previous_mode = self._mode
        logger.info(f"Switching official mode from {previous_mode} to {mode}")

        # WireGuard only valid in TUN mode
        if mode == "proxy" and self.preferred_protocol == "wireguard":
            logger.info("Resetting protocol to MASQUE (WireGuard only in TUN mode)")
            self.preferred_protocol = "masque"

        # Disconnect and clean up resources from previous mode
        self.disconnect()
        
        # Extra cleanup when switching FROM TUN mode
        if previous_mode == "tun":
            logger.info("Cleaning up TUN mode resources...")
            self._cleanup_tun_routing()
            time.sleep(1)
        
        time.sleep(2)
        self._mode = mode
        os.environ["WARP_MODE"] = mode
        self._invalidate_status_cache()
        logger.info(f"Mode switched to {mode}, ready to connect")
        return True

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _stream_logs(self, process, name):
        try:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                if not self.mute_backend_logs:
                    logger.debug(f"[{name}] {line.strip()}")
        except Exception:
            pass

    def execute_command(self, command: str):
        """Execute warp-cli command"""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                logger.error(f"Command '{command}' failed: {result.stderr.strip()}")
                return None
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"Error executing '{command}': {e}")
            return None

    def _is_port_open(self, port: int) -> bool:
        try:
            result = subprocess.run(
                ["ss", "-lnt", f"sport = :{port}"],
                capture_output=True, text=True,
            )
            return f":{port}" in result.stdout
        except Exception:
            return False

    def _is_daemon_responsive(self) -> bool:
        """Check if warp-svc is running AND responsive"""
        try:
            res = subprocess.run(
                ["supervisorctl", "status", "warp-svc"],
                capture_output=True, text=True,
            )
            if res.returncode != 0 or "RUNNING" not in res.stdout:
                return False
            result = subprocess.run(
                "warp-cli --accept-tos status",
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=2,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _check_daemon_running(self) -> bool:
        return self._is_daemon_responsive()

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect to WARP in current mode"""
        if self._mode == "tun":
            return self._connect_tun()
        return self._connect_proxy()

    def _connect_proxy(self) -> bool:
        """Connect in proxy mode"""
        if not self._is_daemon_responsive():
            logger.info("Daemon not ready, restarting services...")
            self._stop_services()
            if not self._start_services_proxy():
                logger.error("Failed to start official WARP services (proxy)")
                return False

        self._ensure_socat()

        logger.info("Connecting WARP (official, proxy mode)...")
        self.execute_command("warp-cli --accept-tos mode proxy")
        self.execute_command("warp-cli --accept-tos proxy port 40001")
        self.execute_command("warp-cli --accept-tos tunnel protocol set MASQUE")
        self.execute_command("warp-cli --accept-tos connect")

        time.sleep(2)

        if self.wait_for_status("connected", timeout=600):
            self.mute_backend_logs = True
            self._invalidate_status_cache()
            logger.info("Official WARP proxy connection successful")
            self._start_http_proxy()
            return True

        logger.error("Official WARP proxy connection failed")
        return False

    def _connect_tun(self) -> bool:
        """Connect in TUN mode (full tunnel via virtual interface)"""
        if not self._is_daemon_responsive():
            logger.info("Daemon not ready, restarting services...")
            self._stop_services()
            if not self._start_services_tun():
                logger.error("Failed to start official WARP services (TUN)")
                return False

        # Save original route BEFORE warp-cli connect modifies routing
        self._save_original_route()

        logger.info("Connecting WARP (official, TUN mode)...")
        self.execute_command("warp-cli --accept-tos mode warp")

        # Set tunnel protocol (WireGuard or MASQUE)
        proto_name = "WireGuard" if self.preferred_protocol == "wireguard" else "MASQUE"
        self.execute_command(f"warp-cli --accept-tos tunnel protocol set {proto_name}")

        self.execute_command("warp-cli --accept-tos connect")

        time.sleep(2)

        if self.wait_for_status("connected", timeout=600):
            self.mute_backend_logs = True
            self._invalidate_status_cache()
            logger.info("Official WARP TUN connection successful")
            
            # Give WARP a moment to fully initialize nftables rules
            time.sleep(2)
            
            # Apply policy routing so panel/proxy response traffic bypasses WARP TUN
            self._apply_tun_routing()
            self._start_tun_proxy()
            return True

        logger.error("Official WARP TUN connection failed")
        return False

    def disconnect(self) -> bool:
        """Disconnect from WARP and stop services"""
        logger.info(f"Disconnecting WARP (official, {self._mode} mode)...")
        self._cached_ip_info = None
        self._invalidate_status_cache()

        # Clean up TUN routing before disconnecting
        if self._mode == "tun":
            logger.info("Cleaning up TUN routing and firewall rules...")
            self._cleanup_tun_routing()

        try:
            self.execute_command("warp-cli --accept-tos disconnect")
            self.wait_for_status("disconnected", timeout=5)
        except Exception:
            pass

        self._stop_services()
        logger.info("WARP disconnected successfully")
        return True

    # ------------------------------------------------------------------
    # Service management
    # ------------------------------------------------------------------

    def _start_services_proxy(self) -> bool:
        """Start services for proxy mode"""
        try:
            logger.info("Starting background services (proxy mode)...")
            self.mute_backend_logs = False

            try:
                subprocess.run(["supervisorctl", "start", "warp-svc"], check=True)
            except subprocess.CalledProcessError:
                logger.error("Failed to start warp-svc")
                return False

            time.sleep(3)
            self._ensure_socat()

            for _ in range(30):
                if self._is_daemon_responsive():
                    logger.info("warp-svc is ready")
                    return self._configure_warp_proxy()
                time.sleep(1)

            logger.error("Timed out waiting for warp-svc")
            return False
        except Exception as e:
            logger.error(f"Error starting proxy services: {e}")
            return False

    def _start_services_tun(self) -> bool:
        """Start services for TUN mode"""
        try:
            logger.info("Starting background services (TUN mode)...")
            self.mute_backend_logs = False

            try:
                subprocess.run(["supervisorctl", "start", "warp-svc"], check=True)
            except subprocess.CalledProcessError:
                logger.error("Failed to start warp-svc")
                return False

            time.sleep(3)

            for _ in range(30):
                if self._is_daemon_responsive():
                    logger.info("warp-svc is ready")
                    return self._configure_warp_tun()
                time.sleep(1)

            logger.error("Timed out waiting for warp-svc")
            return False
        except Exception as e:
            logger.error(f"Error starting TUN services: {e}")
            return False

    def _configure_warp_proxy(self) -> bool:
        """Apply WARP configuration for proxy mode"""
        try:
            if not os.path.exists("/var/lib/cloudflare-warp/reg.json"):
                logger.info("Registering new WARP account...")
                self.execute_command("warp-cli --accept-tos registration delete")
                self.execute_command("warp-cli --accept-tos registration new")

            self.execute_command("warp-cli --accept-tos tunnel protocol set MASQUE")
            self.execute_command("warp-cli --accept-tos mode proxy")
            self.execute_command("warp-cli --accept-tos proxy port 40001")
            return True
        except Exception as e:
            logger.error(f"Error configuring WARP proxy: {e}")
            return False

    def _configure_warp_tun(self) -> bool:
        """Apply WARP configuration for TUN mode"""
        try:
            if not os.path.exists("/var/lib/cloudflare-warp/reg.json"):
                logger.info("Registering new WARP account...")
                self.execute_command("warp-cli --accept-tos registration delete")
                self.execute_command("warp-cli --accept-tos registration new")

            proto_name = "WireGuard" if self.preferred_protocol == "wireguard" else "MASQUE"
            self.execute_command(f"warp-cli --accept-tos tunnel protocol set {proto_name}")
            self.execute_command("warp-cli --accept-tos mode warp")
            return True
        except Exception as e:
            logger.error(f"Error configuring WARP TUN: {e}")
            return False

    def _stop_services(self):
        """Stop all possible services (safe for both modes)"""
        logger.info("Stopping official services...")
        try:
            subprocess.run(["supervisorctl", "stop", "tun-proxy"], check=False)
            subprocess.run(["supervisorctl", "stop", "http-proxy"], check=False)
            subprocess.run(["supervisorctl", "stop", "socat"], check=False)
            subprocess.run(["supervisorctl", "stop", "warp-svc"], check=False)
        except Exception as e:
            logger.error(f"Error stopping services: {e}")

    # ------------------------------------------------------------------
    # Auxiliary proxy helpers
    # ------------------------------------------------------------------

    def _ensure_socat(self):
        """Ensure socat service is running (proxy mode only)"""
        if self._mode != "proxy":
            return

        sys_active = False
        try:
            res = subprocess.run(
                ["supervisorctl", "status", "socat"],
                capture_output=True, text=True,
            )
            sys_active = res.returncode == 0 and "RUNNING" in res.stdout
        except Exception:
            pass

        port_open = self._is_port_open(self.socks5_port)

        if sys_active and port_open:
            return

        logger.info("Starting socat service...")
        try:
            subprocess.run(["supervisorctl", "start", "socat"], check=True)
            time.sleep(1)
            if not self._is_port_open(self.socks5_port):
                logger.warning(f"Socat started but port {self.socks5_port} not listening yet")
                time.sleep(2)
        except Exception as e:
            logger.error(f"Error starting socat: {e}")

    def _start_http_proxy(self):
        """Start HTTP proxy for proxy mode (chains through SOCKS5)"""
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

    def _start_tun_proxy(self):
        """Start SOCKS5 + HTTP proxy for TUN mode"""
        try:
            res = subprocess.run(
                ["supervisorctl", "status", "tun-proxy"],
                capture_output=True, text=True,
            )
            if "RUNNING" in res.stdout:
                return
            logger.info("Starting TUN proxy (SOCKS5 + HTTP)...")
            subprocess.run(["supervisorctl", "start", "tun-proxy"], check=False)
            for _ in range(10):
                if self._is_port_open(self.socks5_port):
                    break
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Failed to start TUN proxy: {e}")

    # ------------------------------------------------------------------
    # TUN routing helpers
    # ------------------------------------------------------------------

    def _save_original_route(self):
        """Save original default gateway, interface and container IP."""
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=5,
            )
            line = result.stdout.strip().split('\n')[0]
            parts = line.split()
            if 'via' in parts and 'dev' in parts:
                self._saved_gateway = parts[parts.index('via') + 1]
                self._saved_interface = parts[parts.index('dev') + 1]
        except Exception as e:
            logger.warning(f"Could not get default route: {e}")
            return

        # Get primary IP on the interface
        if self._saved_interface:
            try:
                result = subprocess.run(
                    ["ip", "-4", "-o", "addr", "show", "dev", self._saved_interface],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.strip().split('\n'):
                    if 'inet ' in line:
                        self._saved_ip = line.split('inet ')[1].split('/')[0]
                        break
            except Exception:
                pass

        logger.info(
            f"Saved original route: via {self._saved_gateway} dev {self._saved_interface}, IP {self._saved_ip}"
        )

    def _apply_tun_routing(self):
        """Apply policy-based routing so panel/proxy response traffic bypasses WARP TUN.

        Strategy:
        1. Create routing table 100 with original default gateway
        2. Add ip rule: traffic from container's own IP uses table 100
           (ensures panel/proxy response traffic goes back via Docker bridge)
        """
        gw = self._saved_gateway
        iface = self._saved_interface
        ip = self._saved_ip

        if not gw or not iface or not ip:
            logger.warning("Missing original route info, skipping TUN routing fix (panel may be inaccessible)")
            return

        try:
            logger.info(f"Applying TUN policy route: from {ip} → table 100 via {gw} dev {iface}")

            # 1. Create routing table 100 with original default gateway
            subprocess.run(
                f"ip route add default via {gw} dev {iface} table 100",
                shell=True, check=False,
            )
            # Copy connected-subnet routes so ARP works in table 100
            res = subprocess.run(
                f"ip route show dev {iface} scope link",
                capture_output=True, text=True, shell=True,
            )
            for line in res.stdout.strip().split('\n'):
                subnet = line.split()[0] if line.strip() else None
                if subnet:
                    subprocess.run(
                        f"ip route add {subnet} dev {iface} table 100",
                        shell=True, check=False,
                    )

            # Add ip rule so traffic from our IP uses table 100 (bypassing WARP)
            subprocess.run(
                f"ip rule add from {ip} lookup 100",
                shell=True, check=False,
            )

            # 3. Add nftables rules to allow traffic on eth0
            # WARP's nftables firewall (cloudflare-warp table) has default DROP policy
            # We need to explicitly allow eth0 traffic for panel/proxy access
            # Wait for WARP to create its nftables table (may take a moment after connect)
            logger.info(f"Waiting for WARP nftables table to be ready...")
            nft_table_ready = False
            for _ in range(10):  # Wait up to 5 seconds
                result = subprocess.run(
                    "nft list table inet cloudflare-warp 2>/dev/null",
                    shell=True, capture_output=True, text=True,
                )
                if result.returncode == 0 and "cloudflare-warp" in result.stdout:
                    nft_table_ready = True
                    break
                time.sleep(0.5)
            
            if not nft_table_ready:
                logger.warning("WARP nftables table not found, firewall rules may not be applied")
            else:
                logger.info(f"Adding nftables rules for {iface} interface...")
                # Add rules with retry to ensure they're inserted
                for attempt in range(3):
                    subprocess.run(
                        f"nft insert rule inet cloudflare-warp input iif \"{iface}\" tcp dport 8000 accept 2>/dev/null",
                        shell=True, check=False,
                    )
                    subprocess.run(
                        f"nft insert rule inet cloudflare-warp input iif \"{iface}\" tcp dport 1080 accept 2>/dev/null",
                        shell=True, check=False,
                    )
                    subprocess.run(
                        f"nft insert rule inet cloudflare-warp input iif \"{iface}\" tcp dport 8080 accept 2>/dev/null",
                        shell=True, check=False,
                    )
                    subprocess.run(
                        f"nft insert rule inet cloudflare-warp output oif \"{iface}\" accept 2>/dev/null",
                        shell=True, check=False,
                    )
                    
                    # Verify rules were added
                    verify = subprocess.run(
                        f"nft list chain inet cloudflare-warp input 2>/dev/null | grep -q 'iif \"{iface}\"'",
                        shell=True,
                    )
                    if verify.returncode == 0:
                        logger.info(f"nftables rules successfully added for {iface}")
                        break
                    else:
                        logger.warning(f"nftables rules not found, retrying... (attempt {attempt + 1}/3)")
                        time.sleep(1)

            logger.info(f"TUN policy route applied: from {ip} via {gw} dev {iface}")
        except Exception as e:
            logger.error(f"Failed to apply TUN routing: {e}")

    def _cleanup_tun_routing(self):
        """Remove policy routing rules, table 100, iptables connmark, and nftables rules."""
        iface = self._saved_interface or "eth0"
        ip = self._saved_ip
        
        try:
            # Remove ip rule for container IP (fallback rules)
            result = subprocess.run(
                "ip rule show", shell=True,
                capture_output=True, text=True,
            )
            for line in result.stdout.strip().split('\n'):
                if 'lookup 100' in line:
                    parts = line.split()
                    if 'from' in parts:
                        rule_ip = parts[parts.index('from') + 1]
                        subprocess.run(f"ip rule del from {rule_ip} lookup 100", shell=True, check=False)

            # Flush table 100
            subprocess.run("ip route flush table 100 2>/dev/null", shell=True, check=False)
            
            # Note: nftables rules will be re-added on next connect anyway
            logger.info("TUN routing cleanup complete")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Connectivity checks
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Check if WARP is connected"""
        if not self._check_daemon_running():
            return False
        try:
            result = subprocess.run(
                "warp-cli --accept-tos status",
                shell=True, capture_output=True, text=True, timeout=3,
            )
            if result.returncode != 0:
                return False
            output = result.stdout.lower()
            return "connected" in output and "disconnected" not in output
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Status / IP Info
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        now = time.time()
        if (
            OfficialController._status_cache is not None
            and now - OfficialController._status_cache_time < OfficialController._STATUS_CACHE_TTL
        ):
            return OfficialController._status_cache

        status = self._get_status_uncached()
        OfficialController._status_cache = status
        OfficialController._status_cache_time = now
        return status

    def _invalidate_status_cache(self):
        OfficialController._status_cache = None
        OfficialController._status_cache_time = 0

    def _get_status_uncached(self) -> Dict:
        base_status = {
            "backend": "official",
            "status": "disconnected",
            "ip": "Unknown",
            "location": "Unknown",
            "city": "Unknown",
            "country": "Unknown",
            "isp": "Cloudflare WARP",
            "warp_protocol": self.preferred_protocol.upper(),
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

    def _fetch_ip_info(self) -> dict:
        """Fetch IP info. Proxy mode: via SOCKS5. TUN mode: direct."""
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
        logger.info("Rotating IP (official: disconnect + reconnect)...")
        self.disconnect()
        time.sleep(2)
        if self.connect():
            return self.wait_for_status("connected", timeout=15)
        return False

    def set_custom_endpoint(self, endpoint: str) -> bool:
        try:
            if not endpoint:
                logger.info("Resetting custom endpoint (official)...")
                cmd = "warp-cli --accept-tos tunnel endpoint reset"
            else:
                logger.info(f"Setting custom endpoint to {endpoint} (official)...")
                cmd = f"warp-cli --accept-tos tunnel endpoint set {endpoint}"

            self.execute_command(cmd)

            try:
                self.execute_command("warp-cli --accept-tos disconnect")
                self.wait_for_status("disconnected", timeout=5)
            except Exception:
                pass
            time.sleep(10)
            return self.connect()
        except Exception as e:
            logger.error(f"Failed to set custom endpoint: {e}")
            return False

    def set_protocol(self, protocol: str) -> bool:
        """Set WARP tunnel protocol. WireGuard only available in TUN mode."""
        protocol = (protocol or "masque").lower()

        if protocol not in ("masque", "wireguard"):
            logger.error(f"Invalid protocol: {protocol}. Use 'masque' or 'wireguard'")
            return False

        if protocol == "wireguard" and self._mode != "tun":
            logger.error("WireGuard is only available in TUN mode")
            return False

        if self.preferred_protocol == protocol:
            logger.info(f"Protocol already set to {protocol}")
            return True

        self.preferred_protocol = protocol
        self._invalidate_status_cache()
        self.mute_backend_logs = False

        try:
            logger.info(f"Switching protocol to {protocol.upper()}...")

            try:
                self.execute_command("warp-cli --accept-tos disconnect")
                self.wait_for_status("disconnected", timeout=5)
            except Exception:
                pass

            proto_name = "WireGuard" if protocol == "wireguard" else "MASQUE"
            cmd = f"warp-cli --accept-tos tunnel protocol set {proto_name}"
            res = self.execute_command(cmd)
            if res is None:
                logger.error("Failed to update tunnel protocol")
                return False

            self._stop_services()
            time.sleep(2)

            return self.connect()
        except Exception as e:
            logger.error(f"Failed to set protocol: {e}")
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
            "BOM": "Mumbai", "GRU": "São Paulo",
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
            "TW": "Taiwan",
        }
        return country_map.get(loc_code.upper(), loc_code)
