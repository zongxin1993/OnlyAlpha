# OnlyAlpha Agent

Independent Python 3.12 / LangGraph service. The Shipping C2 Factor Research page calls this service for model settings/chat and calls backend directly for Human confirmation. A2 chat-session/call IDs identify interaction provenance, not ADR 0123 Research Brief/Session/Decision identities; they cannot be submitted as those formal facts. Agent chat/proposals are unadmitted content, never Factor acceptance, Research evidence or trading authority. No Research, Generation, backend confirmation or LIVE endpoints exist here.

## Installation and startup

`packages/agent/pyproject.toml` owns the Agent distribution version. The repository `uv.lock` is the only dependency resolution authority. Build/install the Agent package and its selected locked closure, not the root OnlyAlpha distribution:

```sh
uv export --locked --package onlyalpha-agent --no-dev --no-emit-workspace --output-file agent-requirements.txt
uv build --locked --package onlyalpha-agent --wheel --out-dir dist
uv venv /chosen/agent-env --python 3.12
uv pip install --python /chosen/agent-env/bin/python --require-hashes -r agent-requirements.txt
uv pip install --python /chosen/agent-env/bin/python --no-deps dist/onlyalpha_agent-0.1.0-py3-none-any.whl
```

Installation is an operator/build action, never startup behavior. The existing `scripts/release_sources.py agent EXACT_COMMIT OUTPUT` exports immutable owned source with the exact root lock/build context. Build from that selected context; missing inputs fail closed. No dependency on `onlyalpha`, backend Python business modules or Rust internals is permitted. Native algorithm installations remain separate.

Set `ONLYALPHA_POSTGRES_DSN` to a dedicated Agent database and unprivileged owning role; do not use the backend DSN/role. Infrastructure provisions the database and revokes PUBLIC access, grants no access to backend tables or secrets, and keeps backend credentials outside the Agent process. Startup rejects superuser/CREATEDB/CREATEROLE roles and a backend schema. Agent initializes only its owned v1 tables and LangGraph checkpoint migrations; no backend migration runs. Local validation uses isolated `_test` databases on the existing canonical test service.

Provide two distinct 32-byte files, mode 0600, using `ONLYALPHA_AGENT_KEY_FILE` (model encryption) and `ONLYALPHA_AGENT_ACCESS_KEY_FILE` (dedicated Agent issuer). Set `ONLYALPHA_AGENT_ORIGIN` to the explicitly permitted Web origin. Keys/credentials are not source, artifacts or logs; preserve the matching key with retained database facts. A missing key or an unavailable original artifact blocks restoration; startup does not regenerate credentials or rewrite sessions.

```sh
onlyalpha-agent serve --host 127.0.0.1 --port 5174
```

A remote listener additionally requires `--ssl-certfile` and `--ssl-keyfile`; proxy-forwarded identity is rejected. Do not expose plaintext remote service or silently trust proxy/user headers. Local development uses only `onlyalpha-dev`; the sole dev topology can supervise the explicitly provisioned independent Agent installation without creating a second stack, installing dependencies or granting business permission on startup.

## Authentication and API

[Agent API v1](../../contracts/agent-api/v1/openapi.json) is separate from backend Product API. A dedicated signed, expiring Agent-audience bearer credential binds issuer, subject, Human/service kind, scopes and token identity. Infrastructure can provision a bounded token with `onlyalpha-agent access-token --subject SUBJECT --kind human --scope chat:read --scope chat:write --expires-in 3600`. Provision model configuration/revocation scopes only when required. Treat command output as a credential. Shipping Web exchanges its verified backend Human session for a separate short-lived Agent-audience assertion. Do not copy backend Cookies or model/service credentials into browser persistence.

Agent verifies audience/subject, scoped operations, ownership, expiry, durable token revocation and request-origin protections. Mutations are Human-only in A2; service credentials can read only explicitly scoped, owned chat. Agent tokens confer no backend authority. Cookie authentication, forwarded-user headers and foreign origins are rejected. No CORS wildcard or backend proxy is provided.

The API configures an encrypted immutable model profile, creates a bounded session, submits a chat message and reads/restores history. Model/session/message writes require canonical UUID idempotency keys; reusing a key for another subject or intent is denied. Responses never return model secrets. Provider HTTPS verification stays enabled; redirects and proxy credential forwarding are disabled. HTTP is allowed only for explicit loopback providers. Provider output is untrusted; A3 retains canonical Authoring validation.

## Recovery and version binding

Sessions pin exact workflow code, installed dependency files, interpreter, checkpoint reader, immutable model profile and call budget. The fingerprint excludes unrelated installed packages and generated bytecode; it includes native libraries and dependency data. Keep each trusted artifact/environment required by active sessions available under its own supervised process. A newer installation cannot execute an older bound session: it reports `WORKFLOW_UNAVAILABLE`; the original installation can continue it. There is no code download, latest fallback or automatic session migration.

A PostgreSQL advisory session lock fences concurrent service instances. Immutable call plans and command receipts commit before external I/O; usage derives from those plans. Full frozen model requests and bounded results are durable facts; checkpoint state contains references/results without keys. Recorded results repair checkpoint loss without another model call. An accepted call lacking a provable result remains `OUTCOME_UNKNOWN`; restart, resume and repeated messages never resend it or reset budget. Resume reuses the original workflow only. Checkpoints do not grant consent or scientific qualification.

Superseded Rust C2 chat/model hosting is retired at the UI cutover. Legacy Python Research consumers remain until their actual replacement gates pass; they are never this page's fallback. There is no old dev-chat data conversion or automatic publication/deployment.

## Scoped backend proposal staging (A3)

Set `ONLYALPHA_AGENT_BACKEND_URL` and `ONLYALPHA_AGENT_BACKEND_CREDENTIAL_FILE` together to enable proposal staging. The protected
credential file uses mode 0600 and contains only the separately provisioned `oa-proposal-v1.<grant UUID>.<32-byte hex secret>`
credential for a backend-owned, Human-authorized proposal grant. The backend stores its digest and explicit scope/limit/expiry;
no backend Cookie, database credential or model key belongs in this file. There is no automatic grant, configuration fallback or
remote plaintext allowance. The existing backend deployment/transport constraints remain in force.

A Human-authenticated Agent API call to `POST /api/v1/agent/sessions/{id}/proposals` names the exact current model-event `expected`
fingerprint and an Agent idempotency key. Backend-provided owner must match that user. The local call plan freezes the candidate,
origin, current backend bases, credential/endpoint binding and distinct backend Command ID before its one submission. Repeating the
same Agent request queries that original Command when uncertain; it never automatically sends it again. `REGISTERED` means only that
backend retained an unadmitted snapshot. It is not Factor confirmation, publication, execution or scientific qualification.

`GET /api/v1/agent/sessions/{id}/proposals/{local_command}` reads confirmation/current-head information from the owning backend afresh.
An unavailable backend is reported as unavailable; local history is still readable. Exact receipts and classified observations are
Agent provenance, not another current Factor store. Credential changes pause original binding reconciliation; do not mint another
Command to disguise UNKNOWN. Model-call budgets are separate from backend grant usage. Only the frontend's direct backend Human
command can confirm; this client exposes no confirmation or Research operation. Shipping C2 uses these exact registration/confirmation boundaries.


## Shipping browser deployment

Operator provisioning uses an empty dedicated unprivileged database and an empty Agent state directory. Run the independently
installed `onlyalpha_agent provision --root /chosen/agent-state --backend-root /chosen/backend-user-data --dsn-file /protected/agent.dsn`.
The DSN file must be private; provisioning writes distinct 0600 keys, the Agent-only proposal credential, a protected backend browser
assertion key and public `agent-connection.json`. No model, grant, Factor or business Command is created. Partial/nonempty
installations and symlink targets are refused; provisioning never repairs or overwrites another installation.

Agent also reads `ONLYALPHA_AGENT_BROWSER_KEY_FILE` and `ONLYALPHA_AGENT_EXPECTED_WORKFLOW` when the deployment provides browser
exchange and a selected installation manifest. The ordinary page explicitly enables the bounded proposal grant, configures the
model and creates discussion through public UI. Each model occurrence can have only one staging plan. Query/recovery and explicit
abandonment endpoints preserve original command identity; an accepted occurrence without external result remains UNKNOWN.

See [Shipping C2 architecture](../../docs/agent-service-architecture.md#shipping-c2-interaction-and-independent-lifecycle) for exact
origin/audience rules, the protected contained-dev listener, independent outage behavior and retirement boundaries.
