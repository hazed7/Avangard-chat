from collections.abc import Mapping
from ipaddress import ip_address

from app.core.config import ProxySettings


def _normalize_ip(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None

    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:
        host, port = candidate.rsplit(":", maxsplit=1)
        if port.isdigit():
            candidate = host

    try:
        ip_address(candidate)
    except ValueError:
        return None
    return candidate


def _is_trusted_proxy(ip: str, proxy: ProxySettings) -> bool:
    try:
        parsed = ip_address(ip)
    except ValueError:
        return False
    return any(parsed in network for network in proxy.trusted_proxy_cidrs)


def _parse_x_forwarded_for(raw: str | None) -> list[str]:
    if not raw:
        return []
    parsed: list[str] = []
    for token in raw.split(","):
        normalized = _normalize_ip(token)
        if normalized:
            parsed.append(normalized)
    return parsed


def resolve_client_ip(
    *,
    peer_ip: str | None,
    headers: Mapping[str, str],
    proxy: ProxySettings,
) -> str:
    normalized_peer = _normalize_ip(peer_ip or "")
    if not normalized_peer:
        return "unknown"

    if not proxy.trust_forwarded_headers:
        return normalized_peer
    if not _is_trusted_proxy(normalized_peer, proxy):
        return normalized_peer

    forwarded_hops = _parse_x_forwarded_for(headers.get("x-forwarded-for"))
    if forwarded_hops:
        chain = [*forwarded_hops, normalized_peer]
        for hop in reversed(chain):
            if not _is_trusted_proxy(hop, proxy):
                return hop
        return forwarded_hops[0]

    real_ip = _normalize_ip(headers.get("x-real-ip", ""))
    if real_ip:
        return real_ip

    return normalized_peer
