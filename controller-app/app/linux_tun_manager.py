"""
Linux TUN interface and routing manager for WarpPool.
Handles policy routing, nftables firewall rules, and TUN interface management.
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
_NFTABLES_TABLE_NAME = "warppool"
_NFTABLES_CHAIN_NAME = "input"


class LinuxTunManager:
    """Manage Linux TUN interface routing, policy rules, and nftables firewall."""

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
        """Replace the default route to go through the TUN interface."""
        try:
            rc, _, stderr = await self._exec(f"ip route replace default dev {tun_name}")
            if rc != 0:
                logger.error(f"Failed to set default interface to {tun_name}: {stderr}")
            else:
                logger.info(f"Default route set to dev {tun_name}")
        except Exception as e:
            logger.error(f"Error setting default interface: {e}")

    # ------------------------------------------------------------------
    # nftables firewall management
    # ------------------------------------------------------------------

    async def capture_firewall_snapshot(self) -> dict:
        """Capture the current nftables/iptables state *before* WARP modifies it.

        Returns a dict with keys ``nftables`` and ``iptables`` holding the raw
        rule-set text, which :meth:`apply_nftables_allow_rules` can reference
        when constructing allow rules.
        """
        snapshot: dict = {"nftables": "", "iptables": ""}

        try:
            rc, stdout, _ = await self._exec("nft list ruleset")
            if rc == 0:
                snapshot["nftables"] = stdout
        except Exception as e:
            logger.warning(f"Failed to capture nftables snapshot: {e}")

        try:
            rc, stdout, _ = await self._exec("iptables-save")
            if rc == 0:
                snapshot["iptables"] = stdout
        except Exception as e:
            logger.warning(f"Failed to capture iptables snapshot: {e}")

        logger.info("Firewall snapshot captured")
        return snapshot

    async def apply_nftables_allow_rules(
        self, iface: str, ports: list, snapshot: dict = None
    ) -> None:
        """Create an nftables table (``inet warppool``) with rules that allow
        inbound TCP traffic on the given *ports* through *iface*, as well as
        established/related traffic.

        Parameters
        ----------
        iface : str
            Physical network interface (e.g. ``eth0``).
        ports : list
            List of TCP port numbers to allow (panel, SOCKS5, …).
        snapshot : dict, optional
            Firewall snapshot from :meth:`capture_firewall_snapshot` (currently
            used only for logging / future reference).
        """
        if not ports:
            logger.warning("apply_nftables_allow_rules: empty port list, skipping")
            return

        try:
            # Clean up any previous warppool table first
            await self._exec(f"nft delete table inet {_NFTABLES_TABLE_NAME}")

            # Create the warppool table
            rc, _, stderr = await self._exec(f"nft add table inet {_NFTABLES_TABLE_NAME}")
            if rc != 0:
                logger.error(f"Failed to create nftables table: {stderr}")
                return

            # Create an input chain with type filter, hook input, priority 0, policy accept
            rc, _, stderr = await self._exec(
                f"nft add chain inet {_NFTABLES_TABLE_NAME} {_NFTABLES_CHAIN_NAME} "
                f"'{{ type filter hook input priority 0 ; policy accept ; }}'"
            )
            if rc != 0:
                logger.error(f"Failed to create nftables chain: {stderr}")
                return

            # Allow established/related connections
            rc, _, stderr = await self._exec(
                f"nft add rule inet {_NFTABLES_TABLE_NAME} {_NFTABLES_CHAIN_NAME} "
                f"ct state established,related accept"
            )
            if rc != 0:
                logger.error(f"Failed to add established/related rule: {stderr}")

            # Allow loopback
            rc, _, stderr = await self._exec(
                f"nft add rule inet {_NFTABLES_TABLE_NAME} {_NFTABLES_CHAIN_NAME} "
                f"iifname lo accept"
            )
            if rc != 0:
                logger.error(f"Failed to add loopback rule: {stderr}")

            # Allow specified TCP ports on the physical interface
            for port in ports:
                rc, _, stderr = await self._exec(
                    f"nft add rule inet {_NFTABLES_TABLE_NAME} {_NFTABLES_CHAIN_NAME} "
                    f"iifname {iface} tcp dport {port} accept"
                )
                if rc != 0:
                    logger.error(f"Failed to add allow rule for port {port}: {stderr}")

            logger.info(
                f"nftables allow rules applied: table={_NFTABLES_TABLE_NAME}, "
                f"iface={iface}, ports={ports}"
            )
        except Exception as e:
            logger.error(f"Error applying nftables rules: {e}")

    async def cleanup_nftables_rules(self) -> None:
        """Delete the ``inet warppool`` nftables table (all rules inside it)."""
        try:
            rc, _, stderr = await self._exec(f"nft delete table inet {_NFTABLES_TABLE_NAME}")
            if rc != 0:
                # Table may not exist — that's fine
                if "No such file or directory" not in stderr and "does not exist" not in stderr:
                    logger.warning(f"nftables cleanup notice: {stderr}")
            else:
                logger.info(f"nftables table '{_NFTABLES_TABLE_NAME}' deleted")
        except Exception as e:
            logger.error(f"Error cleaning up nftables rules: {e}")
