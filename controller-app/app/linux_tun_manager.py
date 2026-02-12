import asyncio
import logging
import re
import shutil
import os
import platform
from typing import Optional, Tuple, Union, List, Set, Dict

logger = logging.getLogger(__name__)


class FirewallSnapshot:
    """
    在开启 TUN 之前，对系统现有防火墙规则做一次快照。
    记录哪些 TCP/UDP 端口和接口被放行，以便后续在 cloudflare-warp 表中恢复。
    """

    def __init__(self):
        # 协议 -> 端口集合
        self.tcp_ports: Set[int] = set()
        self.udp_ports: Set[int] = set()
        # 被放行的入接口名（精确匹配，如 "lo"、"docker0"）
        self.allowed_ifaces: Set[str] = set()
        # 被放行的入接口通配符（如 "docker*", "veth*"）
        self.allowed_iface_patterns: Set[str] = set()

    def merge_ports(self, extra_ports: List[int]):
        """将 warppool 自身需要的端口也合并进来"""
        for p in extra_ports:
            self.tcp_ports.add(p)
            self.udp_ports.add(p)

    @property
    def all_ports(self) -> Set[int]:
        return self.tcp_ports | self.udp_ports

    def __repr__(self):
        return (
            f"FirewallSnapshot(tcp={sorted(self.tcp_ports)}, "
            f"udp={sorted(self.udp_ports)}, "
            f"ifaces={self.allowed_ifaces}, "
            f"iface_patterns={self.allowed_iface_patterns})"
        )


class LinuxTunManager:
    """
    Helper class for managing Linux TUN/TAP routing and firewall rules.
    Designed for platform-exclusive operations on Linux.
    """

    # 定义私有网段，用于防止 Docker/局域网流量被错误路由
    PRIVATE_SUBNETS = [
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16"
    ]

    # 所有由 warppool 写入 cloudflare-warp 表的规则都带此前缀注释
    COMMENT_PREFIX = "warppool-"

    def __init__(self):
        self.check_platform()

    def check_platform(self):
        if platform.system() != "Linux":
            msg = "LinuxTunManager instantiated on non-Linux platform."
            logger.critical(msg)
            raise RuntimeError(msg)

    # ------------------------------------------------------------------
    # 通用 helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _run_command(command: Union[str, List[str]]) -> Tuple[int, str, str]:
        """
        Helper to run async shell commands.
        Supports both string (shell=True, unsafe) and list (exec, safe).
        """
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

            stdout, stderr = await process.communicate()
            return process.returncode, stdout.decode().strip(), stderr.decode().strip()
        except Exception as e:
            cmd_str = command if isinstance(command, str) else " ".join(command)
            logger.error(f"Error running command '{cmd_str}': {e}")
            return -1, "", str(e)

    @staticmethod
    def is_docker() -> bool:
        """Check if running inside a Docker container."""
        if os.path.exists('/.dockerenv'):
            return True
        path = '/proc/self/cgroup'
        try:
            if os.path.isfile(path):
                with open(path, 'r') as f:
                    content = f.read()
                    return 'docker' in content or 'kubepods' in content
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # 路由信息
    # ------------------------------------------------------------------

    @classmethod
    async def get_default_route(cls) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get original default gateway, interface, and primary IP.
        Returns: (gateway, interface, ip_address)
        """
        gw, iface, ip = None, None, None
        try:
            rc, stdout, _ = await cls._run_command(["ip", "route", "show", "default"])
            lines = stdout.split('\n')
            if lines:
                parts = lines[0].split()
                if 'via' in parts:
                    gw = parts[parts.index('via') + 1]
                if 'dev' in parts:
                    iface = parts[parts.index('dev') + 1]
        except Exception as e:
            logger.warning(f"Could not get default route: {e}")
            return None, None, None

        if iface:
            try:
                rc, stdout, _ = await cls._run_command(["ip", "-4", "-o", "addr", "show", "dev", iface])
                for line in stdout.split('\n'):
                    if 'inet ' in line:
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

    # ------------------------------------------------------------------
    # 策略路由 (Bypass Routing)
    # ------------------------------------------------------------------

    @classmethod
    async def setup_bypass_routing(cls, gw: str, iface: str, ip: str, table_id: int = 100):
        """
        Set up policy routing to ensure traffic from specific IP and Local subnets
        uses the original gateway (bypassing the VPN/TUN).
        """
        if not gw or not iface or not ip:
            logger.warning("Missing routing info, skipping bypass routing setup.")
            return

        try:
            logger.info(f"Setting up bypass routing: from {ip} -> table {table_id} via {gw} dev {iface}")

            await cls._run_command(["ip", "route", "add", "default", "via", gw, "dev", iface, "table", str(table_id)])

            rc, stdout, _ = await cls._run_command(["ip", "route", "show", "dev", iface, "scope", "link"])
            for line in stdout.split('\n'):
                subnet = line.split()[0] if line.strip() else None
                if subnet:
                    await cls._run_command(["ip", "route", "add", subnet, "dev", iface, "table", str(table_id)])

            for subnet in cls.PRIVATE_SUBNETS:
                await cls._run_command(["ip", "rule", "del", "to", subnet, "lookup", "main"])
                await cls._run_command(["ip", "rule", "add", "to", subnet, "lookup", "main", "priority", "4900"])

            await cls._run_command(["ip", "rule", "del", "from", ip, "lookup", str(table_id)])
            await cls._run_command(["ip", "rule", "add", "from", ip, "lookup", str(table_id), "priority", "5000"])

        except Exception as e:
            logger.error(f"Failed to setup bypass routing: {e}")

    @classmethod
    async def cleanup_bypass_routing(cls, ip: Optional[str], table_id: int = 100):
        """Remove the bypass routing rules and flush the custom table."""
        try:
            for subnet in cls.PRIVATE_SUBNETS:
                await cls._run_command(["ip", "rule", "del", "to", subnet, "lookup", "main", "priority", "4900"])
            if ip:
                await cls._run_command(["ip", "rule", "del", "from", ip, "lookup", str(table_id)])
            await cls._run_command(["ip", "route", "flush", "table", str(table_id)])
            logger.info(f"Bypass routing (table {table_id}) cleaned up.")
        except Exception as e:
            logger.error(f"Error cleaning up bypass routing: {e}")

    # ------------------------------------------------------------------
    # 静态路由 / 接口
    # ------------------------------------------------------------------

    @classmethod
    async def add_static_route(cls, target: str, gateway: str, interface: str):
        """Add a specific static route via a gateway."""
        try:
            logger.info(f"Adding static route: {target} via {gateway}")
            await cls._run_command(["ip", "route", "add", target, "via", gateway, "dev", interface])
        except Exception as e:
            logger.error(f"Failed to add static route: {e}")

    @classmethod
    async def delete_static_route(cls, target: str):
        """Delete a specific static route."""
        try:
            await cls._run_command(["ip", "route", "del", target])
        except Exception as e:
            logger.error(f"Failed to delete static route: {e}")

    @classmethod
    async def set_default_interface(cls, interface: str):
        """Replace the default system route to go through a specific interface."""
        try:
            logger.info(f"Replacing default route with dev {interface}")
            await cls._run_command(["ip", "route", "replace", "default", "dev", interface])
        except Exception as e:
            logger.error(f"Failed to set default interface: {e}")

    @classmethod
    async def tun_interface_exists(cls, pattern: str = "tun") -> bool:
        """Check if any interface matching the pattern exists."""
        try:
            rc, stdout, _ = await cls._run_command(["ip", "link", "show"])
            return any(pattern in line for line in stdout.split('\n'))
        except Exception:
            return False

    @classmethod
    async def get_tun_interface_name(cls, prefix: str = "tun") -> Optional[str]:
        """Get the name of the first interface starting with prefix."""
        try:
            rc, stdout, _ = await cls._run_command(["ip", "-o", "link", "show"])
            for line in stdout.split('\n'):
                parts = line.split(':')
                if len(parts) >= 2:
                    name = parts[1].strip()
                    if name.startswith(prefix):
                        return name
        except Exception:
            pass
        return None

    # ==================================================================
    # 防火墙快照（iptables + nftables + 监听端口）
    # ==================================================================

    @classmethod
    async def capture_firewall_snapshot(cls) -> FirewallSnapshot:
        """
        在 WARP 连接之前调用。采集系统现有防火墙放行规则，生成快照。
        优先级：
          1. iptables -S INPUT  —— 解析 ACCEPT 规则中的 --dport
          2. nftables（排除 cloudflare-warp 表）—— 解析 accept 规则中的 dport
          3. ss -lntu           —— 所有正在监听的端口作为兜底补充
        """
        snap = FirewallSnapshot()

        await cls._capture_from_iptables(snap)
        await cls._capture_from_nftables(snap)
        await cls._capture_from_listening_ports(snap)

        logger.info(f"Firewall snapshot captured: {snap}")
        return snap

    @classmethod
    async def _capture_from_iptables(cls, snap: FirewallSnapshot):
        """解析 iptables INPUT 链中的 ACCEPT 规则"""
        if not shutil.which("iptables"):
            return

        try:
            rc, stdout, _ = await cls._run_command(["iptables", "-S", "INPUT"])
            if rc != 0:
                return

            for line in stdout.split('\n'):
                line = line.strip()
                # 只关心 ACCEPT 规则
                if '-j ACCEPT' not in line and '--jump ACCEPT' not in line:
                    continue

                # 解析端口：--dport 22 或 --dport 80:90
                dport_match = re.search(r'--dport\s+(\S+)', line)
                if dport_match:
                    port_str = dport_match.group(1)
                    ports = cls._parse_port_spec(port_str)
                    proto = 'tcp'
                    if '-p udp' in line or '--protocol udp' in line:
                        proto = 'udp'
                    elif '-p tcp' in line or '--protocol tcp' in line:
                        proto = 'tcp'
                    else:
                        # 没指定协议，两个都加
                        snap.tcp_ports.update(ports)
                        snap.udp_ports.update(ports)
                        continue

                    if proto == 'tcp':
                        snap.tcp_ports.update(ports)
                    else:
                        snap.udp_ports.update(ports)
                    continue

                # 解析 multiport：--dports 22,80,443
                dports_match = re.search(r'--dports\s+(\S+)', line)
                if dports_match:
                    port_str = dports_match.group(1)
                    ports: Set[int] = set()
                    for part in port_str.split(','):
                        ports.update(cls._parse_port_spec(part.strip()))

                    proto = 'tcp'
                    if '-p udp' in line or '--protocol udp' in line:
                        proto = 'udp'
                    elif '-p tcp' in line or '--protocol tcp' in line:
                        proto = 'tcp'
                    else:
                        snap.tcp_ports.update(ports)
                        snap.udp_ports.update(ports)
                        continue

                    if proto == 'tcp':
                        snap.tcp_ports.update(ports)
                    else:
                        snap.udp_ports.update(ports)
                    continue

                # 解析接口放行：-i lo -j ACCEPT
                iif_match = re.search(r'-i\s+(\S+)', line)
                if iif_match:
                    iface = iif_match.group(1)
                    if '*' in iface or '+' in iface:
                        # iptables 用 + 做通配
                        snap.allowed_iface_patterns.add(iface.replace('+', '*'))
                    else:
                        snap.allowed_ifaces.add(iface)

        except Exception as e:
            logger.warning(f"Failed to capture iptables rules: {e}")

    @classmethod
    async def _capture_from_nftables(cls, snap: FirewallSnapshot):
        """解析 nftables 中非 cloudflare-warp 表的 accept 规则"""
        if not shutil.which("nft"):
            return

        try:
            rc, stdout, _ = await cls._run_command(["nft", "list", "ruleset"])
            if rc != 0:
                return

            # 按 table 分段解析，跳过 cloudflare-warp 表
            current_table = ""
            in_skip_table = False
            brace_depth = 0

            for line in stdout.split('\n'):
                stripped = line.strip()

                # 检测 table 开头
                table_match = re.match(r'^table\s+\S+\s+(\S+)\s*\{', stripped)
                if table_match:
                    current_table = table_match.group(1)
                    in_skip_table = (current_table == "cloudflare-warp")
                    brace_depth = 1
                    continue

                if in_skip_table:
                    brace_depth += stripped.count('{') - stripped.count('}')
                    if brace_depth <= 0:
                        in_skip_table = False
                    continue

                # 只处理含 accept 的行
                if 'accept' not in stripped:
                    continue

                # 解析 dport：tcp dport 22 accept / tcp dport { 22, 80, 443 } accept
                dport_match = re.search(r'(tcp|udp)\s+dport\s+\{?\s*([^}]+?)\s*\}?\s+accept', stripped)
                if dport_match:
                    proto = dport_match.group(1)
                    port_str = dport_match.group(2)
                    ports: Set[int] = set()
                    for part in port_str.split(','):
                        part = part.strip()
                        ports.update(cls._parse_port_spec(part))
                    if proto == 'tcp':
                        snap.tcp_ports.update(ports)
                    else:
                        snap.udp_ports.update(ports)
                    continue

                # 解析 iifname
                iif_match = re.search(r'iifname\s+"?(\S+?)"?\s+accept', stripped)
                if iif_match:
                    iface = iif_match.group(1).strip('"')
                    if '*' in iface:
                        snap.allowed_iface_patterns.add(iface)
                    else:
                        snap.allowed_ifaces.add(iface)

        except Exception as e:
            logger.warning(f"Failed to capture nftables rules: {e}")

    @classmethod
    async def _capture_from_listening_ports(cls, snap: FirewallSnapshot):
        """
        兜底：用 ss 获取所有正在监听的端口。
        这些端口上已经有进程在跑，WARP 防火墙不应阻断它们。
        只采集 0.0.0.0 / :: / * 上监听的端口（对外暴露的服务）。
        """
        try:
            rc, stdout, _ = await cls._run_command(["ss", "-lntu"])
            if rc != 0:
                return

            for line in stdout.split('\n'):
                parts = line.split()
                if len(parts) < 5:
                    continue

                proto_raw = parts[0].lower()  # tcp / udp / tcp6 / udp6
                local_addr = parts[4]         # 0.0.0.0:22 / :::22 / *:53

                # 只关注对外监听（0.0.0.0 / :: / *），127.0.0.1 忽略
                if local_addr.startswith("127."):
                    continue
                if local_addr.startswith("[::1]"):
                    continue

                # 提取端口
                port_str = local_addr.rsplit(':', 1)[-1]
                try:
                    port = int(port_str)
                except ValueError:
                    continue

                if 'tcp' in proto_raw:
                    snap.tcp_ports.add(port)
                elif 'udp' in proto_raw:
                    snap.udp_ports.add(port)

        except Exception as e:
            logger.warning(f"Failed to capture listening ports: {e}")

    @staticmethod
    def _parse_port_spec(spec: str) -> Set[int]:
        """
        解析端口说明，支持单端口 '22'、范围 '80-90'。
        """
        spec = spec.strip()
        result: Set[int] = set()
        if not spec:
            return result

        # 范围：80-90 或 80:90（iptables 格式）
        range_match = re.match(r'^(\d+)\s*[-:]\s*(\d+)$', spec)
        if range_match:
            lo, hi = int(range_match.group(1)), int(range_match.group(2))
            for p in range(lo, hi + 1):
                if 1 <= p <= 65535:
                    result.add(p)
            return result

        # 单端口
        try:
            p = int(spec)
            if 1 <= p <= 65535:
                result.add(p)
        except ValueError:
            pass
        return result

    # ==================================================================
    # nftables 规则应用（基于快照自适应）
    # ==================================================================

    @classmethod
    async def apply_nftables_allow_rules(
        cls,
        interface: str,
        ports: list[int],
        snapshot: Optional[FirewallSnapshot] = None,
    ):
        """
        向 cloudflare-warp 表注入放行规则。
        如果提供了 snapshot，则除了 warppool 自身需要的端口外，
        还会把快照中记录的端口和接口一并放行，保证原有服务不受 WARP 影响。
        """
        if not shutil.which("nft"):
            logger.warning("nft command not found, skipping nftables configuration")
            return

        logger.info("Waiting for WARP nftables table...")
        table_ready = False
        for _ in range(10):
            rc, _, _ = await cls._run_command(["nft", "list", "table", "inet", "cloudflare-warp"])
            if rc == 0:
                table_ready = True
                break
            await asyncio.sleep(0.5)

        if not table_ready:
            logger.warning("WARP nftables table not found.")
            return

        # 合并快照端口与 warppool 自身端口
        if snapshot:
            snapshot.merge_ports(ports)
            tcp_ports = sorted(snapshot.tcp_ports)
            udp_ports = sorted(snapshot.udp_ports)
            extra_ifaces = snapshot.allowed_ifaces
            extra_iface_patterns = snapshot.allowed_iface_patterns
        else:
            tcp_ports = list(ports)
            udp_ports = list(ports)
            extra_ifaces = set()
            extra_iface_patterns = set()

        logger.info(
            f"Applying nftables rules: iface={interface}, "
            f"tcp_ports={tcp_ports}, udp_ports={udp_ports}, "
            f"extra_ifaces={extra_ifaces}, extra_patterns={extra_iface_patterns}"
        )

        try:
            # 先清理旧规则（幂等）
            await cls.cleanup_nftables_rules()

            # 检查 forward 链是否存在
            forward_chain_exists = False
            rc, _, _ = await cls._run_command(["nft", "list", "chain", "inet", "cloudflare-warp", "forward"])
            if rc == 0:
                forward_chain_exists = True

            # ---- 1. 允许已建立连接 (Established/Related) ----
            await cls._run_command([
                "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                "ct", "state", "established,related", "accept",
                "comment", f"{cls.COMMENT_PREFIX}allow-established"
            ])
            if forward_chain_exists:
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "forward",
                    "ct", "state", "established,related", "accept",
                    "comment", f"{cls.COMMENT_PREFIX}allow-forward-established"
                ])

            # ---- 2. 允许回环接口 ----
            await cls._run_command([
                "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                "iifname", "lo", "accept",
                "comment", f"{cls.COMMENT_PREFIX}allow-loopback"
            ])

            # ---- 3. 允许 Docker 流量 ----
            await cls._run_command([
                "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                "iifname", "docker*", "accept",
                "comment", f"{cls.COMMENT_PREFIX}allow-docker"
            ])
            await cls._run_command([
                "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                "iifname", "br-*", "accept",
                "comment", f"{cls.COMMENT_PREFIX}allow-bridge"
            ])
            await cls._run_command([
                "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                "iifname", "veth*", "accept",
                "comment", f"{cls.COMMENT_PREFIX}allow-veth"
            ])
            if forward_chain_exists:
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "forward",
                    "iifname", "docker*", "accept",
                    "comment", f"{cls.COMMENT_PREFIX}forward-docker-in"
                ])
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "forward",
                    "oifname", "docker*", "accept",
                    "comment", f"{cls.COMMENT_PREFIX}forward-docker-out"
                ])
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "forward",
                    "iifname", "br-*", "accept",
                    "comment", f"{cls.COMMENT_PREFIX}forward-bridge-in"
                ])
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "forward",
                    "oifname", "br-*", "accept",
                    "comment", f"{cls.COMMENT_PREFIX}forward-bridge-out"
                ])
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "forward",
                    "iifname", "veth*", "accept",
                    "comment", f"{cls.COMMENT_PREFIX}forward-veth-in"
                ])
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "forward",
                    "oifname", "veth*", "accept",
                    "comment", f"{cls.COMMENT_PREFIX}forward-veth-out"
                ])

            # ---- 4. 恢复快照中记录的接口放行 ----
            for iface_name in extra_ifaces:
                # lo 和 docker* 已在上面处理
                if iface_name == "lo":
                    continue
                if iface_name.startswith("docker"):
                    continue
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                    "iifname", iface_name, "accept",
                    "comment", f"{cls.COMMENT_PREFIX}preserved-iface-{iface_name}"
                ])

            for pattern in extra_iface_patterns:
                if pattern.startswith("docker"):
                    continue
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                    "iifname", pattern, "accept",
                    "comment", f"{cls.COMMENT_PREFIX}preserved-pattern-{pattern}"
                ])

            # ---- 5. 允许物理网卡出站 ----
            await cls._run_command([
                "nft", "insert", "rule", "inet", "cloudflare-warp", "output",
                "oif", interface, "accept",
                "comment", f"{cls.COMMENT_PREFIX}controller-output"
            ])

            # ---- 6. 按端口放行入站 TCP ----
            for port in tcp_ports:
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                    "tcp", "dport", str(port), "accept",
                    "comment", f"{cls.COMMENT_PREFIX}allow-tcp-{port}"
                ])

            # ---- 7. 按端口放行入站 UDP ----
            for port in udp_ports:
                await cls._run_command([
                    "nft", "insert", "rule", "inet", "cloudflare-warp", "input",
                    "udp", "dport", str(port), "accept",
                    "comment", f"{cls.COMMENT_PREFIX}allow-udp-{port}"
                ])

            logger.info("nftables allow rules applied successfully")

        except Exception as e:
            logger.error(f"Failed to apply nftables rules: {e}")
            raise

    # ==================================================================
    # nftables 规则清理（按前缀统一清理）
    # ==================================================================

    @classmethod
    async def cleanup_nftables_rules(cls):
        """
        删除 cloudflare-warp 表中所有 comment 以 COMMENT_PREFIX 开头的规则。
        不再需要传端口列表——只要是 warppool 写的规则，全部清除。
        """
        if not shutil.which("nft"):
            return

        rc, _, _ = await cls._run_command(["nft", "list", "table", "inet", "cloudflare-warp"])
        if rc != 0:
            return

        logger.info("Cleaning up all warppool nftables rules...")

        try:
            for chain in ("input", "output", "forward"):
                rc, stdout, _ = await cls._run_command([
                    "nft", "-a", "list", "chain", "inet", "cloudflare-warp", chain
                ])
                if rc != 0:
                    continue

                # 查找所有带 warppool- 前缀注释的规则 handle
                handles = re.findall(
                    rf'comment\s+"({re.escape(cls.COMMENT_PREFIX)}[^"]*)".*?#\s*handle\s+(\d+)',
                    stdout
                )
                for comment_val, handle in handles:
                    await cls._run_command([
                        "nft", "delete", "rule", "inet", "cloudflare-warp", chain, "handle", handle
                    ])
                    logger.debug(f"Removed rule: {comment_val} (handle {handle})")

            logger.info("nftables rules cleanup complete")
        except Exception as e:
            logger.error(f"Error during nftables cleanup: {e}")
