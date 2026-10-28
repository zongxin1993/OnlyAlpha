"""Isolated Agent database on the canonical test PostgreSQL service."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from onlyalpha_agent.config import Settings
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


@pytest.fixture
def model_server():
    state = SimpleNamespace(calls=0, requests=[], entered=threading.Event(), release=None)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state.calls += 1
            state.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            state.entered.set()
            if state.release is not None:
                assert state.release.wait(10), "controlled model barrier was not released"
            body = json.dumps(
                {"choices": [{"message": {"content": json.dumps({"message": "需要明确观察周期", "candidate": None})}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def settings():
    # Test-only provisioning credentials never enter the service Settings.
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    info = conninfo_to_dict(dsn)
    assert info.get("dbname", "").endswith("_test"), "canonical _test DSN required"
    name = "oa_agent_" + uuid4().hex + "_test"
    password = uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(name), sql.Identifier(name)))
        admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
        agent = make_conninfo(dsn, dbname=name, user=name, password=password)
        try:
            yield Settings(agent, b"e" * 32, b"s" * 32)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))
