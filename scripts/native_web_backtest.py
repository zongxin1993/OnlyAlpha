"""Observe the native Web interruption at its frozen ClickHouse input boundary."""

from __future__ import annotations

import http.client
import http.server
import json
import re
import select
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import psycopg
from psycopg.rows import dict_row

from scripts.database_guard import assert_test_database

MEMBERS = ["causal_evidence", "close_curve", "economic_result", "execution_facts"]


def read_backtest(dsn: str, run_id: str, segment: str | None = None) -> dict | None:
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=2) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        db.execute("SET LOCAL statement_timeout = '1s'")
        return db.execute(
            """
            SELECT to_jsonb(r) AS run, b.payload AS binding, b.binding_fingerprint,
                   statement_timestamp()::text AS observed_at,
                   EXISTS (SELECT FROM public.market_revision_segment s
                       WHERE s.revision_id = 'market-data-revision:' || (b.payload::jsonb #>> '{market,source_revision}')
                         AND s.segment_id = %s) AS frozen_segment,
                   COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.attempt_number)
                       FROM public.backtest_run_attempt a WHERE a.run_id = r.run_id), '[]') AS attempts,
                   (SELECT to_jsonb(p) FROM public.job_publication p
                       WHERE p.job_kind = 'BACKTEST' AND p.run_id = r.run_id) AS publication,
                   COALESCE((SELECT jsonb_agg(m.member_key ORDER BY m.member_key)
                       FROM public.job_result_member m
                       WHERE m.job_kind = 'BACKTEST' AND m.run_id = r.run_id), '[]') AS members,
                   COALESCE((SELECT jsonb_object_agg(receipt.command_kind, receipt.facts)
                       FROM (SELECT c.command_kind, jsonb_agg(to_jsonb(c)) AS facts
                           FROM public.product_command_receipt c JOIN public.product_command_admission a
                           USING (command_id, command_kind, command_fingerprint)
                           WHERE c.outcome_kind = 'BACKTEST_RUN' AND c.outcome_id = r.run_id::text
                             AND c.command_kind IN ('CREATE_BACKTEST_RUN','CANCEL_BACKTEST_RUN')
                           GROUP BY c.command_kind) receipt), '{}') AS receipts
            FROM public.backtest_run r JOIN public.job_frozen_binding b
              ON b.job_kind = 'BACKTEST' AND b.run_id = r.run_id
            WHERE r.run_id = %s
            """,
            (segment, run_id),
        ).fetchone()


def require_active_input(snapshot: dict, run_id: str, command_id: str, namespace: str) -> None:
    run = snapshot["run"]
    assert run["run_id"] == run_id and run["state"] == "RUNNING", run
    assert run["admission_resolution_payload"]["runtime_work_binding"]["reason"] == command_id, run_id
    (receipt,) = snapshot["receipts"]["CREATE_BACKTEST_RUN"]
    assert receipt["command_id"] == command_id, run_id
    assert json.loads(snapshot["binding"])["scope"]["namespace"] == namespace, run_id
    assert snapshot["frozen_segment"] and not snapshot["publication"] and not snapshot["members"], run_id
    (attempt,) = snapshot["attempts"]
    assert attempt["state"] == "ACTIVE" and attempt["attempt_number"] == 1, attempt
    assert datetime.fromisoformat(attempt["lease_expires_at"]) > datetime.fromisoformat(snapshot["observed_at"])


def require_same_run(before: dict, after: dict) -> None:
    assert before["binding"] == after["binding"]
    assert before["binding_fingerprint"] == after["binding_fingerprint"]
    for key in ("run_id", "specification_fingerprint", "admission_resolution_fingerprint", "queued_at", "started_at"):
        assert before["run"][key] == after["run"][key], key
    assert before["receipts"]["CREATE_BACKTEST_RUN"] == after["receipts"]["CREATE_BACKTEST_RUN"]
    for key in ("attempt_id", "attempt_number", "worker_instance_id", "fencing_token", "claimed_at"):
        assert before["attempts"][0][key] == after["attempts"][0][key], key


def require_cancelled_backtest(before: dict, after: dict, command_id: str, requested_at: str) -> None:
    require_same_run(before, after)
    run = after["run"]
    (receipt,) = after["receipts"]["CANCEL_BACKTEST_RUN"]
    assert receipt["command_id"] == command_id, receipt
    accepted = datetime.fromisoformat(receipt["accepted_at"])
    assert datetime.fromisoformat(run["cancel_requested_at"]) == accepted == datetime.fromisoformat(requested_at)
    assert run["state"] == "CANCELLED" and datetime.fromisoformat(run["finished_at"]) >= accepted, run
    (attempt,) = after["attempts"]
    assert attempt["state"] == "CANCELLED", attempt
    assert not after["publication"] and not after["members"], run["run_id"]


def require_stopped_backtest(before: dict, after: dict) -> None:
    require_same_run(before, after)
    assert after["run"]["state"] == "RUNNING" and after["run"]["cancel_requested_at"] is None
    (attempt,) = after["attempts"]
    assert attempt["state"] == "ACTIVE", attempt
    assert datetime.fromisoformat(attempt["lease_expires_at"]) > datetime.fromisoformat(after["observed_at"])
    assert before["receipts"] == after["receipts"]
    assert not after["publication"] and not after["members"], after["run"]["run_id"]


def require_resumed_backtest(before: dict, after: dict) -> None:
    require_same_run(before, after)
    run = after["run"]
    assert run["state"] == "COMPLETED" and run["cancel_requested_at"] is None, run
    assert before["receipts"] == after["receipts"]
    expired, succeeded = after["attempts"]
    assert expired["state"] == "EXPIRED" and expired["failure_code"] == "LEASE_EXPIRED", expired
    assert expired["lease_expires_at"] == before["attempts"][0]["lease_expires_at"], expired
    assert (
        datetime.fromisoformat(expired["lease_expires_at"])
        <= datetime.fromisoformat(expired["finished_at"])
        <= datetime.fromisoformat(succeeded["claimed_at"])
    )
    assert succeeded["state"] == "SUCCEEDED" and succeeded["attempt_number"] == 2, succeeded
    assert succeeded["attempt_id"] != expired["attempt_id"] and succeeded["fencing_token"] > expired["fencing_token"]
    publication = after["publication"]
    assert publication["binding_fingerprint"] == before["binding_fingerprint"], publication
    for field, attempt_field in (
        ("attempt_id", "attempt_id"),
        ("attempt_number", "attempt_number"),
        ("fence", "fencing_token"),
        ("worker_id", "worker_instance_id"),
    ):
        assert publication[field] == succeeded[attempt_field], publication
    for field in ("evidence_fingerprint", "result_fingerprint", "determinism_fingerprint"):
        assert run[field] == publication["publication_fingerprint"], field
    assert after["members"] == MEMBERS, after["members"]


@contextmanager
def frozen_market_barrier(dsn: str, namespace: str, database: str, upstream: str, stop_host, wait_for_host):
    assert_test_database(dsn)
    assert re.fullmatch(r"onlyalpha_test_native_host_[0-9a-f]{32}", database)
    assert upstream == "http://clickhouse:8123"
    lock = threading.Lock()
    stop_completed = threading.Event()
    armed = None
    observations = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_json(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            with lock:
                observed = observations.get(self.path.removeprefix("/backtest-input/"))
                value = None if observed is None else observed["status"]
            self.send_json(value)

        def do_POST(self):
            nonlocal armed
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/backtest-input/arm":
                kind, run_id, command_id = json.loads(body)
                assert kind in ("CANCELLED", "RUNNING")
                for identity in (run_id, command_id):
                    assert str(uuid.UUID(identity)) == identity and uuid.UUID(identity).version == 4
                with lock:
                    assert armed is None and run_id not in observations
                    armed = (kind, run_id, command_id)
                self.send_json(True)
                return
            if self.path == "/backtest-input/stop":
                with lock:
                    observed = observations[json.loads(body)]
                    assert observed["kind"] == "RUNNING" and observed["status"] == "HELD"
                    observed["status"] = "STOP_REQUESTED"
                    request_stop.sendall(b"1")
                assert stop_completed.wait(5), "Frozen ClickHouse socket did not settle"
                with lock:
                    sent = "sigterm_at" in observed
                if sent:
                    wait_for_host()
                self.send_json(sent)
                return
            self.clickhouse(body)

        def clickhouse(self, body):
            nonlocal armed
            arrived = time.monotonic()
            path = urlsplit(self.path)
            params = parse_qs(path.query)
            assert path.path == "/" and not path.netloc and params.get("database") == [database]
            observed = None
            trace = self.headers.get("x-onlyalpha-job-correlation", "").split(":")
            if b" WHERE segment_id={segment:String} LIMIT " in body and body.startswith(b"SELECT "):
                (segment,) = params["param_segment"]
                with lock:
                    if armed is not None and trace[0] == armed[1]:
                        kind, run_id, command_id = armed
                        snapshot = read_backtest(dsn, run_id, segment)
                        assert snapshot is not None, run_id
                        require_active_input(snapshot, run_id, command_id, namespace)
                        (attempt,) = snapshot["attempts"]
                        assert trace == [run_id, command_id, str(attempt["attempt_number"])], trace
                        observed = observations[run_id] = {
                            "kind": kind,
                            "status": "HELD",
                            "before": snapshot,
                            "segment_id": segment,
                            "request_correlation": trace,
                        }
                        armed = None
            if observed is not None:
                deadline = arrived + 5
                sockets = [self.connection, stop_input] if observed["kind"] == "RUNNING" else [self.connection]
                ready, _, _ = select.select(sockets, [], [], max(0, deadline - time.monotonic()))
                if self.connection not in ready and stop_input in ready:
                    stop_input.recv(1)
                    ready, _, _ = select.select([self.connection], [], [], 0)
                    if not ready and time.monotonic() < deadline:
                        with lock:
                            observed["sigterm_at"] = stop_host()
                        ready, _, _ = select.select([self.connection], [], [], max(0, deadline - time.monotonic()))
                disconnected = False
                if self.connection in ready:
                    try:
                        disconnected = self.connection.recv(1) == b""
                    except ConnectionResetError:
                        disconnected = True
                closed_at = time.monotonic()
                with lock:
                    observed["closed_at"] = closed_at
                    observed["hold_seconds"] = closed_at - arrived
                    observed["status"] = "DISCONNECTED" if disconnected else "UNPROVEN"
                if observed["kind"] == "RUNNING":
                    stop_completed.set()
                return
            upstream = http.client.HTTPConnection("clickhouse", 8123, timeout=5)
            try:
                upstream.request(
                    "POST",
                    self.path,
                    body=body,
                    headers={
                        "Authorization": self.headers["Authorization"],
                        "Content-Type": self.headers["Content-Type"],
                    },
                )
                with upstream.getresponse() as reply:
                    data = reply.read()
                    self.send_response(reply.status)
                    for key in ("Content-Type", "X-ClickHouse-Summary"):
                        if value := reply.getheader(key):
                            self.send_header(key, value)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            finally:
                upstream.close()

    stop_input, request_stop = socket.socketpair()
    with stop_input, request_stop, http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.daemon_threads = False
        worker = threading.Thread(target=server.serve_forever, name="frozen-clickhouse-input")
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", observations
        finally:
            server.shutdown()
            worker.join()
