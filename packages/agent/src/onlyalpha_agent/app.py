"""Versioned A2 Agent API. No Human confirmation, backend submission or Research routes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import UUID4, BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from . import model, workflow
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
        yield

    app = FastAPI(title="OnlyAlpha Agent API", version="1", lifespan=lifespan)

    @app.middleware("http")
    async def bounded_input(request: Request, call_next: Any) -> Any:
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
                or headers.get("sec-fetch-site") not in {None, "none", "same-origin"}
            ):
                raise Denied("AGENT_UNAUTHORIZED")
            p = authenticate(settings.signing_key, headers["authorization"])
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
                accepted = store.accept_message(sid, p.subject, cid, body.model_dump())
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

    @app.put("/api/v1/agent/access/revocations/{token_id}", response_model=RevocationView)
    def revoke(token_id: UUID4, p: Annotated[Principal, Depends(principal)]) -> Any:
        require(p, "access:revoke", True)
        with Store(settings) as store:
            store.conn.execute(
                "INSERT INTO agent_revocation VALUES(%s,%s) ON CONFLICT DO NOTHING", (p.subject, str(token_id))
            )
        return {"revoked": str(token_id)}

    return app
