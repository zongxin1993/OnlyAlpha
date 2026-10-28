"""Operator startup and credential provisioning, never business commands."""

from __future__ import annotations

import argparse
import time
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
    token = sub.add_parser("access-token")
    token.add_argument("--subject", required=True)
    token.add_argument("--kind", choices=["human", "service"], required=True)
    token.add_argument("--scope", action="append", required=True)
    token.add_argument("--expires-in", type=int, required=True)
    args = parser.parse_args()
    settings = Settings.from_environment()
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
    ):
        parser.error("remote listener requires explicit TLS certificate and key")
    import uvicorn

    from .app import create_app

    uvicorn.run(
        create_app(settings),
        host=args.host,
        port=args.port,
        workers=1,
        access_log=False,
        proxy_headers=False,
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
    )


if __name__ == "__main__":
    main()
