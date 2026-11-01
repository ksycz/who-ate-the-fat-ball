"""Find the camera on the LAN after its DHCP address changed."""

import ipaddress
import logging
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 0.5
_ARP_LINE = re.compile(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-fA-F:]+)")


def is_open(host: str, port: int, timeout: float = PROBE_TIMEOUT_S) -> bool:
    """A plain TCP connect, closed straight away."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _norm_mac(mac: str) -> str:
    # macOS `arp -a` drops leading zeros ("a:b:c:..."); compare on two-digit lower-case octets.
    return ":".join(part.zfill(2) for part in mac.lower().replace("-", ":").split(":"))


def arp_table() -> dict[str, str]:
    """{normalised mac: ip} from `arp -an`; empty if it can't be read."""
    try:
        out = subprocess.run(["arp", "-an"], check=False, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return {_norm_mac(m.group(2)): m.group(1) for m in _ARP_LINE.finditer(out)}


def local_ipv4() -> str | None:
    """This machine's LAN address (a UDP connect sends nothing)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def _network(subnet: str) -> ipaddress.IPv4Network:
    """Accept a /24 ("192.168.1.0/24") or any address in it ("192.168.1.5")."""
    if "/" in subnet:
        return ipaddress.ip_network(subnet, strict=False)
    return ipaddress.ip_network(f"{subnet}/24", strict=False)


def find_camera(subnet: str, port: int, mac: str | None) -> str | None:
    """Cached IP first (when `subnet` is an address), then the ARP table for `mac`, then a /24 scan."""
    if "/" not in subnet and is_open(subnet, port):
        return subnet
    if mac:
        ip = arp_table().get(_norm_mac(mac))
        if ip and is_open(ip, port):
            return ip
    hosts = [str(h) for h in _network(subnet).hosts()]
    with ThreadPoolExecutor(max_workers=64) as pool:
        for host, ok in zip(hosts, pool.map(lambda h: is_open(h, port), hosts)):
            if ok:
                log.info("camera found at %s:%d", host, port)
                return host
    return None
