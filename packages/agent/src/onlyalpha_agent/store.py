"""Agent-owned facts; backend effects and receipts are observed through scoped APIs."""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any, cast
from uuid import UUID

import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import backend
from .config import Settings
from .model import endpoint, validate_response
from .workflow import PROMPT, STUDY_PROMPT, digest


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
CREATE TABLE IF NOT EXISTS agent_session_context (
 session uuid PRIMARY KEY REFERENCES agent_session, parent uuid NOT NULL UNIQUE REFERENCES agent_session,
 fingerprint text NOT NULL, payload jsonb NOT NULL);
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
CREATE UNIQUE INDEX IF NOT EXISTS agent_backend_origin ON agent_backend_plan(session,(payload->'body'->'origin'->>'event_fingerprint'));
CREATE OR REPLACE FUNCTION agent_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'AGENT_IMMUTABLE_FACT'; END $$;
"""


def backend_command_id(command: str, topic: str = "FACTOR") -> str:
    return str(
        UUID(
            bytes=bytes.fromhex(
                digest(
                    {
                        "agent_command": command,
                        "purpose": "register-factor-study" if topic == "STUDY" else "register-factor-proposal",
                    }
                )
            )[:16],
            version=4,
        )
    )


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
            "agent_session_context",
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
                    "agent_session_context",
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

    def intent(self, value: Any) -> str:
        return hmac.digest(
            self.settings.encryption_key, json.dumps(value, sort_keys=True, ensure_ascii=False).encode(), "sha256"
        ).hex()

    @contextmanager
    def command(self, command: str, owner: str, value: Any) -> Iterator[dict[str, Any] | None]:
        intent = self.intent(value)
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))", (command,))
            old = self.conn.execute("SELECT * FROM agent_command WHERE id=%s", (command,)).fetchone()
            if old and old["owner"] == owner and old["outcome"] == {"abandoned": True}:
                raise Conflict("AGENT_COMMAND_ABANDONED")
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

    def observe_command(self, command: str, owner: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT owner,outcome,intent FROM agent_command WHERE id=%s", (command,)).fetchone()
        if row is None:
            return {"status": "UNKNOWN", "outcome": None}
        if row["owner"] != owner:
            raise Missing()
        outcome = row["outcome"]
        if outcome == {"abandoned": True}:
            return {"status": "ABANDONED", "outcome": outcome}
        # An accepted receipt must resolve to its own mandatory effect. External
        # model/backend results are optional: their absence remains UNKNOWN.
        valid = False
        if isinstance(outcome, dict) and set(outcome) == {"event"}:
            plan = self.plan(command)
            session, events = self.history(plan["session"], owner)
            valid = any(
                str(event["command"]) == command and event["fingerprint"] == outcome["event"] for event in events
            )
        elif isinstance(outcome, dict) and set(outcome) == {"backend_plan"}:
            plan = self.backend_plan(command)
            self.session(plan["session"], owner)
            valid = plan["owner"] == owner and digest(plan) == outcome["backend_plan"]
        elif isinstance(outcome, dict) and set(outcome) in ({"id", "workflow"}, {"id", "workflow", "context"}):
            session = self.session(outcome["id"], owner)
            valid = self.creation_outcome(session) == outcome
            expected = self.intent(
                {
                    "operation": "create",
                    "id": outcome["id"],
                    "body": self.creation_body(session),
                }
            )
            receipt = self.conn.execute("SELECT intent FROM agent_command WHERE id=%s", (command,)).fetchone()
            valid = valid and receipt is not None and hmac.compare_digest(receipt["intent"], expected)
        elif isinstance(outcome, dict) and "revision" in outcome:
            profile, _secret = self.model(outcome["revision"], owner)
            valid = profile == outcome and outcome["credential_generation"] == command
        if not valid:
            raise Conflict("AGENT_COMMAND_EFFECT_CORRUPT")
        return {"status": "ACCEPTED", "outcome": outcome}

    def abandon_command(self, command: str, owner: str) -> dict[str, Any]:
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))", (command,))
            outcome = self.observe_command(command, owner)
            if outcome["status"] == "UNKNOWN":
                self.conn.execute(
                    "INSERT INTO agent_command VALUES(%s,%s,%s,%s)",
                    (command, owner, digest({"abandon": command}), Jsonb({"abandoned": True})),
                )
                return {"status": "ABANDONED", "outcome": {"abandoned": True}}
            return outcome

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

    def create(
        self,
        sid: str,
        owner: str,
        command: str,
        body: dict[str, Any],
        workflow: str,
        continuation: dict[str, Any] | None = None,
    ) -> Any:
        source = body.get("continuation")
        with (
            self.session_lock(source["parent_session"]) if source is not None else nullcontext(),
            self.command(command, owner, {"operation": "create", "id": sid, "body": body}) as old,
        ):
            if old is not None:
                return self.view(sid, owner, workflow)
            self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,3))", (owner,))
            count = self.conn.execute("SELECT count(*) AS n FROM agent_session WHERE owner=%s", (owner,)).fetchone()
            if count is None or count["n"] >= 100:
                raise Conflict("AGENT_CAPACITY_REACHED")
            self.model(body["model_revision"], owner)
            context = None
            if body.get("continuation") is not None:
                source = body["continuation"]
                if self.successor(source["parent_session"], owner) is not None:
                    raise Conflict("AGENT_SESSION_CONTINUED")
                parent, events = self.history(source["parent_session"], owner)
                parent_context = self.session_context(source["parent_session"])
                reference = self.view(source["parent_session"], owner, parent["workflow"])["factor_reference"]
                proof = continuation
                request = proof.get("snapshot", {}).get("request", {}) if isinstance(proof, dict) else {}
                if (
                    not events
                    or events[-1]["fingerprint"] != source["parent_head"]
                    or self.pending_backend(source["parent_session"], owner)
                    or any(
                        self.result(str(event["command"])) is None
                        or self.result(str(event["command"])).get("error") == "MODEL_OUTCOME_UNKNOWN"
                        for event in events
                    )
                    or reference is None
                    or reference["fingerprint"] is None
                    or proof is None
                    or proof.get("command_id") != source["backend_command"]
                    or proof.get("schema_version") != 1
                    or digest(proof.get("snapshot")) != proof.get("operation_fingerprint")
                    or proof.get("snapshot", {}).get("command_id") != source["backend_command"]
                    or proof.get("snapshot", {}).get("owner") != owner
                    or proof["snapshot"].get("actor") != "HUMAN"
                    or proof["snapshot"].get("kind") != "CONTINUE_FACTOR_STUDY"
                    or proof["snapshot"].get("effect") != {"continuation_command_id": source["backend_command"]}
                    or request
                    != {
                        "schema_version": 1,
                        "factor_proposal_fingerprint": reference["fingerprint"],
                        "session_id": sid,
                        "workflow_fingerprint": workflow,
                        "model_revision": parent["model"],
                        "source_session_id": source["parent_session"],
                        "source_workflow_fingerprint": parent["workflow"],
                        **(
                            {"source_continuation_command_id": parent_context["input"]["backend_command"]}
                            if parent_context is not None
                            else {}
                        ),
                    }
                    or body["model_revision"] != parent["model"]
                    or body["model_call_limit"] > parent["budget"] - len(events)
                ):
                    raise Conflict("AGENT_CONTINUATION_INVALID")
                context = {"input": source, "proof": proof, "factor_reference": reference}
            if self.conn.execute("SELECT 1 FROM agent_session WHERE id=%s", (sid,)).fetchone():
                raise Conflict("AGENT_SESSION_CONFLICT")
            self.conn.execute(
                "INSERT INTO agent_session VALUES(%s,%s,%s,%s,%s)",
                (sid, owner, workflow, body["model_revision"], body["model_call_limit"]),
            )
            self.outcome = {"id": sid, "workflow": workflow}
            if context is not None:
                pin = digest(context)
                self.conn.execute(
                    "INSERT INTO agent_session_context VALUES(%s,%s,%s,%s)",
                    (sid, body["continuation"]["parent_session"], pin, Jsonb(context)),
                )
                self.outcome["context"] = pin
        return self.view(sid, owner, workflow)

    def session(self, sid: str, owner: str) -> Any:
        row = self.conn.execute("SELECT * FROM agent_session WHERE id=%s AND owner=%s", (sid, owner)).fetchone()
        if not row:
            raise Missing()
        creation = self.conn.execute(
            "SELECT intent,outcome FROM agent_command WHERE owner=%s AND outcome->>'id'=%s AND outcome ? 'workflow'",
            (owner, sid),
        ).fetchall()
        expected = self.intent(
            {
                "operation": "create",
                "id": sid,
                "body": self.creation_body(row),
            }
        )
        if (
            len(creation) != 1
            or creation[0]["outcome"] != self.creation_outcome(row)
            or not hmac.compare_digest(creation[0]["intent"], expected)
        ):
            raise Conflict("AGENT_SESSION_CORRUPT")
        return row

    def session_context(self, sid: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT parent,fingerprint,payload FROM agent_session_context WHERE session=%s", (sid,)
        ).fetchone()
        if row is None:
            return None
        value = row["payload"]
        if (
            digest(value) != row["fingerprint"]
            or value["input"]["parent_session"] != str(row["parent"])
            or str(row["parent"]) == sid
        ):
            raise Conflict("AGENT_CONTINUATION_CORRUPT")
        return cast(dict[str, Any], value)

    def successor(self, sid: str, owner: str) -> str | None:
        rows = self.conn.execute(
            "SELECT session::text AS session FROM agent_session_context WHERE parent=%s LIMIT 2", (sid,)
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise Conflict("AGENT_CONTINUATION_CORRUPT")
        row = rows[0]
        child = self.session(row["session"], owner)
        context = self.session_context(row["session"])
        if context is None or context["input"]["parent_session"] != sid or child["owner"] != owner:
            raise Conflict("AGENT_CONTINUATION_CORRUPT")
        return cast(str, row["session"])

    def creation_body(self, row: Any) -> dict[str, Any]:
        body = {"model_revision": row["model"], "model_call_limit": row["budget"]}
        context = self.session_context(str(row["id"]))
        if context is not None:
            body["continuation"] = context["input"]
        return body

    def creation_outcome(self, row: Any) -> dict[str, Any]:
        outcome = {"id": str(row["id"]), "workflow": row["workflow"]}
        context = self.session_context(str(row["id"]))
        if context is not None:
            outcome["context"] = digest(context)
        return outcome

    def history(self, sid: str, owner: str) -> tuple[Any, list[Any]]:
        session = self.session(sid, owner)
        rows = list(self.conn.execute("SELECT * FROM agent_event WHERE session=%s ORDER BY ordinal", (sid,)))
        head = None
        for i, row in enumerate(rows):
            if row["ordinal"] != i + 1 or digest(row["plan"]) != row["fingerprint"] or row["plan"]["expected"] != head:
                raise Conflict("AGENT_HISTORY_CORRUPT")
            if row["plan"].get("topic", "FACTOR") not in {"FACTOR", "STUDY"}:
                raise Conflict("AGENT_HISTORY_CORRUPT")
            receipt = self.conn.execute(
                "SELECT owner,outcome,intent FROM agent_command WHERE id=%s", (row["command"],)
            ).fetchone()
            body = {"expected": row["plan"]["expected"], "text": row["plan"]["text"]}
            if row["plan"].get("topic", "FACTOR") == "STUDY":
                body.update(topic="STUDY", factor_proposal_fingerprint=row["plan"]["factor_proposal_fingerprint"])
            if (
                receipt is None
                or receipt["owner"] != owner
                or receipt["outcome"] != {"event": row["fingerprint"]}
                or not hmac.compare_digest(
                    receipt["intent"],
                    self.intent(
                        {
                            "operation": "message",
                            "id": sid,
                            "body": body,
                        }
                    ),
                )
                or row["plan"]["session"] != sid
                or row["plan"]["command"] != str(row["command"])
                or row["plan"]["workflow"] != session["workflow"]
                or row["plan"]["model_revision"] != session["model"]
            ):
                raise Conflict("AGENT_HISTORY_CORRUPT")
            head = row["fingerprint"]
        return session, rows

    def conversation(self, sid: str, owner: str) -> dict[str, Any]:
        session, rows = self.history(sid, owner)
        profile, _secret = self.model(session["model"], owner)
        references = {reference["head"]: (plan, reference) for plan, reference in self.backend_references(sid, owner)}
        turns = []
        for row in rows:
            topic = row["plan"].get("topic", "FACTOR")
            turn: dict[str, Any] = {
                "head": row["fingerprint"],
                "topic": topic,
                "user": row["plan"]["text"],
                "assistant": None,
                "status": "OUTCOME_UNKNOWN",
                "candidate": None,
                "study": None,
                "factor_reference": None,
                "study_reference": None,
            }
            result = self.result(str(row["command"]))
            if result is not None:
                if "error" in result:
                    if result["error"] != "MODEL_OUTCOME_UNKNOWN":
                        turn["status"] = "FAILED"
                else:
                    try:
                        response = validate_response(result["response"], topic)
                    except (ValueError, KeyError, TypeError):
                        raise Conflict("AGENT_RESULT_CORRUPT") from None
                    field = "study" if topic == "STUDY" else "candidate"
                    turn.update(status="READY", assistant=response["message"])
                    turn[field] = response[field]
            if row["fingerprint"] in references:
                plan, reference = references[row["fingerprint"]]
                field = "study_reference" if plan.get("topic", "FACTOR") == "STUDY" else "factor_reference"
                turn[field] = reference
            turns.append(turn)
        return {
            "id": sid,
            "head": rows[-1]["fingerprint"] if rows else None,
            "model_revision": session["model"],
            "model": {key: profile[key] for key in ("name", "model_id", "model_version")},
            "turns": turns,
        }

    def view(self, sid: str, owner: str, workflow: str) -> dict[str, Any]:
        s, rows = self.history(sid, owner)
        messages = []
        status = "READY"
        head = None
        candidate = None
        study = None
        topic = "FACTOR"
        for row in rows:
            head = row["fingerprint"]
            candidate = None
            study = None
            topic = row["plan"].get("topic", "FACTOR")
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
                if topic == "STUDY":
                    study = result["response"]["study"]
                else:
                    candidate = result["response"]["candidate"]
        if s["workflow"] != workflow:
            status = "WORKFLOW_UNAVAILABLE"
        context = self.session_context(sid)
        factor_reference = context["factor_reference"] if context is not None else None
        if context is not None and not rows:
            topic = "STUDY"
        study_reference = None
        for plan, reference in self.backend_references(sid, owner):
            if plan.get("topic", "FACTOR") == "STUDY":
                study_reference = reference
            else:
                factor_reference = reference
                study_reference = None
        return {
            "id": sid,
            "factor_reference": factor_reference,
            "study_reference": study_reference,
            "topic": topic,
            "workflow": s["workflow"],
            "current_workflow": workflow,
            "model_revision": s["model"],
            "head": head,
            "consumed": len(rows),
            "model_call_limit": s["budget"],
            "messages": messages,
            "status": status,
            "candidate": candidate,
            "study": study,
            "execution_admitted": False,
            "continuation": context["input"] if context is not None else None,
            "successor": self.successor(sid, owner),
        }

    def accept_message(
        self,
        sid: str,
        owner: str,
        command: str,
        body: dict[str, Any],
        study_context: dict[str, Any] | None = None,
        backend_binding: str | None = None,
    ) -> bool:
        # Caller holds the session advisory lock across acceptance, external I/O and recording.
        with self.command(command, owner, {"operation": "message", "id": sid, "body": body}) as old:
            if old is not None:
                return False
            s = self.session(sid, owner)
            current = self.view(sid, owner, s["workflow"])
            if current["successor"] is not None:
                raise Conflict("AGENT_SESSION_CONTINUED")
            if current["head"] != body["expected"]:
                raise Conflict("AGENT_HEAD_CONFLICT")
            if current["status"] == "OUTCOME_UNKNOWN":
                raise Conflict("AGENT_ORIGINAL_CALL_UNKNOWN")
            if self.pending_backend(sid, owner):
                raise Conflict("AGENT_BACKEND_OUTCOME_UNKNOWN")
            if current["consumed"] >= s["budget"]:
                raise Conflict("AGENT_BUDGET_EXHAUSTED")
            topic = body.get("topic", "FACTOR")
            if topic not in {"FACTOR", "STUDY"}:
                raise Conflict("AGENT_TOPIC_INVALID")
            if topic == "STUDY":
                try:
                    backend.validate_study_context(study_context, owner, body["factor_proposal_fingerprint"])
                except (ValueError, KeyError):
                    raise Conflict("AGENT_STUDY_CONTEXT_INVALID") from None
                if (
                    backend_binding is None
                    or len(backend_binding) != 64
                    or any(c not in "0123456789abcdef" for c in backend_binding)
                ):
                    raise Conflict("AGENT_BACKEND_BINDING_UNAVAILABLE")
                reference = current["factor_reference"]
                if reference is None or reference["fingerprint"] != body["factor_proposal_fingerprint"]:
                    raise Conflict("AGENT_FACTOR_REFERENCE_CONFLICT")
            profile, _secret = self.model(s["model"], owner)
            plan = {
                "session": sid,
                "command": command,
                "expected": body["expected"],
                "text": body["text"],
                "workflow": s["workflow"],
                "model_revision": s["model"],
                "request": {
                    "model": profile["model_id"],
                    "messages": [
                        {"role": "system", "content": STUDY_PROMPT if topic == "STUDY" else PROMPT},
                        *(
                            [
                                {
                                    "role": "system",
                                    "content": json.dumps(
                                        study_context, ensure_ascii=False, sort_keys=True, allow_nan=False
                                    ),
                                }
                            ]
                            if topic == "STUDY"
                            else []
                        ),
                        *current["messages"],
                        {"role": "user", "content": body["text"]},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 2000,
                },
            }
            if topic == "STUDY":
                plan.update(
                    topic=topic,
                    factor_proposal_fingerprint=body["factor_proposal_fingerprint"],
                    study_context=study_context,
                    backend_binding=backend_binding,
                )
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
        if (
            not row
            or digest(row["plan"]) != row["fingerprint"]
            or row["plan"].get("session") != str(row["session"])
            or row["plan"].get("command") != str(row["command"])
        ):
            raise Conflict("AGENT_CALL_CORRUPT")
        return cast(dict[str, Any], row["plan"])

    def model(self, revision: str, owner: str) -> tuple[dict[str, Any], str]:
        from cryptography.exceptions import InvalidTag

        row = self.conn.execute("SELECT * FROM agent_model WHERE revision=%s", (revision,)).fetchone()
        if row is None:
            raise Conflict("AGENT_MODEL_BINDING_UNAVAILABLE")
        payload = row["payload"]
        content = {k: v for k, v in payload.items() if k != "revision"}
        if (
            row["owner"] != owner
            or payload.get("owner") != owner
            or payload.get("id") != str(row["id"])
            or payload.get("revision") != revision
            or digest(content) != revision
        ):
            raise Conflict("AGENT_MODEL_CORRUPT")
        try:
            cipher = bytes(row["secret"])
            secret = AESGCM(self.settings.encryption_key).decrypt(cipher[:12], cipher[12:], revision.encode()).decode()
            body = {k: payload[k] for k in ("name", "base_url", "model_id", "model_version")}
            body.update(expected=payload["parent"], secret=secret)
            receipt = self.conn.execute(
                "SELECT owner,intent,outcome FROM agent_command WHERE id=%s", (payload["credential_generation"],)
            ).fetchone()
            if (
                receipt is None
                or receipt["owner"] != owner
                or receipt["outcome"] != payload
                or not hmac.compare_digest(
                    receipt["intent"], self.intent({"operation": "model", "id": payload["id"], "body": body})
                )
            ):
                raise Conflict("AGENT_MODEL_CORRUPT")
        except (InvalidTag, ValueError, KeyError, TypeError):
            raise Conflict("AGENT_MODEL_CORRUPT") from None
        return cast(dict[str, Any], payload), secret

    def model_input(self, command: str) -> tuple[Any, str, Any]:
        plan = self.plan(command)
        row = self.conn.execute("SELECT owner FROM agent_session WHERE id=%s", (plan["session"],)).fetchone()
        if row is None:
            raise Conflict("AGENT_CALL_CORRUPT")
        session, _events = self.history(plan["session"], row["owner"])
        profile, secret = self.model(session["model"], row["owner"])
        return profile, secret, plan["request"]

    def result(self, command: str) -> Any:
        row = self.conn.execute("SELECT * FROM agent_result WHERE command=%s", (command,)).fetchone()
        if row and digest(row["payload"]) != row["fingerprint"]:
            raise Conflict("AGENT_RESULT_CORRUPT")
        return row["payload"] if row else None

    def finish(self, command: str, value: dict[str, Any]) -> None:
        plan = self.plan(command)
        if plan.get("topic", "FACTOR") == "STUDY" and "response" in value:
            try:
                response = validate_response(value["response"], "STUDY")
                if response["study"] is not None:
                    selection = {k: v for k, v in response["study"]["source"].items() if k != "instrument_id"}
                    if selection not in plan["study_context"]["sources"]:
                        raise ValueError("unavailable source selection")
            except (ValueError, TypeError, KeyError):
                value = {"error": "MODEL_RESPONSE_INVALID"}
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
        with self.command(command, owner, {"operation": "stage", "session": sid, "expected": expected}) as old:
            if old is not None:
                return self.backend_plan(command), False
            s = self.session(sid, owner)
            current = self.view(sid, owner, s["workflow"])
            topic = current["topic"]
            if current["successor"] is not None:
                raise Conflict("AGENT_SESSION_CONTINUED")
            content = current["study"] if topic == "STUDY" else current["candidate"]
            if current["head"] != expected or current["status"] != "READY" or content is None:
                raise Conflict("AGENT_PROPOSAL_HEAD_CONFLICT")
            if self.pending_backend(sid, owner):
                raise Conflict("AGENT_BACKEND_OUTCOME_UNKNOWN")
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
            source = self.plan(str(row["command"]))
            backend_command = backend_command_id(command, topic)
            body = {
                "schema_version": 1,
                "origin": {
                    "session_id": sid,
                    "event_fingerprint": expected,
                    "result_fingerprint": recorded["fingerprint"],
                    "workflow_fingerprint": s["workflow"],
                    "model_revision": s["model"],
                },
            }
            if topic == "STUDY":
                if context != source["study_context"] or binding != source["backend_binding"]:
                    raise Conflict("AGENT_BACKEND_BINDING_UNAVAILABLE")
                body.update(
                    factor_proposal_fingerprint=source["factor_proposal_fingerprint"],
                    expected_study_fingerprint=context["study_proposal_fingerprint"],
                    advice=content,
                )
                continuation = self.session_context(sid)
                if continuation is not None:
                    body["continuation_command_id"] = continuation["input"]["backend_command"]
            else:
                body.update(
                    candidate=content,
                    expected_draft_fingerprint=context["draft_fingerprint"],
                    expected_display_fingerprint=context["display_fingerprint"],
                    expected_proposal_fingerprint=context["proposal_fingerprint"],
                )
            plan = {
                "schema_version": 1,
                "session": sid,
                "owner": owner,
                "backend_command": backend_command,
                "binding": binding,
                "body": body,
            }
            if topic == "STUDY":
                plan["topic"] = topic
            fp = digest(plan)
            self.outcome = {"backend_plan": fp}
            self.conn.execute(
                "INSERT INTO agent_backend_plan VALUES(%s,%s,%s,%s,%s)",
                (command, sid, backend_command, fp, Jsonb(plan)),
            )
        return plan, True

    def pending_backend(self, sid: str, owner: str) -> bool:
        # Even a refusal cannot prove the original submission had no effect.
        return any(
            reference["fingerprint"] is None and not reference.get("abandoned", False)
            for _plan, reference in self.backend_references(sid, owner)
        )

    def backend_references(self, sid: str, owner: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        _session, events = self.history(sid, owner)
        plans = self.conn.execute("SELECT command FROM agent_backend_plan WHERE session=%s", (sid,)).fetchall()
        intents = [
            self.intent({"operation": "stage", "session": sid, "expected": event["fingerprint"]}) for event in events
        ]
        receipts = self.conn.execute(
            "SELECT id FROM agent_command WHERE owner=%s AND intent=ANY(%s)", (owner, intents)
        ).fetchall()
        if {str(row["command"]) for row in plans} != {str(row["id"]) for row in receipts}:
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        references = []
        for row in plans:
            command = str(row["command"])
            plan = self.backend_plan(command)
            if plan["owner"] != owner or plan["session"] != sid:
                raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
            receipt = self.backend_recorded(command)
            references.append(
                (
                    plan,
                    {
                        "command": command,
                        "head": plan["body"]["origin"]["event_fingerprint"],
                        "fingerprint": receipt["effect"].get("proposal_fingerprint") if receipt else None,
                        "abandoned": bool(receipt and receipt["effect"] == {"registration_abandoned": True}),
                    },
                )
            )
        positions = {event["fingerprint"]: event["ordinal"] for event in events}
        if len({reference["head"] for _plan, reference in references}) != len(references):
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        return sorted(references, key=lambda item: positions[item[1]["head"]])

    def backend_plan(self, command: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM agent_backend_plan WHERE command=%s", (command,)).fetchone()
        if (
            row is None
            or digest(row["payload"]) != row["fingerprint"]
            or row["payload"].get("session") != str(row["session"])
            or row["payload"].get("backend_command") != str(row["backend_command"])
        ):
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        receipt = self.conn.execute("SELECT owner,outcome,intent FROM agent_command WHERE id=%s", (command,)).fetchone()
        if (
            receipt is None
            or receipt["owner"] != row["payload"]["owner"]
            or receipt["outcome"] != {"backend_plan": row["fingerprint"]}
        ):
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        plan = row["payload"]
        session, events = self.history(plan["session"], plan["owner"])
        origin = plan["body"]["origin"]
        topic = plan.get("topic", "FACTOR")
        if not hmac.compare_digest(
            receipt["intent"],
            self.intent({"operation": "stage", "session": plan["session"], "expected": origin["event_fingerprint"]}),
        ) or plan["backend_command"] != backend_command_id(command, topic):
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        source = next((event for event in events if event["fingerprint"] == origin["event_fingerprint"]), None)
        if source is None:
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        result = self.conn.execute("SELECT * FROM agent_result WHERE command=%s", (source["command"],)).fetchone()
        if (
            origin["session_id"] != plan["session"]
            or origin["workflow_fingerprint"] != session["workflow"]
            or origin["model_revision"] != session["model"]
            or result is None
            or result["fingerprint"] != origin["result_fingerprint"]
            or digest(result["payload"]) != result["fingerprint"]
            or topic not in {"FACTOR", "STUDY"}
            or source["plan"].get("topic", "FACTOR") != topic
            or result["payload"].get("response", {}).get("study" if topic == "STUDY" else "candidate")
            != plan["body"]["advice" if topic == "STUDY" else "candidate"]
        ):
            raise Conflict("AGENT_BACKEND_PLAN_CORRUPT")
        if topic == "STUDY":
            model_plan = source["plan"]
            expected = {
                "schema_version": 1,
                "origin": origin,
                "factor_proposal_fingerprint": model_plan["factor_proposal_fingerprint"],
                "expected_study_fingerprint": model_plan["study_context"]["study_proposal_fingerprint"],
                "advice": result["payload"]["response"]["study"],
            }
            continuation = self.session_context(plan["session"])
            if continuation is not None:
                expected["continuation_command_id"] = continuation["input"]["backend_command"]
            if plan["body"] != expected or plan["binding"] != model_plan["backend_binding"]:
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
            or not (
                isinstance(receipt["effect"].get("proposal_fingerprint"), str)
                or plan.get("topic") == "STUDY"
                and set(receipt["effect"]) == {"registration_abandoned"}
                and receipt["effect"]["registration_abandoned"] is True
            )
        ):
            raise Conflict("AGENT_BACKEND_RECEIPT_INVALID")
        import re

        if (
            set(receipt) != {"schema_version", "command_id", "operation_fingerprint", "effect"}
            or set(receipt["effect"]) not in ({"proposal_fingerprint"}, {"registration_abandoned"})
            or any(
                re.fullmatch(r"[0-9a-f]{64}", v) is None
                for v in [
                    receipt["operation_fingerprint"],
                    *(
                        [receipt["effect"]["proposal_fingerprint"]]
                        if "proposal_fingerprint" in receipt["effect"]
                        else []
                    ),
                ]
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
