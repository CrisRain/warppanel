import asyncio
import logging
import json
import os
from abc import ABC, abstractmethod
from typing import Dict, Optional, Union, List

logger = logging.getLogger(__name__)

class WarpBackendController(ABC):
    """
    Abstract base class for WARP backend controllers.
    Implements common functionality for process management, network checks, and status retrieval.
    """
    
    _status_cache: Optional[Dict] = None
    _status_cache_time: float = 0
    _STATUS_CACHE_TTL: float = 2.0

    def __init__(self, socks5_port: int = 1080):
        self.socks5_port = socks5_port
        self._cached_ip_info: Optional[Dict] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 120  # Cache IP info for 120 seconds

    @property
    @abstractmethod
    def mode(self) -> str:
        """Return current operation mode (e.g. 'proxy', 'tun')"""
        pass

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection"""
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """Terminate connection"""
        pass
    
    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if backend is connected"""
        pass

    async def _run_command(self, command: Union[str, List[str]], timeout=None):
        """Run a shell command or executable"""
        try:
            if isinstance(command, list):
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return process.returncode, stdout.decode().strip(), stderr.decode().strip()
        except asyncio.TimeoutError:
            logger.error(f"Command '{command}' timed out")
            return -1, "", "Timeout"
        except Exception as e:
            logger.error(f"Error executing '{command}': {e}")
            return -1, "", str(e)

    async def _is_port_open(self, port: int) -> bool:
        """Check if a local port is listening using 'ss'"""
        try:
            rc, stdout, _ = await self._run_command(f"ss -lnt sport = :{port}")
            return f":{port}" in stdout
        except Exception:
            return False

    async def get_status(self) -> Dict:
        """Get connection status and IP information (with short-term caching)"""
        now = asyncio.get_running_loop().time()
        if (
            self._status_cache is not None
            and now - self._status_cache_time < self._STATUS_CACHE_TTL
        ):
            return self._status_cache

        status = await self._get_status_uncached()
        self._status_cache = status
        self._status_cache_time = now
        return status

    def _invalidate_status_cache(self):
        self._status_cache = None
        self._status_cache_time = 0

    async def _get_status_uncached(self) -> Dict:
        """
        Construct status dictionary. 
        Subclasses can override, but this provides a solid default structure.
        """
        connected = await self.is_connected()
        
        base_status = {
            "backend": self.__class__.__name__.replace("Controller", "").lower(), # efficient enough
            "status": "connected" if connected else "disconnected",
            "ip": "Unknown",
            "location": "Unknown",
            "city": "Unknown",
            "country": "Unknown",
            "isp": "Cloudflare WARP",
            "warp_protocol": "MASQUE", # Default, override in subclass if dynamic
            "warp_mode": self.mode,
            "connection_time": "Unknown",
            "network_type": "Unknown",
            "proxy_address": f"socks5://127.0.0.1:{self.socks5_port}",
            "details": {},
        }

        if not connected:
            self._cached_ip_info = None
            return base_status

        now = asyncio.get_running_loop().time()
        if self._cached_ip_info and (now - self._cache_time) < self._cache_ttl:
            base_status.update(self._cached_ip_info)
            return base_status

        ip_info = await self._fetch_ip_info()
        if ip_info:
            self._cached_ip_info = ip_info
            self._cache_time = now
            base_status.update(ip_info)
        elif self._cached_ip_info:
            base_status.update(self._cached_ip_info)

        return base_status

    async def _fetch_ip_info(self) -> Optional[Dict]:
        """Fetch IP info via SOCKS5 proxy"""
        apis = [
            "http://ip-api.com/json/?fields=status,message,query,country,city,isp",
            "https://ipinfo.io/json",
            "https://ifconfig.me/all.json"
        ]
        
        for api_url in apis:
            try:
                cmd = ["curl", "-s", "--max-time", "5"]
                
                # Always use proxy for IP check to verify tunnel
                cmd.extend(["-x", f"socks5h://127.0.0.1:{self.socks5_port}"])
                cmd.append(api_url)
                
                # logger.debug(f"Fetching IP info from {api_url}...")
                rc, stdout, _ = await self._run_command(cmd, timeout=8)

                if rc == 0 and stdout:
                    try:
                        data = json.loads(stdout)
                        return self._parse_ip_data(data, api_url)
                    except json.JSONDecodeError:
                        continue
                        
            except Exception:
                pass
                
        return None

    def _parse_ip_data(self, data: Dict, api_url: str) -> Dict:
        """Normalize IP data from different APIs"""
        if "ip-api.com" in api_url:
            if data.get("status") == "success":
                isp = data.get("isp") or "Cloudflare WARP"
                return {
                    "ip": data.get("query") or "Unknown",
                    "country": data.get("country") or "Unknown",
                    "city": data.get("city") or "Unknown",
                    "location": data.get("country") or "Unknown",
                    "isp": isp,
                    "details": {"isp": isp},
                }
        elif "ipinfo.io" in api_url:
            return {
                "ip": data.get("ip") or "Unknown",
                "country": data.get("country") or "Unknown",
                "city": data.get("city") or "Unknown",
                "location": data.get("country") or "Unknown",
                "isp": data.get("org") or "Cloudflare WARP",
                "details": {"isp": data.get("org")},
            }
        elif "ifconfig.me" in api_url:
             return {
                "ip": data.get("ip_addr") or "Unknown",
                "country": "Unknown",
                "city": "Unknown",
                "location": "Unknown",
                "isp": "Cloudflare WARP",
                "details": {},
            }
        return {}

    async def wait_for_status(self, target_status: str, timeout: int = 15) -> bool:
        """Poll for status change"""
        start_time = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start_time < timeout:
            connected = await self.is_connected()
            if target_status == "connected" and connected:
                self._invalidate_status_cache()
                return True
            elif target_status == "disconnected" and not connected:
                self._invalidate_status_cache()
                return True
            await asyncio.sleep(1)
        return False

    async def rotate_ip_simple(self) -> bool:
        """Rotate IP by reconnecting (default implementation)"""
        logger.info(f"Rotating IP ({self.__class__.__name__}: disconnect + reconnect)...")
        await self.disconnect()
        await self.wait_for_status("disconnected", timeout=5)
        await asyncio.sleep(2)
        if await self.connect():
            return await self.wait_for_status("connected", timeout=15)
        return False
