"""Private Streamable HTTP transport for the existing AE tools, behind Tailscale Serve."""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

from starlette.responses import JSONResponse


class TailnetIdentityGate:
    """Trust identity headers only on the loopback-only Serve backend.

    Serve strips client-supplied identity headers. Do not expose this backend
    directly, enable proxy_headers, or use these headers behind another proxy.
    Local processes already have the same authority through the stdio server.
    """

    def __init__(self, app, *, hostname: str, login: str):
        self.app = app
        self.hosts = {hostname.lower(), hostname.lower() + ":443"}
        self.login = login.casefold()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        values: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            values.setdefault(key.lower(), []).append(value)
        peer = (scope.get("client") or ("", 0))[0]
        hosts = values.get(b"host", [])
        logins = values.get(b"tailscale-user-login", [])
        valid = (
            peer in {"127.0.0.1", "::1"}
            and len(hosts) == 1
            and hosts[0].decode("latin-1").lower() in self.hosts
            and len(logins) == 1
            and logins[0].decode("latin-1").casefold() == self.login
            and b"origin" not in values
            and b"sec-fetch-site" not in values
        )
        if not valid:
            await JSONResponse({"error": "tailnet_identity_required"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_app(hostname: str, login: str):
    from mcp.server.transport_security import TransportSecuritySettings
    from .server import mcp

    # Reuse every existing tool and its safeguards; never expose the raw AE port.
    mcp.settings.stateless_http = True
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[hostname, hostname + ":443"],
        allowed_origins=[],
    )
    return TailnetIdentityGate(mcp.streamable_http_app(), hostname=hostname, login=login)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    hostname = config["hostname"].strip().lower()
    login = config["allowed_login"].strip()
    port = int(config.get("port", 18890))
    if not hostname.endswith(".ts.net") or any(c in hostname for c in "/:@ ") or not login or not 1024 <= port <= 65535:
        raise ValueError("Expected a Tailscale hostname, allowed login, and unprivileged loopback port")
    log_dir = args.config.resolve().parent
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "tailnet-mcp.log", maxBytes=1048576, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(handlers=[handler], level=logging.WARNING, force=True)
    os.environ["AE2CLAUDE_PORT"] = str(config.get("ae_port", 18889))
    os.environ["AE2CLAUDE_APPROVAL_MODE"] = "auto"
    import uvicorn
    uvicorn.run(build_app(hostname, login), host="127.0.0.1", port=port,
                proxy_headers=False, access_log=False, log_config=None,
                timeout_keep_alive=10, timeout_graceful_shutdown=15,
                limit_concurrency=32)


if __name__ == "__main__":
    main()
