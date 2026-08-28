# P9.K.7 Remote Gateway Protocol Foundation

## Purpose and boundary

P9.K.7 freezes one provider-neutral process/OS boundary for future remote infrastructure Gateways. It does not implement a provider,
real trading, a second Product API, or a second Kernel.

```text
Product actor
→ HTTPS / canonical OpenAPI
→ Product Command / Query
→ Stateful Kernel
→ typed Kernel port
→ remote infrastructure adapter
→ onlyalpha.gateway.v1 Protobuf/gRPC
→ future Gateway
→ provider / venue
```

Product actors never call the Gateway as their normal control path. Internal deterministic business calls remain direct and typed. The
Gateway may own provider connection/session state, transport state, provider correlation, remote command receipts, and bounded stream
history. Strategy, Portfolio, Risk, Research, Product authorization, Kernel lifecycle, and local business projections remain outside it.

## Contract authority and versioning

The sole authoring authority is the sorted `.proto` set under:

```text
contracts/gateway/v1/onlyalpha_gateway_protocol/v1/
```

The compatibility-major authority is the Protobuf package:

```protobuf
package onlyalpha.gateway.v1;
```

Generated Python messages/stubs and `descriptor.pb` in `onlyalpha-gateway-protocol` are deterministic projections, not another contract.
The descriptor SHA256 is diagnostic/deployment evidence only. Within v1, existing field number/type/removal or reserved reuse, RPC
removal/signature changes, and package-major drift fail closed. Breaking semantics require a new `v2` namespace.

Generation is pinned to:

```text
grpcio-tools 1.73.1
grpcio       1.73.1
protobuf     6.33.5
```

The protobuf pin was updated to 6.33.5 by the P9.K.7 post-commit security closure; canonical `.proto` bytes, protocol major,
generated descriptor identity, and Gateway business semantics remained unchanged.

The generation input excludes timestamps, hostnames, absolute paths, Git SHA, random values, and build numbers. Governance commands are:

```bash
uv run python scripts/gateway_protocol.py write
uv run python scripts/gateway_protocol.py check
uv run python scripts/gateway_protocol.py verify --base <immutable-40-char-git-sha>
```

`verify` extracts historical `.proto` bytes from the immutable Git object. The first K7 revision is an explicit bootstrap when the base
contains no Gateway protocol; subsequent changes compare descriptors mechanically.

## Identity taxonomy

| Identity | Meaning | Semantic input? |
|---|---|---|
| `gateway_id` | stable configured/logical Gateway | no |
| `gateway_instance_id` | one concrete Gateway process lifetime | no |
| `command_id` | logical retryable remote side effect | remote operational only |
| `command_fingerprint` | canonical remote command intent binding | remote operational only |
| `correlation_id` | one transport attempt/trace | no |
| `stream_id` + `sequence` | ordering authority for one stream | infrastructure stream only |
| protocol major / descriptor hash | compatibility/diagnostics | no |
| deadline, retry count, address, TLS identity | transport/security context | no |

Transport/session metadata never enters Dataset, Calculation, Candidate, Strategy, or Strategy Revision identity. For the K7 test-only
mutation, the fingerprint is SHA256 over a fixed v1 domain separator plus the UTF-8 test payload. Correlation ID, Gateway instance,
deadline, and retry metadata are deliberately excluded.

## Handshake and capabilities

Every connection/reconnection performs `Handshake` before side effects. It proves logical Gateway identity, concrete process instance,
protocol major, diagnostic descriptor identity, implementation version, and advertised capabilities. K7 defines only:

```text
TEST_UNARY
TEST_STREAM
```

Protocol mismatch or an absent required capability fails before `READY`. A new `gateway_instance_id` means the process restarted and
invalidates prior capability/session/stream assumptions even when TCP reconnect succeeds.

The infrastructure connection lifecycle is:

```text
DISCONNECTED → CONNECTING → HANDSHAKING → READY → STREAMING
```

After disconnect: reconnect, re-handshake, revalidate instance/protocol/capabilities, then choose exact resume or reconciliation. This is
connectivity state, not a second business lifecycle.

## Unary mutation, retry, and timeout

`ApplyTestMutation` is deliberately provider-neutral and TEST ONLY. It exists solely to prove:

```text
same command_id + same canonical fingerprint
→ replay the same outcome; one logical side effect

same command_id + different canonical fingerprint
→ COMMAND_CONFLICT; no second side effect
```

A retry keeps `command_id` and canonical fingerprint while `correlation_id` may change. The client performs no hidden automatic mutation
retry. A gRPC timeout/UNAVAILABLE after submission means the outcome is unknown to the caller; it is not a business rejection and does
not prove non-execution. The legal response is an explicit retry with the same command identity or later provider reconciliation.

OnlyAlpha Remote Protocol does **not** claim exactly-once network delivery. Convergence is provided by retryable transport, stable command
identity, idempotent receipt replay, and future provider reconciliation where required.

## Error model

gRPC transport status and Gateway application/infrastructure results remain separate. The stable v1 application taxonomy is:

```text
INVALID_REQUEST
PROTOCOL_MISMATCH
UNSUPPORTED_CAPABILITY
NOT_READY
COMMAND_CONFLICT
PROVIDER_UNAVAILABLE
PROVIDER_REJECTED
DEADLINE_EXCEEDED
RESYNC_REQUIRED
INTERNAL_ERROR
```

Provider codes/messages are diagnostics. Kernel behavior must never depend on provider exception strings.

## Test stream semantics

`WatchTestEvents` is a dedicated server-streaming RPC, separate from unary command RPCs. It is not a universal message bus. Each event has
`stream_id`, `gateway_instance_id`, explicit monotonic `sequence`, stable test `event_id`, evidence-only observation time, and payload.

Sequence is the ordering authority. Wall-clock time never repairs or reorders the stream.

- exact next sequence: accept;
- duplicate/already applied sequence: detect and report deterministically, do not apply twice;
- forward gap: fail explicitly with `RESYNC_REQUIRED` semantics;
- `resume_after=N` with retained history: continue exactly at `N+1`;
- unavailable exact continuation: return `RESYNC_REQUIRED`, never jump to latest;
- process-instance mismatch: require re-handshake/recovery decision.

The test Gateway history is bounded. Buffer truncation that prevents exact continuation becomes `RESYNC_REQUIRED`; it never silently drops
required history. Future market-data and execution streams may define different recovery contracts. Market data may permit explicit
resnapshot/resubscribe; execution gaps will generally require provider reconciliation. K7 implements neither production stream.

## Security

Production remote Gateway traffic must use authenticated encrypted transport, expected to be TLS/mTLS or a later explicitly governed
equivalent. K7 uses an insecure localhost channel only in the deterministic test fixture. It does not build PKI, certificate rotation,
Vault, SPIFFE, a service mesh, or authorization semantics. Security metadata stays outside business fingerprints.

## Future provider extension rules

QMT/CTP implementations are infrastructure adapters behind typed Kernel ports. They may extend v1 only compatibly or introduce v2 for a
breaking semantic boundary. A provider extension must not expose a Product client API, duplicate Strategy/Portfolio/Risk/accounting truth,
assume exactly-once transport, map timeout to rejection, resume from latest silently, or create a provider-specific duplicate core protocol.

Production order/account/position RPCs, provider durability, reconciliation, authenticated transport, deployment policy, and real Broker
permissions remain future provider work.
