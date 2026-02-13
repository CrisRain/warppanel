"""
Linux TUN interface, routing, and Split Tunneling manager for WarpPool.

Provides two sets of functionality:
- **Policy routing & static routes** — used by UsqueController (usque third-party
  client) which requires manual bypass routing through table 100.
- **Split Tunneling via warp-cli** — used by OfficialController (warp-cli official
  client) to manage the ``warp-cli tunnel ip`` exclude list so that certain CIDRs
  bypass the WARP tunnel without manual iptables / nftables rules.
"""
import asyncio
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_POLICY_TABLE = 100
_POLICY_PRIORITY = 100


class LinuxTunManager:
    """Manage Linux TUN interface routing, policy rules, and warp-cli Split Tunneling."""

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _exec(self, cmd: str) -> Tuple[int, str, str]:
        """Execute a shell command and return (returncode, stdout, stderr)."""
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
            return process.returncode, stdout.decode().strip(), stderr.decode().strip()
        except asyncio.TimeoutError:
            logger.error(f"Command timed out: {cmd}")
            return -1, "", "Timeout"
        except Exception as e:
            logger.error(f"Error executing '{cmd}': {e}")
            return -1, "", str(e)

    # ------------------------------------------------------------------
    # Docker detection (synchronous)
    # ------------------------------------------------------------------

    def is_docker(self) -> bool:
        """Return *True* if we are running inside a Docker container."""
        # Method 1: /.dockerenv sentinel file
        if os.path.exists("/.dockerenv"):
            return True

        # Method 2: cgroup inspection
        try:
            with open("/proc/1/cgroup", "r") as f:
                content = f.read()
            if "docker" in content or "container" in content:
                return True
        except Exception:
            pass

        return False

    # ------------------------------------------------------------------
    # Default route
    # ------------------------------------------------------------------

    async def get_default_route(self) -> Tuple[str, str, str]:
        """Parse ``ip route show default`` and return *(gateway, interface, source_ip)*.

        Falls back to empty strings when information is unavailable.
        """
        rc, stdout, stderr = await self._exec("ip route show default")
        if rc != 0:
            logger.error(f"Failed to get default route: {stderr}")
            return ("", "", "")

        gateway = ""
        interface = ""
        source_ip = ""

        # Typical output:
        #   default via 10.0.0.1 dev eth0 src 10.0.0.2
        #   default via 10.0.0.1 dev eth0 proto dhcp metric 100
        for line in stdout.splitlines():
            if not line.startswith("default"):
                continue
            parts = line.split()
            for i, token in enumerate(parts):
                if token == "via" and i + 1 < len(parts):
                    gateway = parts[i + 1]
                elif token == "dev" and i + 1 < len(parts):
                    interface = parts[i + 1]
                elif token == "src" and i + 1 < len(parts):
                    source_ip = parts[i + 1]
            break  # only process first default line

        # If src was not in default route line, obtain it from the interface
        if not source_ip and interface:
            rc2, out2, _ = await self._exec(
                f"ip -4 addr show dev {interface} | grep -oP 'inet \\K[0-9.]+'"
            )
            if rc2 == 0 and out2:
                source_ip = out2.splitlines()[0].strip()

        return (gateway, interface, source_ip)

    # ------------------------------------------------------------------
    # TUN interface detection
    # ------------------------------------------------------------------

    async def tun_interface_exists(self) -> bool:
        """Return *True* if any ``tun*`` network interface exists."""
        try:
            # Check /sys/class/net for tun* entries
            if os.path.isdir("/sys/class/net"):
                for name in os.listdir("/sys/class/net"):
                    if name.startswith("tun"):
                        return True

            # Fallback: ip link show
            rc, stdout, _ = await self._exec("ip link show")
            if rc == 0:
                for line in stdout.splitlines():
                    if "tun" in line:
                        return True
        except Exception as e:
            logger.error(f"Error checking TUN interface: {e}")

        return False

    async def get_tun_interface_name(self) -> Optional[str]:
        """Return the name of the first ``tun*`` interface, or *None*."""
        try:
            if os.path.isdir("/sys/class/net"):
                for name in sorted(os.listdir("/sys/class/net")):
                    if name.startswith("tun"):
                        return name

            # Fallback: ip link show
            rc, stdout, _ = await self._exec("ip link show")
            if rc == 0:
                for line in stdout.splitlines():
                    # Lines like: "4: tun0: <POINTOPOINT, ..."
                    if "tun" in line and ":" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            name = parts[1].strip().split("@")[0]
                            if name.startswith("tun"):
                                return name
        except Exception as e:
            logger.error(f"Error getting TUN interface name: {e}")

        return None

    # ------------------------------------------------------------------
    # Policy-based bypass routing  (table 100)
    # ------------------------------------------------------------------

    async def setup_bypass_routing(self, gw: str, iface: str, ip: str) -> None:
        """Create policy routing rules so that traffic originating from *ip*
        (panel / SOCKS5 response packets) bypasses the TUN and goes through
        the physical interface directly.

        * ``ip rule add from {ip} table 100 priority 100``
        * ``ip route add default via {gw} dev {iface} table 100``
        """
        if not gw or not iface or not ip:
            logger.warning("setup_bypass_routing: missing gw/iface/ip, skipping")
            return

        try:
            # Add policy rule
            rc, _, stderr = await self._exec(
                f"ip rule add from {ip} table {_POLICY_TABLE} priority {_POLICY_PRIORITY}"
            )
            if rc != 0 and "File exists" not in stderr:
                logger.error(f"Failed to add ip rule: {stderr}")

            # Add route in table 100
            rc, _, stderr = await self._exec(
                f"ip route add default via {gw} dev {iface} table {_POLICY_TABLE}"
            )
            if rc != 0 and "File exists" not in stderr:
                logger.error(f"Failed to add route table {_POLICY_TABLE}: {stderr}")

            logger.info(f"Bypass routing set up: from {ip} → via {gw} dev {iface} table {_POLICY_TABLE}")
        except Exception as e:
            logger.error(f"Error setting up bypass routing: {e}")

    async def cleanup_bypass_routing(self, ip: str) -> None:
        """Remove the policy rule and routing table created by
        :meth:`setup_bypass_routing`.
        """
        if not ip:
            logger.debug("cleanup_bypass_routing: no IP provided, skipping")
            return

        try:
            # Remove policy rule (may need to remove multiple times if duplicated)
            for _ in range(5):
                rc, _, _ = await self._exec(
                    f"ip rule del from {ip} table {_POLICY_TABLE} priority {_POLICY_PRIORITY}"
                )
                if rc != 0:
                    break  # no more matching rules

            # Flush routing table 100
            await self._exec(f"ip route flush table {_POLICY_TABLE}")

            logger.info(f"Bypass routing cleaned up for {ip}")
        except Exception as e:
            logger.error(f"Error cleaning up bypass routing: {e}")

    # ------------------------------------------------------------------
    # Static routes (anti-loop for WARP endpoint)
    # ------------------------------------------------------------------

    async def add_static_route(self, cidr: str, gw: str, iface: str) -> None:
        """Add a static route: ``ip route add {cidr} via {gw} dev {iface}``."""
        try:
            rc, _, stderr = await self._exec(f"ip route add {cidr} via {gw} dev {iface}")
            if rc != 0 and "File exists" not in stderr:
                logger.error(f"Failed to add static route {cidr}: {stderr}")
            else:
                logger.info(f"Static route added: {cidr} via {gw} dev {iface}")
        except Exception as e:
            logger.error(f"Error adding static route {cidr}: {e}")

    async def delete_static_route(self, cidr: str) -> None:
        """Delete a static route: ``ip route del {cidr}``."""
        try:
            rc, _, stderr = await self._exec(f"ip route del {cidr}")
            if rc != 0 and "No such process" not in stderr:
                logger.error(f"Failed to delete static route {cidr}: {stderr}")
            else:
                logger.info(f"Static route deleted: {cidr}")
        except Exception as e:
            logger.error(f"Error deleting static route {cidr}: {e}")

    # ------------------------------------------------------------------
    # Default interface (TUN)
    # ------------------------------------------------------------------

    async def set_default_interface(self, tun_name: str) -> None:
        """Add a default route with lower metric (higher priority) via TUN.

        Avoids replacing the existing default route to prevent network loss on crash.
        """
        try:
            # Metric 1 is higher priority than typical default routes (usually 100+)
            cmd = f"ip route add default dev {tun_name} metric 1"
            rc, _, stderr = await self._exec(cmd)
            if rc != 0:
                if "File exists" in stderr:
                    logger.warning(f"Default route via {tun_name} metric 1 already exists.")
                else:
                    logger.error(f"Failed to set default interface to {tun_name}: {stderr}")
            else:
                logger.info(f"Default route set to dev {tun_name} metric 1")
        except Exception as e:
            logger.error(f"Error setting default interface: {e}")

    async def remove_default_interface(self, tun_name: str) -> None:
        """Remove the high-priority default route via TUN."""
        try:
            cmd = f"ip route del default dev {tun_name} metric 1"
            rc, _, stderr = await self._exec(cmd)
            if rc != 0 and "No such process" not in stderr:
                 logger.error(f"Failed to remove default route via {tun_name}: {stderr}")
            else:
                 logger.info(f"Default route removed from dev {tun_name}")
        except Exception as e:
            logger.error(f"Error removing default interface: {e}")

    # ------------------------------------------------------------------
    # Docker Compatibility (Port Mapping Fixes)
    # ------------------------------------------------------------------

    async def setup_docker_bypass(self) -> None:
        """Configure policy routing so Docker containers bypass the TUN interface.

        Routes private subnets (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) to the
        'main' table, ensuring they use the physical gateway instead of the TUN default route.
        """
        try:
            logger.info("Setting up Docker/Private bypass rules (Host-Only Mode)...")
            
            # Subnets to exclude from TUN
            subnets = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
            
            for subnet in subnets:
                # Priority 50: Process before default route
                cmd = f"ip rule add from {subnet} table main priority 50"
                rc, _, stderr = await self._exec(cmd)
                if rc != 0 and "File exists" not in stderr:
                    logger.error(f"Failed to add bypass rule for {subnet}: {stderr}")

            logger.info("Docker bypass rules applied")
        except Exception as e:
            logger.error(f"Error setting up Docker bypass: {e}")

    async def cleanup_docker_bypass(self) -> None:
        """Remove policy routing rules for Docker bypass."""
        try:
            subnets = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
            
            for subnet in subnets:
                # Clean up rules (loop to handle potential duplicates)
                for _ in range(3):
                    cmd = f"ip rule del from {subnet} table main priority 50"
                    rc, _, _ = await self._exec(cmd)
                    if rc != 0:
                        break # No more rules
            
            logger.info("Docker bypass rules removed")
        except Exception as e:
            logger.error(f"Error cleaning up Docker bypass: {e}")

    # ------------------------------------------------------------------
    # Split Tunneling via warp-cli  (OfficialController)
    # ------------------------------------------------------------------

    async def split_tunnel_add(self, cidr: str) -> bool:
        """Add a CIDR to the Split Tunneling exclude list (traffic will bypass WARP).

        Uses ``warp-cli tunnel ip add <cidr>``.
        Returns *True* on success or if the entry already exists.
        """
        try:
            rc, stdout, stderr = await self._exec(f"warp-cli tunnel ip add {cidr}")
            if rc == 0:
                logger.info(f"Split tunnel add: {cidr}")
                return True
            # "Error: IP address already exists" — treat as success
            if "already exists" in stderr or "already exists" in stdout:
                logger.debug(f"Split tunnel add: {cidr} already exists, skipping")
                return True
            logger.error(f"Split tunnel add failed for {cidr}: {stderr}")
            return False
        except Exception as e:
            logger.error(f"Error in split_tunnel_add({cidr}): {e}")
            return False

    async def split_tunnel_remove(self, cidr: str) -> bool:
        """Remove a CIDR from the Split Tunneling exclude list.

        Uses ``warp-cli tunnel ip remove <cidr>``.
        Returns *True* on success or if the entry does not exist.
        """
        try:
            rc, stdout, stderr = await self._exec(f"warp-cli tunnel ip remove {cidr}")
            if rc == 0:
                logger.info(f"Split tunnel remove: {cidr}")
                return True
            # Entry not found — treat as success
            if "not found" in stderr or "not found" in stdout or "does not exist" in stderr:
                logger.debug(f"Split tunnel remove: {cidr} not found, skipping")
                return True
            logger.error(f"Split tunnel remove failed for {cidr}: {stderr}")
            return False
        except Exception as e:
            logger.error(f"Error in split_tunnel_remove({cidr}): {e}")
            return False

    async def split_tunnel_list(self) -> list[str]:
        """Return the current Split Tunneling exclude list as a list of CIDR strings.

        Uses ``warp-cli tunnel ip list`` and parses each non-empty line as a CIDR.
        """
        try:
            rc, stdout, stderr = await self._exec("warp-cli tunnel ip list")
            if rc != 0:
                logger.error(f"Split tunnel list failed: {stderr}")
                return []
            cidrs: list[str] = []
            for line in stdout.splitlines():
                line = line.strip()
                if line and ("/" in line or "." in line or ":" in line):
                    cidrs.append(line)
            return cidrs
        except Exception as e:
            logger.error(f"Error in split_tunnel_list: {e}")
            return []

    async def split_tunnel_reset(self) -> bool:
        """Reset the Split Tunneling exclude list to its default values.

        Uses ``warp-cli tunnel ip reset``.
        """
        try:
            rc, _, stderr = await self._exec("warp-cli tunnel ip reset")
            if rc != 0:
                logger.error(f"Split tunnel reset failed: {stderr}")
                return False
            logger.info("Split tunnel list reset to defaults")
            return True
        except Exception as e:
            logger.error(f"Error in split_tunnel_reset: {e}")
            return False

    async def setup_split_tunnel_bypass(self, cidrs: list[str]) -> bool:
        """Batch-add CIDRs to the Split Tunneling exclude list.

        Used to exclude multiple network ranges at once (e.g. panel IP, management
        subnet, SSH client IP).  Duplicate entries are silently ignored.

        Returns *True* if **all** additions succeeded.
        """
        if not cidrs:
            logger.debug("setup_split_tunnel_bypass: empty CIDR list, skipping")
            return True

        all_ok = True
        for cidr in cidrs:
            if not await self.split_tunnel_add(cidr):
                all_ok = False

        if all_ok:
            logger.info(f"Split tunnel bypass set up for {len(cidrs)} CIDRs")
        else:
            logger.warning("Split tunnel bypass: some CIDRs failed to add")
        return all_ok

    async def cleanup_split_tunnel_bypass(self, cidrs: list[str]) -> bool:
        """Batch-remove CIDRs from the Split Tunneling exclude list.

        Used during disconnect to clean up previously added exclude rules.
        Non-existent entries are silently ignored.

        Returns *True* if **all** removals succeeded.
        """
        if not cidrs:
            logger.debug("cleanup_split_tunnel_bypass: empty CIDR list, skipping")
            return True

        all_ok = True
        for cidr in cidrs:
            if not await self.split_tunnel_remove(cidr):
                all_ok = False

        if all_ok:
            logger.info(f"Split tunnel bypass cleaned up for {len(cidrs)} CIDRs")
        else:
            logger.warning("Split tunnel bypass: some CIDRs failed to remove")
        return all_ok

    # ------------------------------------------------------------------
    # Server / SSH client IP helpers
    # ------------------------------------------------------------------

    async def get_server_ip(self) -> Optional[str]:
        """Return the server's primary IP address.

        Prefers the *source_ip* from :meth:`get_default_route`.  Falls back to
        ``hostname -I`` if the default route does not include a source address.
        """
        try:
            _, _, source_ip = await self.get_default_route()
            if source_ip:
                return source_ip

            # Fallback: hostname -I returns space-separated IPs
            rc, stdout, _ = await self._exec("hostname -I")
            if rc == 0 and stdout:
                first_ip = stdout.split()[0].strip()
                if first_ip:
                    return first_ip
        except Exception as e:
            logger.error(f"Error getting server IP: {e}")

        return None

    async def get_ssh_client_ip(self) -> Optional[str]:
        """Return the IP address of the current SSH client, or *None*.

        Reads the ``SSH_CLIENT`` or ``SSH_CONNECTION`` environment variable to
        determine the remote peer.  This is useful for automatically excluding
        the administrator's SSH IP from the WARP tunnel to prevent lockout.
        """
        try:
            # SSH_CLIENT="<client_ip> <client_port> <server_port>"
            ssh_client = os.environ.get("SSH_CLIENT", "")
            if ssh_client:
                client_ip = ssh_client.split()[0].strip()
                if client_ip:
                    logger.debug(f"SSH client IP from SSH_CLIENT: {client_ip}")
                    return client_ip

            # SSH_CONNECTION="<client_ip> <client_port> <server_ip> <server_port>"
            ssh_conn = os.environ.get("SSH_CONNECTION", "")
            if ssh_conn:
                client_ip = ssh_conn.split()[0].strip()
                if client_ip:
                    logger.debug(f"SSH client IP from SSH_CONNECTION: {client_ip}")
                    return client_ip
        except Exception as e:
            logger.error(f"Error getting SSH client IP: {e}")

        return None
