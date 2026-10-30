"""Versioned Agent API with scoped proposal staging, never Human approval or Research execution."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator
from starlette.types import ASGIApp, Receive, Scope, Send

from . import backend, model, workflow
from .config import Settings
from .security import Denied, Principal, authenticate
from .store import Conflict, Missing, Store


class BoundedBody:
    """Bound received bytes before JSON parsing or body buffering."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD"}:
            await self.app(scope, receive, send)
            return
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 16384:
                await JSONResponse({"error": "AGENT_INPUT_TOO_LARGE"}, status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Any:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelInput(Closed):
    expected: str | None
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2048)
    model_id: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=200)
    secret: str = Field(min_length=1, max_length=8192, repr=False)


class SessionInput(Closed):
    model_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_call_limit: int = Field(ge=1, le=100)


class MessageInput(Closed):
    expected: str | None
    text: str = Field(min_length=1, max_length=8000)
    topic: Literal["FACTOR", "STUDY"] = "FACTOR"
    factor_proposal_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def topic_binding(self) -> "MessageInput":
        if (self.topic == "STUDY") != (self.factor_proposal_fingerprint is not None):
            raise ValueError("Study messages require an exact Factor reference")
        return self


class ProposalInput(Closed):
    expected: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackendProposalView(Closed):
    status: Literal["REGISTERED", "OUTCOME_UNKNOWN", "BINDING_UNAVAILABLE", "REJECTED"]
    backend_command: str
    receipt: dict[str, Any] | None


class BackendObservationView(Closed):
    backend_command: str
    backend_snapshot: dict[str, Any]


class ModelView(Closed):
    id: str
    owner: str
    name: str
    base_url: str
    model_id: str
    model_version: str
    credential_generation: str
    parent: str | None
    revision: str


class ModelsView(Closed):
    items: list[ModelView]


class ChatMessage(Closed):
    role: Literal["user", "assistant"]
    content: str


class ProposalReference(Closed):
    command: str
    head: str
    fingerprint: str | None


class CommandView(Closed):
    status: Literal["UNKNOWN", "ACCEPTED", "ABANDONED"]
    outcome: dict[str, Any] | None


class SessionView(Closed):
    id: str
    workflow: str
    model_revision: str
    head: str | None
    consumed: int
    model_call_limit: int
    messages: list[ChatMessage]
    status: Literal["READY", "FAILED", "OUTCOME_UNKNOWN", "WORKFLOW_UNAVAILABLE"]
    candidate: dict[str, Any] | None
    factor_reference: ProposalReference | None
    study_reference: ProposalReference | None
    topic: Literal["FACTOR", "STUDY"]
    study: dict[str, Any] | None
    execution_admitted: Literal[False]


class SessionsView(Closed):
    items: list[SessionView]


class RevocationView(Closed):
    revoked: str


class HealthView(Closed):
    status: Literal["ALIVE"]


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with Store(settings) as store:
            store.initialize()
        app.state.workflow = workflow.current_identity()
        if settings.expected_workflow is not None and app.state.workflow != settings.expected_workflow:
            raise Conflict("AGENT_INSTALLATION_BINDING_UNAVAILABLE")
        yield

    app = FastAPI(title="OnlyAlpha Agent API", version="1", lifespan=lifespan)

    @app.middleware("http")
    async def bounded_input(request: Request, call_next: Any) -> Any:
        if settings.contained_peer is not None and (
            request.client is None
            or request.client.host not in {"127.0.0.1", settings.contained_peer}
            or request.headers.getlist("host") != ["127.0.0.1:5174"]
        ):
            return JSONResponse({"error": "AGENT_TRANSPORT_DENIED"}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            raw = await request.body()
            if len(raw) > 16384:
                return JSONResponse({"error": "AGENT_INPUT_TOO_LARGE"}, status_code=413)
            if raw:
                try:
                    model.strict_json(raw)
                except (ValueError, UnicodeError, RecursionError):
                    return JSONResponse({"error": "AGENT_INPUT_INVALID"}, status_code=400)
        return await call_next(request)

    app.add_middleware(BoundedBody)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "AGENT_INPUT_INVALID"}, status_code=422)

    @app.exception_handler(Conflict)
    async def conflict(request: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=409)

    @app.exception_handler(Missing)
    async def missing(request: Request, exc: Missing) -> JSONResponse:
        return JSONResponse({"error": "AGENT_NOT_FOUND"}, status_code=404)

    @app.exception_handler(psycopg.Error)
    async def unavailable(request: Request, exc: psycopg.Error) -> JSONResponse:
        return JSONResponse({"error": "AGENT_STORAGE_UNAVAILABLE"}, status_code=503)

    bearer = HTTPBearer(auto_error=False)

    def principal(
        request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ) -> Principal:
        headers = request.headers
        try:
            if (
                len(headers.getlist("authorization")) != 1
                or "cookie" in headers
                or any(k in {"forwarded", "x-user"} or k.startswith("x-forwarded-") for k in headers)
                or headers.get("origin") not in {None, settings.origin}
                or headers.get("sec-fetch-site") not in {None, "none", "same-origin", "same-site", "cross-site"}
                or headers.get("sec-fetch-site") in {"same-site", "cross-site"}
                and headers.get("origin") != settings.origin
            ):
                raise Denied("AGENT_UNAUTHORIZED")
            p = authenticate(
                settings.signing_key, headers["authorization"], browser_issuer_key=settings.browser_issuer_key
            )
            with Store(settings) as store:
                if store.conn.execute(
                    "SELECT 1 FROM agent_revocation WHERE owner=%s AND token_id=%s", (p.subject, p.token_id)
                ).fetchone():
                    raise Denied("AGENT_UNAUTHORIZED")
            return p
        except Denied as error:
            raise HTTPException(401, str(error)) from error

    def require(p: Principal, scope: str, human: bool = False) -> None:
        try:
            p.require(scope, human=human)
        except Denied as error:
            raise HTTPException(403, str(error)) from error

    def command(request: Request) -> str:
        values = request.headers.getlist("idempotency-key")
        try:
            if len(values) != 1 or str(UUID(values[0], version=4)) != values[0]:
                raise ValueError
            return values[0]
        except ValueError as error:
            raise HTTPException(400, "AGENT_COMMAND_ID_REQUIRED") from error

    @app.get("/api/v1/agent/health", response_model=HealthView)
    def health() -> Any:
        return {"status": "ALIVE"}

    @app.get("/api/v1/agent/commands/{cid}", response_model=CommandView)
    def observe(cid: UUID4, p: Annotated[Principal, Depends(principal)]) -> Any:
        require(p, "chat:read")
        with Store(settings) as store:
            return store.observe_command(str(cid), p.subject)

    @app.post("/api/v1/agent/commands/{cid}/abandon", response_model=CommandView)
    def abandon(cid: UUID4, p: Annotated[Principal, Depends(principal)]) -> Any:
        require(p, "chat:write", True)
        with Store(settings) as store:
            return store.abandon_command(str(cid), p.subject)

    @app.get("/api/v1/agent/models", response_model=ModelsView)
    def models(p: Annotated[Principal, Depends(principal)]) -> Any:
        require(p, "chat:read")
        with Store(settings) as store:
            return {"items": store.models(p.subject)}

    @app.put("/api/v1/agent/models/{mid}", response_model=ModelView)
    def configure(
        mid: UUID4,
        body: ModelInput,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        p: Annotated[Principal, Depends(principal)],
    ) -> Any:
        require(p, "model:write", True)
        try:
            model.endpoint(body.base_url)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        with Store(settings) as store:
            return store.configure(str(mid), p.subject, command(request), body.model_dump())

    @app.put("/api/v1/agent/sessions/{sid}", response_model=SessionView)
    def create(
        sid: UUID4,
        body: SessionInput,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        p: Annotated[Principal, Depends(principal)],
    ) -> Any:
        require(p, "chat:write", True)
        with Store(settings) as store:
            return store.create(str(sid), p.subject, command(request), body.model_dump(), app.state.workflow)

    @app.get("/api/v1/agent/sessions", response_model=SessionsView)
    def sessions(p: Annotated[Principal, Depends(principal)]) -> Any:
        require(p, "chat:read")
        with Store(settings) as store:
            ids = store.conn.execute(
                "SELECT id FROM agent_session WHERE owner=%s ORDER BY id LIMIT 101", (p.subject,)
            ).fetchall()
            if len(ids) > 100:
                raise Conflict("AGENT_CAPACITY_REACHED")
            return {"items": [store.view(str(s["id"]), p.subject, app.state.workflow) for s in ids]}

    @app.get("/api/v1/agent/sessions/{sid}", response_model=SessionView)
    def read(sid: UUID4, p: Annotated[Principal, Depends(principal)]) -> Any:
        require(p, "chat:read")
        with Store(settings) as store:
            return store.view(str(sid), p.subject, app.state.workflow)

    def turn(sid: str, p: Principal, cid: str | None, body: MessageInput | None) -> Any:
        require(p, "chat:write", True)
        with Store(settings) as store, store.session_lock(sid):
            s = store.view(sid, p.subject, app.state.workflow)
            if s["status"] == "WORKFLOW_UNAVAILABLE":
                return s
            accepted = False
            if cid is not None and body is not None:
                context = None
                binding = None
                recorded = store.conn.execute("SELECT 1 FROM agent_command WHERE id=%s", (cid,)).fetchone()
                if body.topic == "STUDY" and recorded is None:
                    if settings.backend_url is None or settings.backend_credential is None:
                        raise HTTPException(503, "AGENT_BACKEND_NOT_CONFIGURED")
                    connection = backend.Connection(settings.backend_url, settings.backend_credential)
                    try:
                        context = backend.request(
                            connection, "GET", "/api/v2/factor-study-context/" + str(body.factor_proposal_fingerprint)
                        )
                        if context.get("owner") != p.subject:
                            raise HTTPException(403, "AGENT_BACKEND_OWNER_MISMATCH")
                        backend.validate_study_context(context, p.subject, str(body.factor_proposal_fingerprint))
                    except (backend.Unknown, backend.Rejected, ValueError) as error:
                        raise HTTPException(503, "AGENT_STUDY_CONTEXT_UNAVAILABLE") from error
                    binding = connection.fingerprint()
                message = (
                    body.model_dump()
                    if body.topic == "STUDY"
                    else body.model_dump(exclude={"topic", "factor_proposal_fingerprint"})
                )
                accepted = store.accept_message(sid, p.subject, cid, message, context, binding)
                if not accepted and store.result(cid) is None:
                    return store.view(sid, p.subject, app.state.workflow)
            else:
                last = store.conn.execute(
                    "SELECT command FROM agent_event WHERE session=%s ORDER BY ordinal DESC LIMIT 1", (sid,)
                ).fetchone()
                if last is None or store.result(str(last["command"])) is None:
                    return s
                cid = str(last["command"])

            def invoke(plan: Any) -> Any:
                profile, secret, request = store.model_input(str(cid))
                if plan.get("topic", "FACTOR") == "STUDY":
                    return model.invoke(profile, secret, request, "STUDY")
                return model.invoke(profile, secret, request)

            graph = workflow.graph(store, str(cid), invoke if accepted else None, PostgresSaver(store.conn))
            graph.invoke(
                {"session": sid, "command": str(cid), "outcome": {}},
                {"configurable": {"thread_id": sid}},
                durability="sync",
            )
            return store.view(sid, p.subject, app.state.workflow)

    @app.post("/api/v1/agent/sessions/{sid}/messages", response_model=SessionView)
    def message(
        sid: UUID4,
        body: MessageInput,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        p: Annotated[Principal, Depends(principal)],
    ) -> Any:
        return turn(str(sid), p, command(request), body)

    @app.post("/api/v1/agent/sessions/{sid}/resume", response_model=SessionView)
    def resume(sid: UUID4, p: Annotated[Principal, Depends(principal)]) -> Any:
        return turn(str(sid), p, None, None)

    @app.post("/api/v1/agent/sessions/{sid}/proposals", response_model=BackendProposalView)
    def stage_proposal(
        sid: UUID4,
        body: ProposalInput,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        p: Annotated[Principal, Depends(principal)],
    ) -> Any:
        return stage(str(sid), body.expected, command(request), p, True)

    @app.post("/api/v1/agent/sessions/{sid}/proposals/{cid}/resume", response_model=BackendProposalView)
    def recover_proposal(sid: UUID4, cid: UUID4, p: Annotated[Principal, Depends(principal)]) -> Any:
        require(p, "chat:write", True)
        with Store(settings) as store:
            plan = store.backend_plan(str(cid))
            if plan["owner"] != p.subject or plan["session"] != str(sid):
                raise HTTPException(404, "AGENT_NOT_FOUND")
        return stage(str(sid), plan["body"]["origin"]["event_fingerprint"], str(cid), p, False)

    def stage(sid: str, expected: str, cid: str, p: Principal, allow_new: bool) -> Any:
        require(p, "chat:write", True)
        if settings.backend_url is None or settings.backend_credential is None:
            raise HTTPException(503, "AGENT_BACKEND_NOT_CONFIGURED")
        connection = backend.Connection(settings.backend_url, settings.backend_credential)
        with Store(settings) as store, store.session_lock(str(sid)):
            current = store.view(str(sid), p.subject, app.state.workflow)
            if current["status"] == "WORKFLOW_UNAVAILABLE":
                raise HTTPException(409, "AGENT_WORKFLOW_UNAVAILABLE")
            old = store.conn.execute("SELECT 1 FROM agent_backend_plan WHERE command=%s", (cid,)).fetchone()
            if old is None:
                if not allow_new:
                    raise HTTPException(409, "AGENT_BACKEND_OUTCOME_UNKNOWN")
                if current["topic"] == "STUDY":
                    row = store.conn.execute(
                        "SELECT command FROM agent_event WHERE session=%s AND fingerprint=%s", (sid, expected)
                    ).fetchone()
                    if row is None or current["head"] != expected:
                        raise Conflict("AGENT_PROPOSAL_HEAD_CONFLICT")
                    source = store.plan(str(row["command"]))
                    if source["backend_binding"] != connection.fingerprint():
                        raise HTTPException(409, "AGENT_BACKEND_BINDING_UNAVAILABLE")
                    context = source["study_context"]
                else:
                    try:
                        context = backend.request(connection, "GET", "/api/v2/factor-proposal-context/" + str(sid))
                    except (backend.Unknown, backend.Rejected) as error:
                        raise HTTPException(503, "AGENT_BACKEND_CONTEXT_UNAVAILABLE") from error
                if context.get("owner") != p.subject:
                    raise HTTPException(403, "AGENT_BACKEND_OWNER_MISMATCH")
            else:
                context = {}
            plan, accepted = store.prepare_backend(
                str(sid), p.subject, cid, expected, connection.fingerprint(), context
            )
            result = {"status": "OUTCOME_UNKNOWN", "backend_command": plan["backend_command"], "receipt": None}
            if plan["binding"] != connection.fingerprint():
                return {**result, "status": "BINDING_UNAVAILABLE"}
            if store.backend_rejected(cid):
                return {**result, "status": "REJECTED"}
            stored = store.backend_recorded(cid)
            if stored is not None:
                checkpoint_proposal(store, str(sid), cid)
                return {**result, "status": "REGISTERED", "receipt": stored}
            family = "factor-studies" if plan.get("topic", "FACTOR") == "STUDY" else "factor-proposals"
            try:
                if accepted:
                    receipt = backend.request(
                        connection, "POST", "/api/v2/" + family, plan["body"], plan["backend_command"]
                    )
                else:
                    receipt = backend.request(
                        connection, "GET", "/api/v2/" + family + "/commands/" + plan["backend_command"]
                    )
                try:
                    store.backend_finish(cid, receipt)
                except Conflict as error:
                    if str(error) != "AGENT_BACKEND_RECEIPT_INVALID":
                        raise
                    store.backend_observation(cid, "SUBMIT" if accepted else "QUERY", "INVALID_RESPONSE")
                    return result
                checkpoint_proposal(store, str(sid), cid)
                return {**result, "status": "REGISTERED", "receipt": receipt}
            except backend.Unknown:
                store.backend_observation(cid, "SUBMIT" if accepted else "QUERY", "UNKNOWN")
                return result
            except backend.Rejected:
                store.backend_observation(cid, "SUBMIT" if accepted else "QUERY", "REJECTED")
                # A failed observation cannot prove that the original submission had no effect.
                return {**result, "status": "REJECTED" if accepted else "OUTCOME_UNKNOWN"}

    def checkpoint_proposal(store: Store, sid: str, cid: str) -> None:
        # Durable backend receipts precede this recoverable cursor. This graph cannot submit effects.
        workflow.proposal_graph(store, cid, PostgresSaver(store.conn)).invoke(
            {"session": sid, "command": cid, "outcome": {}},
            {"configurable": {"thread_id": sid + "/proposal/" + cid}},
            durability="sync",
        )

    @app.get("/api/v1/agent/sessions/{sid}/proposals/{cid}", response_model=BackendObservationView)
    def proposal_status(sid: UUID4, cid: UUID4, p: Annotated[Principal, Depends(principal)]) -> dict[str, Any]:
        require(p, "chat:read")
        with Store(settings) as store:
            store.session(str(sid), p.subject)
            plan = store.backend_plan(str(cid))
            if plan["owner"] != p.subject or plan["session"] != str(sid):
                raise HTTPException(404, "AGENT_NOT_FOUND")
            if settings.backend_url is None or settings.backend_credential is None:
                raise HTTPException(503, "AGENT_BACKEND_NOT_CONFIGURED")
            connection = backend.Connection(settings.backend_url, settings.backend_credential)
            if connection.fingerprint() != plan["binding"]:
                raise HTTPException(409, "AGENT_BACKEND_BINDING_UNAVAILABLE")
            receipt = store.backend_recorded(str(cid))
            if receipt is None:
                raise HTTPException(409, "AGENT_BACKEND_OUTCOME_UNKNOWN")
            fp = receipt["effect"]["proposal_fingerprint"]
            family = "factor-studies" if plan.get("topic", "FACTOR") == "STUDY" else "factor-proposals"
            try:
                view = backend.request(connection, "GET", "/api/v2/" + family + "/" + fp)
                if (
                    view.get("fingerprint") != fp
                    or view.get("snapshot", {}).get("owner") != p.subject
                    or type(view.get("is_current")) is not bool
                ):
                    raise backend.Unknown()
            except (backend.Unknown, backend.Rejected) as error:
                raise HTTPException(503, "AGENT_BACKEND_OBSERVATION_UNAVAILABLE") from error
            return {"backend_command": plan["backend_command"], "backend_snapshot": view}

    @app.put("/api/v1/agent/access/revocations/{token_id}", response_model=RevocationView)
    def revoke(token_id: UUID4, p: Annotated[Principal, Depends(principal)]) -> Any:
        require(p, "access:revoke", True)
        with Store(settings) as store:
            store.conn.execute(
                "INSERT INTO agent_revocation VALUES(%s,%s) ON CONFLICT DO NOTHING", (p.subject, str(token_id))
            )
        return {"revoked": str(token_id)}

    return app
