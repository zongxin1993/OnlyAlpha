# Settlement Model

`OnlySettlementModel` 分别配置 asset settlement、cash settlement、asset availability、cash availability。
Execution 生成不可变 instruction，生产调用方必须使用版本化 Trading Calendar 推进业务日。

- Generic T0：资产和现金成交后立即可交易并记账。
- A 股：买入资产 T+1 可卖；卖出所得现金当日可再次交易；法律清算按 T+1 表达。
- T+N：使用显式 lag，不能使用布尔 T+1。
- Futures daily mark-to-market 是独立扩展模式，不套用股票证券交收。

当前 Account 不模拟提现；withdrawable cash 是保留边界，不能与 trade-available cash 混同。


## Rust Settlement responsibility and admission boundary

`crates/onlyalpha-kernel/settlement/` is the Domain-only cash-security Settlement library. Python `settlement/{models,identity,authority,facts}.py` supplies the classified model/schedule/initial-owner/due reference; `settlement/planner.py` transaction composition stays in Execution. Source Calendar and compiled policy remain explicit Plugin/adapter inputs. Six distinct booking/availability/withdrawal/legal dates use the existing versioned Domain Calendar and exact trading-day advances, with bounded coverage/search and no UTC-midnight inference. Instruction identity binds full owner, economic, policy/calendar and Position/Allocation lifecycle inputs. Direct snapshots never grant authoring authority.

Resource admission reserves worst-case canonical Fill slots before submission from exact Order quantity and Instrument quantum. Existing records plus all remaining quanta cannot increase on a valid positive Fill. Orders are replayed by their immutable admission ordinal, installing preceding frozen instruction histories before later resource admissions. Capacity remains at most 512 instruction slots, with a 32 MiB checkpoint bound; individual inputs, records and receipts are bounded so all six pending transitions retain space. New-risk admission can fail closed without discarding observed in-budget facts or suppressing maturity.

Execution metadata schema4 freezes the Settlement owner in its existing six-group transaction, and `SETTLEMENT_MATURITY` updates exact Position/Allocation buckets, Account receivables and the Ledger's non-economic Allocation version/evidence witness atomically. Ledger refresh cannot alter quantity, identity/cycle, cost or PnL; no version/before-proof guard is relaxed. Supported cash execution requires immediate booking and cash trading availability, with explicit T+N asset availability, cash withdrawal and legal settlement. Other economic shapes are rejected explicitly.

The library represents all six axes, including delayed booking; it completes only when all six flags are effective. Strict ID/venue, duplicate/restore and complete-booking behavior are independently tested corrections/extensions, not asserted whole Python parity. Source digest is integrity rather than authenticated producer authority. Native codecs and comparison identities do not decode official Python history. Formal Runtime admission, durable storage drivers, deployment upgrade/old-history activation, futures daily MTM, LIVE and Shipping UI acceptance remain separate R3-R8 gates.
