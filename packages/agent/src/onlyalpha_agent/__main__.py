"""Operator startup and credential provisioning, never business commands."""

from __future__ import annotations

import argparse
import socket
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .security import AUDIENCE, issue_token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5174)
    serve.add_argument("--ssl-certfile")
    serve.add_argument("--ssl-keyfile")
    serve.add_argument("--contained-record", type=Path)
    setup = sub.add_parser("provision")
    setup.add_argument("--root", type=Path, required=True)
    setup.add_argument("--backend-root", type=Path, required=True)
    setup.add_argument("--dsn-file", type=Path, required=True)
    setup.add_argument("--agent-url", default="http://127.0.0.1:5174")
    token = sub.add_parser("access-token")
    token.add_argument("--subject", required=True)
    token.add_argument("--kind", choices=["human", "service"], required=True)
    token.add_argument("--scope", action="append", required=True)
    token.add_argument("--expires-in", type=int, required=True)
    args = parser.parse_args()
    if args.operation == "provision":
        from .deployment import provision

        provision(args.root, args.backend_root, args.dsn_file, args.agent_url)
        return
    settings = Settings.from_environment()
    if args.operation == "serve" and args.contained_record is not None:
        from .deployment import contained_gateway

        if args.host != "0.0.0.0" or args.port != 5174 or args.ssl_certfile:
            parser.error("contained transport requires exact dev listener")
        settings = replace(settings, contained_peer=contained_gateway(args.contained_record))
    if args.operation == "access-token":
        if not 0 < args.expires_in <= 86400:
            parser.error("expiry must be 1..86400 seconds")
        print(
            issue_token(
                settings.signing_key,
                subject=args.subject,
                audience=AUDIENCE,
                kind=args.kind,
                scopes=args.scope,
                token_id=str(uuid4()),
                expires_at=int(time.time()) + args.expires_in,
            )
        )
        return
    if (
        bool(args.ssl_certfile) != bool(args.ssl_keyfile)
        or args.host not in {"127.0.0.1", "::1", "localhost"}
        and not args.ssl_certfile
        and settings.contained_peer is None
    ):
        parser.error("remote listener requires explicit TLS certificate and key")
    import uvicorn

    from .app import create_app

    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets: list[socket.socket] | None = None) -> None:
            await super().startup(sockets)
            if self.started:
                print("ONLYALPHA_AGENT_READY", flush=True)

    ReadyServer(
        uvicorn.Config(
            create_app(settings),
            host=args.host,
            port=args.port,
            workers=1,
            access_log=False,
            proxy_headers=False,
            ssl_certfile=args.ssl_certfile,
            ssl_keyfile=args.ssl_keyfile,
        )
    ).run()


if __name__ == "__main__":
    main()
