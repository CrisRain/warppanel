import asyncio
import logging
import shutil
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

import os

class LinuxTunManager:
    """
    Helper class for managing Linux TUN/TAP routing and firewall rules.
    Designed for platform-exclusive operations on Linux.
    """

    def __init__(self):
        self.check_platform()

    def check_platform(self):
        import platform
        if platform.system() != "Linux":
            logger.warning("LinuxTunManager instantiated on non-Linux platform. Operations will fail or be ignored.")

    @staticmethod
    async def _run_command(command: str) -> Tuple[int, str, str]:
        """Helper to run async shell commands"""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            return process.returncode, stdout.decode().strip(), stderr.decode().strip()
        except Exception as e:
            logger.error(f"Error running command '{command}': {e}")
            return -1, "", str(e)

    @staticmethod
    def is_docker() -> bool:
        """Check if running inside a Docker container."""
        # Check .dockerenv file
        if os.path.exists('/.dockerenv'):
            return True
        
        # Check cgroup
        path = '/proc/self/cgroup'
        try:
            if os.path.isfile(path):
                with open(path, 'r') as f:
                    for line in f:
                        if 'docker' in line:
                            return True
        except Exception:
            pass
            
        return False

    @classmethod
    async def get_default_route(cls) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get original default gateway, interface, and primary IP.
        Returns: (gateway, interface, ip_address)
        """
        gw, iface, ip = None, None, None
        try:
            # Get default route
            rc, stdout, _ = await cls._run_command("ip route show default")
            # Example output: "default via 172.18.0.1 dev eth0"
            lines = stdout.split('\n')
            if lines:
                parts = lines[0].split()
                if 'via' in parts and 'dev' in parts:
                    gw = parts[parts.index('via') + 1]
                    iface = parts[parts.index('dev') + 1]
        except Exception as e:
            logger.warning(f"Could not get default route: {e}")
            return None, None, None

        # Get IP address for the interface
        if iface:
            try:
                rc, stdout, _ = await cls._run_command(f"ip -4 -o addr show dev {iface}")
                for line in stdout.split('\n'):
                    if 'inet ' in line:
                        # Format: "N: eth0  inet 172.18.0.2/16 ..."
                        # Split by whitespace, find 'inet', next is IP/CIDR
                        parts = line.split()
                        if 'inet' in parts:
                            ip_cidr = parts[parts.index('inet') + 1]
                            ip = ip_cidr.split('/')[0]
                            break
            except Exception:
                pass

        if gw and iface:
            logger.info(f"Detected default route: via {gw} dev {iface}, IP {ip}")
        return gw, iface, ip

    @classmethod
    async def setup_bypass_routing(cls, gw: str, iface: str, ip: str, table_id: int = 100):
        """
        Set up policy routing to ensure traffic from the specific IP 
        uses the original gateway (bypassing the VPN/TUN).
        """
        if not gw or not iface or not ip:
            logger.warning("Missing routing info, skipping bypass routing setup.")
            return

        try:
            logger.info(f"Setting up bypass routing: from {ip} -> table {table_id} via {gw} dev {iface}")
            
            # 1. Add default route to custom table
            await cls._run_command(f"ip route add default via {gw} dev {iface} table {table_id}")
            
            # 2. Copy link-scope routes to custom table (for ARP/local reachability)
            rc, stdout, _ = await cls._run_command(f"ip route show dev {iface} scope link")
            for line in stdout.split('\n'):
                subnet = line.split()[0] if line.strip() else None
                if subnet:
                    await cls._run_command(f"ip route add {subnet} dev {iface} table {table_id}")

            # 3. Add IP rule to use custom table
            # Clean up old rule first just in case
            await cls._run_command(f"ip rule del from {ip} lookup {table_id} 2>/dev/null")
            await cls._run_command(f"ip rule add from {ip} lookup {table_id}")
            
        except Exception as e:
            logger.error(f"Failed to setup bypass routing: {e}")

    @classmethod
    async def cleanup_bypass_routing(cls, ip: Optional[str], table_id: int = 100):
        """
        Remove the bypass routing rules and flush the custom table.
        """
        try:
            # Remove ip rule
            if ip:
                await cls._run_command(f"ip rule del from {ip} lookup {table_id} 2>/dev/null")
            else:
                pass

            # Flush table
            await cls._run_command(f"ip route flush table {table_id} 2>/dev/null")
            logger.info(f"Bypass routing (table {table_id}) cleaned up.")
        except Exception as e:
            logger.error(f"Error cleaning up bypass routing: {e}")

    @classmethod
    async def add_static_route(cls, target: str, gateway: str, interface: str):
        """Add a specific static route via a gateway."""
        try:
            logger.info(f"Adding static route: {target} via {gateway}")
            await cls._run_command(f"ip route add {target} via {gateway} dev {interface}")
        except Exception as e:
            logger.error(f"Failed to add static route: {e}")

    @classmethod
    async def delete_static_route(cls, target: str):
        """Delete a specific static route."""
        try:
            await cls._run_command(f"ip route del {target} 2>/dev/null")
        except Exception as e:
            logger.error(f"Failed to delete static route: {e}")

    @classmethod
    async def set_default_interface(cls, interface: str):
        """Replace the default system route to go through a specific interface."""
        try:
            logger.info(f"Replacing default route with dev {interface}")
            await cls._run_command(f"ip route replace default dev {interface}")
        except Exception as e:
            logger.error(f"Failed to set default interface: {e}")

    @classmethod
    async def tun_interface_exists(cls, pattern: str = "tun") -> bool:
        """Check if any interface matching the pattern exists."""
        try:
            rc, stdout, _ = await cls._run_command("ip link show")
            # Simplified check
            return any(pattern in line for line in stdout.split('\n'))
        except Exception:
            return False

    @classmethod
    async def get_tun_interface_name(cls, prefix: str = "tun") -> Optional[str]:
        """Get the name of the first interface starting with prefix."""
        try:
            rc, stdout, _ = await cls._run_command("ip -o link show")
            for line in stdout.split('\n'):
                # Format: "N: name: ..."
                parts = line.split(':')
                if len(parts) >= 2:
                    name = parts[1].strip()
                    if name.startswith(prefix):
                        return name
        except Exception:
            pass
        return None

    @classmethod
    async def apply_nftables_allow_rules(cls, interface: str, ports: list[int]):
        """
        Add nftables rules to allow traffic on specific ports for the given interface.
        Used when Cloudflare WARP enables its firewall (cloudflare-warp table).
        
        All rules are tagged with unique comments for identification and cleanup:
        - Output rule: "warppool-controller-output"
        - TCP input rules: "warppool-controller-tcp-{port}"
        - UDP input rules: "warppool-controller-udp-{port}"
        """
        if not shutil.which("nft"):
            logger.warning("nft command not found, skipping nftables configuration")
            return

        logger.info(f"Waiting for WARP nftables table...")
        # Wait for table
        table_ready = False
        for _ in range(10):
            rc, _, _ = await cls._run_command("nft list table inet cloudflare-warp 2>/dev/null")
            if rc == 0:
                table_ready = True
                break
            await asyncio.sleep(0.5)
        
        if not table_ready:
            logger.warning("WARP nftables table not found.")
            return

        logger.info(f"Adding allow rules for {interface} on ports {ports}")
        try:
            # Clean up any existing warppool-controller rules first (idempotency)
            await cls.cleanup_nftables_rules(interface, ports)
            
            # Allow Output (add to end of chain with comment)
            rc, stdout, stderr = await cls._run_command(
                f'nft add rule inet cloudflare-warp output oif "{interface}" accept comment "warppool-controller-output"'
            )
            if rc != 0:
                logger.error(f"Failed to add nftables output rule: {stderr}")
                raise RuntimeError(f"nftables output rule failed: {stderr}")
            logger.info(f"Added nftables output rule for {interface}")
            
            # Allow Input on specific ports (both TCP and UDP with unique comments)
            for port in ports:
                # TCP rule
                rc, stdout, stderr = await cls._run_command(
                    f'nft add rule inet cloudflare-warp input iif "{interface}" tcp dport {port} accept comment "warppool-controller-tcp-{port}"'
                )
                if rc != 0:
                    logger.error(f"Failed to add nftables TCP input rule for port {port}: {stderr}")
                    raise RuntimeError(f"nftables TCP input rule failed for port {port}: {stderr}")
                logger.info(f"Added nftables TCP input rule for {interface}:{port}")
                
                # UDP rule
                rc, stdout, stderr = await cls._run_command(
                    f'nft add rule inet cloudflare-warp input iif "{interface}" udp dport {port} accept comment "warppool-controller-udp-{port}"'
                )
                if rc != 0:
                    logger.error(f"Failed to add nftables UDP input rule for port {port}: {stderr}")
                    raise RuntimeError(f"nftables UDP input rule failed for port {port}: {stderr}")
                logger.info(f"Added nftables UDP input rule for {interface}:{port}")
                
        except Exception as e:
            logger.error(f"Failed to apply nftables rules: {e}")
            raise

    @classmethod
    async def cleanup_nftables_rules(cls, interface: str, ports: list[int]):
        """
        Remove nftables rules for the specified interface and ports.
        Used during cleanup when disconnecting from TUN mode.
        
        This method uses rule handles for precise deletion to avoid accidentally
        removing unrelated rules. It searches for rules with warppool-controller
        comments and deletes them by handle number.
        """
        import re
        
        if not shutil.which("nft"):
            logger.warning("nft command not found, skipping nftables cleanup")
            return

        logger.info(f"Cleaning up nftables rules for {interface} on ports {ports}")
        
        # Check if table exists
        rc, _, _ = await cls._run_command("nft list table inet cloudflare-warp 2>/dev/null")
        if rc != 0:
            logger.info("WARP nftables table not found, skipping cleanup")
            return
        
        try:
            # Clean up output chain rules with warppool-controller-output comment
            rc, stdout, _ = await cls._run_command("nft -a list chain inet cloudflare-warp output 2>/dev/null")
            if rc == 0:
                # Match rules with "warppool-controller-output" comment and extract handle
                # Pattern matches: comment "warppool-controller-output" ... # handle <number>
                pattern = r'comment "warppool-controller-output".*?# handle (\d+)'
                handles = re.findall(pattern, stdout)
                for handle in handles:
                    rc, _, _ = await cls._run_command(
                        f"nft delete rule inet cloudflare-warp output handle {handle} 2>/dev/null"
                    )
                    if rc == 0:
                        logger.info(f"Removed nftables output rule (handle {handle})")
            
            # Clean up input chain rules with warppool-controller-tcp/udp-{port} comments
            rc, stdout, _ = await cls._run_command("nft -a list chain inet cloudflare-warp input 2>/dev/null")
            if rc == 0:
                for port in ports:
                    # TCP rules
                    tcp_pattern = rf'comment "warppool-controller-tcp-{port}".*?# handle (\d+)'
                    tcp_handles = re.findall(tcp_pattern, stdout)
                    for handle in tcp_handles:
                        rc, _, _ = await cls._run_command(
                            f"nft delete rule inet cloudflare-warp input handle {handle} 2>/dev/null"
                        )
                        if rc == 0:
                            logger.info(f"Removed nftables TCP input rule for port {port} (handle {handle})")
                    
                    # UDP rules
                    udp_pattern = rf'comment "warppool-controller-udp-{port}".*?# handle (\d+)'
                    udp_handles = re.findall(udp_pattern, stdout)
                    for handle in udp_handles:
                        rc, _, _ = await cls._run_command(
                            f"nft delete rule inet cloudflare-warp input handle {handle} 2>/dev/null"
                        )
                        if rc == 0:
                            logger.info(f"Removed nftables UDP input rule for port {port} (handle {handle})")
            
            logger.info("nftables rules cleanup complete")
        except Exception as e:
            logger.error(f"Error during nftables cleanup: {e}")

