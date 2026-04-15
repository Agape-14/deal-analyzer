"""Dual-stack uvicorn launcher for Railway.

Railway's private network resolves `<service>.railway.internal` to
IPv6 addresses, but their healthcheck probe connects over IPv4 (from
a sibling process on the same node). Binding uvicorn to `--host ::`
relies on Linux's default `net.ipv6.bindv6only=0` to accept both
families — but some container runtimes flip that to 1, leaving us
with an IPv6-only listener that Railway's IPv4 healthcheck can't
reach.

This script creates the listening socket explicitly with
`IPV6_V6ONLY = 0` so dual-stack is guaranteed regardless of the
kernel default. Uvicorn then attaches to the existing fd rather
than binding itself.
"""

from __future__ import annotations

import os
import socket

import uvicorn


def _make_dualstack_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("::", port))
    sock.listen(2048)  # high enough that burst traffic isn't refused
    return sock


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    sock = _make_dualstack_socket(port)

    config = uvicorn.Config(
        "app.main:app",
        fd=sock.fileno(),
        # host/port are informational when `fd` is given, but uvicorn
        # uses them in its startup log — match reality so the log is
        # honest about what's listening.
        host="::",
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        # Trust Railway's proxy for forwarded headers (client IP,
        # scheme) so downstream rate-limit keying works correctly.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
