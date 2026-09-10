# FP-BROKER-001 — Session-bound order identity and reconnect command replay

## Failure family

Logical order identity changes when a broker session changes, or pre-disconnect commands are unintentionally re-issued after reconnect.

## External / internal evidence

- WonderTrader issue #77: an XTP entrust identity depended on `session_id`; after reconnect, replayed order callbacks used a different session and no longer mapped to the same logical order. The same issue also notes explicit relogin/resubscription requirements and partial-cancel status mapping concerns.
  - https://github.com/wondertrader/wondertrader/issues/77
- TqSdk issue #71: an order submitted before disconnect could be submitted again after reconnect.
  - https://github.com/shinnytech/tqsdk-python/issues/71
- Evidence status: observed upstream broker/reconnect defects.

## Observed symptom

The same external order can appear under two local identities after reconnect, or an old submit intent can cause a second external side effect when the session is rebuilt.

## Generalized root cause

Logical command/order identity was coupled to connection/session identity, and reconnect replay semantics did not distinguish durable intent from transport-level request replay.

## Risk to OnlyAlpha

A single Order Intent can become multiple local or venue orders, reconciliation can fail to converge, partial fills can attach to the wrong order, and risk exposure can be duplicated.

## OnlyAlpha invariant

Logical order identity and deterministic client-order identity MUST NOT depend on ephemeral transport/session identity.

A reconnect MUST NOT replay a risk-increasing command unless the exact durable command contract explicitly proves that replay is idempotent and still required.

## Required protection

- stable OnlyOrderId / client-order identity independent of connection generation;
- separate transport/session identity for correlation and diagnostics only;
- UNKNOWN/reconciliation semantics for uncertain submits;
- explicit provider order-state mapping including partial/cancel states;
- reconnect protocols that query/reconcile durable venue facts before deciding whether any command remains outstanding.

## Required tests

- submit under session A, reconnect as session B, receive replayed venue callback → same logical order identity;
- disconnect after request send but before acknowledgement → no blind second submit;
- pre-disconnect command remains in a resend buffer → reconnect cannot produce a second economic order;
- partial-cancel/partially-filled terminal mappings preserve canonical order/fill state and trigger required callbacks exactly once.

## Non-solutions / rejected shortcuts

Generating a new client ID after every reconnect, replaying every buffered request, or keying order identity by broker session ID does not preserve idempotency.

## Scope notes

Applies to real Broker adapters, QMT/CTP/XTP gateways, and any transport with session-scoped provider identifiers. Venue-native order IDs may remain session/provider specific; the canonical OnlyAlpha identity must not.