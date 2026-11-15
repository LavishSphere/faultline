"""Client address -> rate-limit key. Shared by the edge limiter (main.RateLimitMiddleware) and the public-inference
per-IP budgets (routes/public_inference.py), so both count the same client the same way.

The address is `scope["client"]`: behind Caddy, uvicorn --proxy-headers sets it from X-Forwarded-For, trusted ONLY
from the edge subnet (FORWARDED_ALLOW_IPS in deploy/docker-compose.yml). Nothing here reads a forwarding header.
"""

from __future__ import annotations

import ipaddress
from typing import Any


def rate_limit_key(host: str) -> str:
    """IPv4: the address. IPv6: its /64, since one client can rotate through a whole /64 (docs/DEPLOY.md)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, 64), strict=False))
    return str(ip)


def client_key(client: Any) -> str:
    """Key for an ASGI `scope["client"]` tuple or a Starlette `request.client`; "unknown" when absent."""
    host = getattr(client, "host", None)
    if host is None and isinstance(client, tuple | list) and client:
        host = client[0]
    return rate_limit_key(host if isinstance(host, str) else "unknown")
