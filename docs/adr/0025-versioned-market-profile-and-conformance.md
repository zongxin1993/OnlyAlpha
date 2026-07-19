# ADR 0025: Versioned Market Profiles and Conformance Gates

- Status: Superseded in part by ADR 0026
- Date: 2026-07-19
- Modules: config, market, runtime, result, artifact

## Decision

Profile family（如 `CN_A_SHARE_CASH`）与有效版本（如 `2025.1`）是不同身份。Registry 使用左闭右开有效期，拒绝重叠；未指定版本按交易日 `AUTO_EFFECTIVE_DATE` 解析，显式版本使用 `PINNED_VERSION`。Removed 不可解析，Deprecated 只允许显式固定加载。

普通 Override 只允许流动性、滑点、撮合和 strict 等仿真假设。结算、持仓模式、卖空和保证金制度必须通过 Custom Profile 改变。Resolved Profile 保存完整规则 manifest、Reference 身份和确定性指纹。

Stable 的每个 true Capability 必须由绑定 Conformance Pack 的 Scenario 覆盖，并且 Scenario Runner 必须通过正式 Engine/Risk/Broker/ExecutionProcessor；接口或单元测试不能替代纵切面证明。未满足门禁的版本保持 Experimental。

## Consequences

ADR 0026 已删除 Legacy/optional market 语义。跨版本运行由 Rule Engine 按 Trading Day 解析和缓存编译结果，不得静默固定错误版本。
