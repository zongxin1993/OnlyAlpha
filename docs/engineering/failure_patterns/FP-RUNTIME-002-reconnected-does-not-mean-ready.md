# FP-RUNTIME-002 — Transport reconnected does not mean runtime READY

## Failure family

A market-data or trading transport reconnects successfully while semantic state recovery, subscription recovery, or downstream execution remains incomplete or stalled.

## External / internal evidence

- TqSdk issue #491: reconnect succeeded but the market-data path remained stuck in `WAIT_FOR_COMPLETED`.
  - https://github.com/shinnytech/tqsdk-python/issues/491
- TqSdk issue #119: the strategy still appeared to be running after reconnect but no longer progressed.
  - https://github.com/shinnytech/tqsdk-python/issues/119
- vn.py issue #1153: heartbeat/reconnect state could remain in a reconnect loop after a disconnect.
  - https://github.com/vnpy/vnpy/issues/1153
- Evidence status: observed upstream defects with concrete symptoms/reproduction descriptions.

## Observed symptom

A socket/client reports a successful reconnect, process health still appears normal, or a strategy remains marked RUNNING, but subscriptions, data delivery, state synchronization, or legal execution progress is not actually restored.

## Generalized root cause

Transport connectivity was treated as semantic readiness. Connection state, subscription state, synchronization state, runtime liveness and execution permission were collapsed into one status.

## Risk to OnlyAlpha

OnlyAlpha could resume Research/SIM/LIVE work from incomplete state, expose stale observations, or permit risk-increasing execution before market/broker authorities have converged.

## OnlyAlpha invariant

`CONNECTED != READY`.

A runtime becomes READY only after every authority required by its contract has completed recovery and verification. Liveness, transport connectivity and execution permission remain separate facts.

## Required protection

- explicit readiness barriers per authority;
- reconnect followed by resubscription/recovery/reconciliation where required;
- fail-closed transition back to DEGRADED/RECOVERING when an authoritative stream is lost;
- no automatic FULL execution merely because transport reconnects;
- explicit progress/liveness probes for recovery state machines.

## Required tests

- transport reconnects but subscription recovery never completes → runtime remains not READY;
- transport reconnects while the state-recovery protocol is stalled → health/readiness expose the distinction;
- reconnect after market/broker stream loss → execution remains disabled until authoritative recovery completes;
- repeated disconnect/reconnect does not create an infinite reconnect loop or false READY transition.

## Non-solutions / rejected shortcuts

A successful TCP/WebSocket handshake, a process-alive check, a fixed post-reconnect sleep, or a `running=True` flag does not prove semantic readiness.

## Scope notes

Applies to Market Data, Broker, LIVE Runtime, distributed workers and any future gateway whose transport can reconnect independently of state recovery.