"""Agent-owned facts; backend effects and receipts are observed through scoped APIs."""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import Settings
from .model import endpoint
from .workflow import PROMPT, digest


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_schema (version integer PRIMARY KEY CHECK(version=1));
INSERT INTO agent_schema VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS agent_command (
 id uuid PRIMARY KEY, owner text NOT NULL, intent text NOT NULL, outcome jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS agent_model (
 revision text PRIMARY KEY, id uuid NOT NULL, owner text NOT NULL, payload jsonb NOT NULL, secret bytea NOT NULL);
CREATE TABLE IF NOT EXISTS agent_model_head (id uuid PRIMARY KEY, owner text NOT NULL, revision text NOT NULL REFERENCES agent_model);
CREATE TABLE IF NOT EXISTS agent_session (
 id uuid PRIMARY KEY, owner text NOT NULL, workflow text NOT NULL, model text NOT NULL REFERENCES agent_model,
 budget integer NOT NULL CHECK(budget BETWEEN 1 AND 100));
CREATE TABLE IF NOT EXISTS agent_event (
 command uuid PRIMARY KEY REFERENCES agent_command DEFERRABLE INITIALLY DEFERRED, session uuid NOT NULL REFERENCES agent_session,
 ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 100), fingerprint text NOT NULL UNIQUE,
 plan jsonb NOT NULL, UNIQUE(session,ordinal));
CREATE TABLE IF NOT EXISTS agent_result (
 command uuid PRIMARY KEY REFERENCES agent_event, fingerprint text NOT NULL, payload jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS agent_revocation (owner text NOT NULL, token_id text NOT NULL, PRIMARY KEY(owner,token_id));
CREATE TABLE IF NOT EXISTS agent_backend_plan (
 command uuid PRIMARY KEY REFERENCES agent_command DEFERRABLE INITIALLY DEFERRED,
 session uuid NOT NULL REFERENCES agent_session, backend_command uuid NOT NULL UNIQUE,
 fingerprint text NOT NULL, payload jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS agent_backend_result (
 command uuid PRIMARY KEY REFERENCES agent_backend_plan, fingerprint text NOT NULL, payload jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS agent_backend_observation (
 command uuid NOT NULL REFERENCES agent_backend_plan, ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 100),
 fingerprint text NOT NULL, payload jsonb NOT NULL, PRIMARY KEY(command,ordinal));
CREATE OR REPLACE FUNCTION agent_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'AGENT_IMMUTABLE_FACT'; END $$;
"""


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = psycopg.connect(settings.dsn, autocommit=True, row_factory=dict_row)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *args: object) -> None:
        self.conn.close()

    def initialize(self) -> None:
        # Refuse backend or privileged runtime installations rather than merely choosing another schema.
        role = self.conn.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        tables = self.conn.execute("""SELECT c.relname,pg_get_userbyid(c.relowner) AS owner,current_user AS runtime
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
            AND c.relkind IN ('r','p','v','m','f')""").fetchall()
        allowed = {
            "agent_backend_observation",
            "agent_backend_plan",
            "agent_backend_result",
            "agent_schema",
            "agent_command",
            "agent_model",
            "agent_model_head",
            "agent_session",
            "agent_event",
            "agent_result",
            "agent_revocation",
            "checkpoint_migrations",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
        }
        if (
            role is None
            or any(role.values())
            or any(t["relname"] not in allowed or t["owner"] != t["runtime"] for t in tables)
        ):
            raise Conflict("AGENT_DEDICATED_DATABASE_REQUIRED")
        self.conn.execute("SELECT pg_advisory_lock(hashtextextended('ONLYALPHA_AGENT_SCHEMA',0))")
        try:
            with self.conn.transaction():
                self.conn.execute(SCHEMA)
                for table in (
                    "agent_backend_observation",
                    "agent_backend_plan",
                    "agent_backend_result",
                    "agent_command",
                    "agent_model",
                    "agent_session",
                    "agent_event",
                    "agent_result",
                    "agent_revocation",
                ):
                    self.conn.execute(f"DROP TRIGGER IF EXISTS immutable ON {table}")
                    self.conn.execute(
                        f"CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION agent_immutable()"
                    )
            # The checkpoint library owns checkpoint tables; it never owns the append-only facts above.
            from langgraph.checkpoint.postgres import PostgresSaver

            PostgresSaver(self.conn).setup()
        finally:
            self.conn.execute("SELECT pg_advisory_unlock(hashtextextended('ONLYALPHA_AGENT_SCHEMA',0))")

    @contextmanager
    def session_lock(self, session: str) -> Iterator[None]:
        row = self.conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked", (session,)).fetchone()
        if row is None or not row["locked"]:
            raise Conflict("AGENT_SESSION_BUSY")
        try:
            yield
        finally:
            self.conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (session,))

    @contextmanager
    def command(self, command: str, owner: str, value: Any) -> Iterator[dict[str, Any] | None]:
        intent = hmac.digest(
            self.settings.encryption_key, json.dumps(value, sort_keys=True, ensure_ascii=False).encode(), "sha256"
        ).hex()
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))", (command,))
            old = self.conn.execute("SELECT * FROM agent_command WHERE id=%s", (command,)).fetchone()
            if old and (old["owner"] != owner or old["intent"] != intent):
                raise Conflict("AGENT_COMMAND_CONFLICT")
            if old:
                yield old["outcome"]
            else:
                yield None
                # Business effect and accepted outcome participate in the same transaction.
                self.conn.execute(
                    "INSERT INTO agent_command VALUES(%s,%s,%s,%s)", (command, owner, intent, Jsonb(self.outcome))
                )

    def models(self, owner: str) -> list[Any]:
        return [
            r["payload"]
            for r in self.conn.execute(
                "SELECT m.payload FROM agent_model m JOIN agent_model_head h ON h.revision=m.revision WHERE m.owner=%s ORDER BY m.id",
                (owner,),
            )
        ]

    def configure(self, model_id: str, owner: str, command: str, body: dict[str, Any]) -> Any:
        endpoint(body["base_url"])
        with self.command(command, owner, {"operation": "model", "id": model_id, "body": body}) as old:
            if old is not None:
                return old
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,2))", (model_id,))
            head = self.conn.execute("SELECT * FROM agent_model_head WHERE id=%s", (model_id,)).fetchone()
            if head and head["owner"] != owner:
                raise Missing()
            if (head["revision"] if head else None) != body["expected"]:
                raise Conflict("AGENT_MODEL_CONFLICT")
            payload = {k: v for k, v in body.items() if k not in {"secret", "expected"}}
            payload.update(id=model_id, owner=owner, credential_generation=command, parent=body["expected"])
            revision = digest(payload)
            payload["revision"] = revision
            nonce = os.urandom(12)
            secret = nonce + AESGCM(self.settings.encryption_key).encrypt(
                nonce, body["secret"].encode(), revision.encode()
            )
            self.conn.execute(
                "INSERT INTO agent_model VALUES(%s,%s,%s,%s,%s)", (revision, model_id, owner, Jsonb(payload), secret)
            )
            self.conn.execute(
                "INSERT INTO agent_model_head VALUES(%s,%s,%s) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision",
                (model_id, owner, revision),
            )
            self.outcome = payload
            return payload

    def create(self, sid: str, owner: str, command: str, body: dict[str, Any], workflow: str) -> Any:
        with self.command(command, owner, {"operation": "create", "id": sid, "body": body}) as old:
            if old is not None:
                return self.view(sid, owner, workflow)
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,3))", (owner,))
            count = self.conn.execute("SELECT count(*) AS n FROM agent_session WHERE owner=%s", (owner,)).fetchone()
            if count is None or count["n"] >= 100:
                raise Conflict("AGENT_CAPACITY_REACHED")
            profile = self.conn.execute(
                "SELECT revision FROM agent_model WHERE revision=%s AND owner=%s", (body["model_revision"], owner)
            ).fetchone()
            if not profile:
                raise Missing()
            if self.conn.execute("SELECT 1 FROM agent_session WHERE id=%s", (sid,)).fetchone():
                raise Conflict("AGENT_SESSION_CONFLICT")
            self.conn.execute(
                "INSERT INTO agent_session VALUES(%s,%s,%s,%s,%s)",
                (sid, owner, workflow, body["model_revision"], body["model_call_limit"]),
            )
            self.outcome = {"id": sid, "workflow": workflow}
        return self.view(sid, owner, workflow)

    def session(self, sid: str, owner: str) -> Any:
        row = self.conn.execute("SELECT * FROM agent_session WHERE id=%s AND owner=%s", (sid, owner)).fetchone()
        if not row:
            raise Missing()
        return row

    def view(self, sid: str, owner: str, workflow: str) -> dict[str, Any]:
        s = self.session(sid, owner)
        rows = list(self.conn.execute("SELECT * FROM agent_event WHERE session=%s ORDER BY ordinal", (sid,)))
        messages = []
        status = "READY"
        head = None
        candidate = None
        for i, row in enumerate(rows):
            if row["ordinal"] != i + 1 or digest(row["plan"]) != row["fingerprint"] or row["plan"]["expected"] != head:
                raise Conflict("AGENT_HISTORY_CORRUPT")
            receipt = self.conn.execute(
                "SELECT owner,outcome FROM agent_command WHERE id=%s", (row["command"],)
            ).fetchone()
            if (
                receipt is None
                or receipt["owner"] != owner
                or receipt["outcome"] != {"event": row["fingerprint"]}
                or row["plan"]["session"] != sid
                or row["plan"]["command"] != str(row["command"])
                or row["plan"]["workflow"] != s["workflow"]
                or row["plan"]["model_revision"] != s["model"]
            ):
                raise Conflict("AGENT_HISTORY_CORRUPT")
            head = row["fingerprint"]
            messages.append({"role": "user", "content": row["plan"]["text"]})
            result = self.result(str(row["command"]))
            if result is None or result.get("error") == "MODEL_OUTCOME_UNKNOWN":
                status = "OUTCOME_UNKNOWN"
            elif "error" in result:
                status = "FAILED"
                messages.append({"role": "assistant", "content": result["error"]})
            else:
                status = "READY"
                messages.append({"role": "assistant", "content": result["response"]["message"]})
                candidate = result["response"]["candidate"]
        if s["workflow"] != workflow:
            status = "WORKFLOW_UNAVAILABLE"
        return {
            "id": sid,
            "workflow": s["workflow"],
            "model_revision": s["model"],
            "head": head,
            "consumed": len(rows),
            "model_call_limit": s["budget"],
            "messages": messages,
            "status": status,
            "candidate": candidate,
            "execution_admitted": False,
        }

    def accept_message(self, sid: str, owner: str, command: str, body: dict[str, Any]) -> bool:
        # Caller holds the session advisory lock across acceptance, external I/O and recording.
        with self.command(command, owner, {"operation": "message", "id": sid, "body": body}) as old:
            if old is not None:
                return False
            s = self.session(sid, owner)
            current = self.view(sid, owner, s["workflow"])
            if current["head"] != body["expected"]:
                raise Conflict("AGENT_HEAD_CONFLICT")
            if current["status"] == "OUTCOME_UNKNOWN":
                raise Conflict("AGENT_ORIGINAL_CALL_UNKNOWN")
            if current["consumed"] >= s["budget"]:
                raise Conflict("AGENT_BUDGET_EXHAUSTED")
            profile = self.conn.execute(
                "SELECT payload FROM agent_model WHERE revision=%s",
                (s["model"],),
            ).fetchone()
            if not profile:
                raise Conflict("AGENT_MODEL_BINDING_UNAVAILABLE")
            plan = {
                "session": sid,
                "command": command,
                "expected": body["expected"],
                "text": body["text"],
                "workflow": s["workflow"],
                "model_revision": s["model"],
                "request": {
                    "model": profile["payload"]["model_id"],
                    "messages": [
                        {"role": "system", "content": PROMPT},
                        *current["messages"],
                        {"role": "user", "content": body["text"]},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 2000,
                },
            }
            if len(json.dumps(plan).encode()) > 65536:
                raise Conflict("AGENT_CONTEXT_CAPACITY")
            fp = digest(plan)
            self.outcome = {"event": fp}
            # Deferred FK permits atomically recording event and receipt in either statement order.
            self.conn.execute("SET CONSTRAINTS ALL DEFERRED")
            self.conn.execute(
                "INSERT INTO agent_event VALUES(%s,%s,%s,%s,%s)",
                (command, sid, current["consumed"] + 1, fp, Jsonb(plan)),
            )
        return True

    def plan(self, command: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM agent_event WHERE command=%s", (command,)).fetchone()
        if not row or digest(row["plan"]) != row["fingerprint"]:
            raise Conflict("AGENT_CALL_CORRUPT")
        return cast(dict[str, Any], row["plan"])

    def model_input(self, command: str) -> tuple[Any, str, Any]:
        plan = self.plan(command)
        m = self.conn.execute("SELECT * FROM agent_model WHERE revision=%s", (plan["model_revision"],)).fetchone()
        if m is None:
            raise Conflict("AGENT_MODEL_BINDING_UNAVAILABLE")
        cipher = bytes(m["secret"])
        secret = AESGCM(self.settings.encryption_key).decrypt(cipher[:12], cipher[12:], m["revision"].encode()).decode()
        return m["payload"], secret, plan["request"]

    def result(self, command: str) -> Any:
        row = self.conn.execute("SELECT * FROM agent_result WHERE command=%s", (command,)).fetchone()
        if row and digest(row["payload"]) != row["fingerprint"]:
            raise Conflict("AGENT_RESULT_CORRUPT")
        return row["payload"] if row else None

    def finish(self, command: str, value: dict[str, Any]) -> None:
        if len(json.dumps(value).encode()) > 131072:
            value = {"error": "MODEL_RESPONSE_INVALID"}
        old = self.result(command)
        if old is not None:
            if old != value:
                raise Conflict("AGENT_RESULT_CONFLICT")
            return
        self.conn.execute("INSERT INTO agent_result VALUES(%s,%s,%s)", (command, digest(value), Jsonb(value)))

    def prepare_backend(
        self, sid: str, owner: str, command: str, expected: str, binding: str, context: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        from uuid import UUID

        with self.command(command, owner, {"operation": "stage", "session": sid, "expected": expected}) as old:
            if old is not None:
                return self.backend_plan(command), False
            s = self.session(sid, owner)
            current = self.view(sid, owner, s["workflow"])
            if current["head"] != expected or current["status"] != "READY" or current["candidate"] is None:
                raise Conflict("AGENT_PROPOSAL_HEAD_CONFLICT")
            row = self.conn.execute(
                "SELECT command FROM agent_event WHERE fingerprint=%s AND session=%s", (expected, sid)
            ).fetchone()
            if row is None:
                raise Conflict("AGENT_PROPOSAL_ORIGIN_UNAVAILABLE")
            recorded = self.conn.execute(
                "SELECT fingerprint FROM agent_result WHERE command=%s", (row["command"],)
            ).fetchone()
            if recorded is None:
                raise Conflict("AGENT_PROPOSAL_ORIGIN_UNAVAILABLE")
            backend_command = str(
                UUID(
                    bytes=bytes.fromhex(digest({"agent_command": command, "purpose": "register-factor-proposal"}))[:16],
                    version=4,
                )
            )
            body = {
                "schema_version": 1,
                "origin": {
                    "session_id": sid,
                    "event_fingerprint": expected,
                    "result_fingerprint": recorded["fingerprint"],
                    "workflow_fingerprint": s["workflow"],
                    "model_revision": s["model"],
                },
                "candidate": current["candidate"],
                "expected_draft_fingerprint": context["draft_fingerprint"],
                "expected_display_fingerprint": context["display_fingerprint"],
                "expected_proposal_fingerprint": context["proposal_fingerprint"],
            }
            plan = {
                "schema_version": 1,
                "session": sid,
                "owner": owner,
                "backend_command": backend_command,
                "binding": binding,
                "body": body,
            }
            fp = digest(plan)
            self.outcome = {"backend_plan": fp}
            self.conn.execute(
                "INSERT INTO agent_backend_plan VALUES(%s,%s,%s,%s,%s)",
                (command, sid, backend_command, fp, Jsonb(plan)),
            )
        return plan, True

    def backend_plan(self, command: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT fingerprint,payload FROM agent_backend_plan WHERE command=%s", (command,)
        ).fetchone()
        if row is None or digest(row["payload"]) != row["fingerprint"]:
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        receipt = self.conn.execute("SELECT owner,outcome FROM agent_command WHERE id=%s", (command,)).fetchone()
        if (
            receipt is None
            or receipt["owner"] != row["payload"]["owner"]
            or receipt["outcome"] != {"backend_plan": row["fingerprint"]}
        ):
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        return cast(dict[str, Any], row["payload"])

    def backend_recorded(self, command: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT fingerprint,payload FROM agent_backend_result WHERE command=%s", (command,)
        ).fetchone()
        if row is None:
            return None
        if digest(row["payload"]) != row["fingerprint"]:
            raise Conflict("AGENT_BACKEND_RESULT_CORRUPT")
        self.validate_backend_receipt(command, row["payload"])
        return cast(dict[str, Any], row["payload"])

    def validate_backend_receipt(self, command: str, receipt: dict[str, Any]) -> None:
        plan = self.backend_plan(command)
        if (
            receipt.get("schema_version") != 1
            or receipt.get("command_id") != plan["backend_command"]
            or not isinstance(receipt.get("operation_fingerprint"), str)
            or not isinstance(receipt.get("effect"), dict)
            or not isinstance(receipt["effect"].get("proposal_fingerprint"), str)
        ):
            raise Conflict("AGENT_BACKEND_RECEIPT_INVALID")
        import re

        if (
            set(receipt) != {"schema_version", "command_id", "operation_fingerprint", "effect"}
            or set(receipt["effect"]) != {"proposal_fingerprint"}
            or any(
                re.fullmatch(r"[0-9a-f]{64}", v) is None
                for v in [receipt["operation_fingerprint"], receipt["effect"]["proposal_fingerprint"]]
            )
        ):
            raise Conflict("AGENT_BACKEND_RECEIPT_INVALID")

    def backend_finish(self, command: str, receipt: dict[str, Any]) -> None:
        self.validate_backend_receipt(command, receipt)
        old = self.backend_recorded(command)
        if old is not None:
            if old != receipt:
                raise Conflict("AGENT_BACKEND_RESULT_CONFLICT")
            return
        self.conn.execute(
            "INSERT INTO agent_backend_result VALUES(%s,%s,%s)", (command, digest(receipt), Jsonb(receipt))
        )

    def backend_observation(self, command: str, phase: str, outcome: str) -> None:
        count = self.conn.execute(
            "SELECT count(*) AS n FROM agent_backend_observation WHERE command=%s", (command,)
        ).fetchone()
        if count is None or count["n"] >= 100:
            raise Conflict("AGENT_BACKEND_OBSERVATION_CAPACITY")
        v = {"command": command, "ordinal": count["n"] + 1, "phase": phase, "outcome": outcome}
        self.conn.execute(
            "INSERT INTO agent_backend_observation VALUES(%s,%s,%s,%s)", (command, v["ordinal"], digest(v), Jsonb(v))
        )

    def backend_rejected(self, command: str) -> bool:
        row = self.conn.execute(
            "SELECT fingerprint,payload FROM agent_backend_observation WHERE command=%s AND ordinal=1", (command,)
        ).fetchone()
        if row is not None and digest(row["payload"]) != row["fingerprint"]:
            raise Conflict("AGENT_BACKEND_OBSERVATION_CORRUPT")
        return bool(row and row["payload"]["phase"] == "SUBMIT" and row["payload"]["outcome"] == "REJECTED")
