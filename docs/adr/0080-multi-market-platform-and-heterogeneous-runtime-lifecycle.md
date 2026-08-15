# ADR 0080: Multi-Market Platform and Heterogeneous Runtime Lifecycle

Status: Accepted

Date: 2026-08-15

## Context

OnlyAlpha 的目标是多市场量化平台，而不是以某个具体市场为中心再增加若干适配器。现有 Domain、Market Product、
Engine 和 Runtime 合同已经冻结市场中立的交易语义，但尚未明确以下长期产品边界：

- 一个 Engine 是否只运行生命周期相同的 Runtime；
- 多市场是由一个跨市场 Trading Runtime 承担，还是由多个隔离 Runtime 组合；
- 有限 Research、Backtest、Sim 或 Live 产品完成后，何时可以声明平台“正式支持某市场”；
- 跨市场结果汇总是否可以反向成为交易状态 authority。

这些选择会直接影响 Runtime ownership、Account/currency identity、Engine lifecycle、配置 grouping、Web 控制面与产品声明。

## Decision

OnlyAlpha 是以公共 Domain contract 为基础的多市场平台。`onlyalpha.domain` 定义跨市场共同使用的 canonical
identity、instrument、venue、currency、time、market data、price、quantity、money、order、trade、position、account、fee、
settlement、margin 与 immutable fact vocabulary。具体市场制度由 versioned Market Product Plugin 拥有；Core 和 Trading
Kernel 不按市场名称选择经济行为。

一个 `OnlyEngine` 的目标产品形态允许同时持有并运行以下四种 Runtime：

```text
OnlyEngine
├── Research Runtime
├── Backtest Runtime
├── Sim Runtime
└── Live Runtime
```

四种 Runtime 的生命周期相互独立。有限 Research/Backtest 完成不得隐式停止 Sim/Live；一个 Runtime 的 start、wait、stop、
close 或失败不得被解释为另一个 Runtime 的 lifecycle command 或 domain fact。Engine 负责统一 planning、composition、Session、
共享基础设施引用、独立生命周期编排、结果汇总与诊断，但不拥有任何 Runtime 的 mutable economic authority。

当前目标产品合同采用：

```text
One Trading Runtime
= One Account authority
= One resolved Market Product
= One Account currency
```

多市场通过同一 Engine 下多个隔离 Trading Runtime 组合，而不是在单个 Runtime/Account 中混合市场或币种：

```text
OnlyEngine
├── CN A-share Runtime / CNY Account
├── HK Equity Runtime / HKD Account
├── US Equity Runtime / USD Account
└── Crypto Runtime / configured single-currency Account
```

每个 Trading Runtime 继续独占其 Order、Position、Allocation、Account、Ledger、Risk、Reservation、Fee、Settlement、
Transaction、Projection、Checkpoint 与 Recovery authority。跨市场汇总只允许存在于 Engine Result/Analytics/Artifact、Query/API
和 Web presentation；汇总 projection 不得提交订单、共享资金、修改 Runtime state 或成为组合级交易 authority。

一个市场只有在以下四种产品纵切面均由正式入口、产品合同、恢复/确定性测试和认证证据闭环后，才能声明
“OnlyAlpha 正式支持该市场”：

```text
Research + Backtest + Sim + Live
```

在此之前，可以认证并发布明确命名、明确版本和明确范围的有限产品，例如某市场的 Research、Backtest 或 Sim 产品；不得用
该有限合同推导平台已经正式支持整个市场。`CN_A_SHARE_DURABLE_BACKTEST_V1` 因此仍是正式、已认证的有限 A 股 Backtest
产品，但不等于 OnlyAlpha 已正式支持完整 A 股市场。

Research 的市场覆盖通过 canonical Dataset/Reference/Calculation/Result 合同表达，不要求为了产品名称对称而创建 Trading
Market Product Binding、Account 或 Broker authority。

## Rejected Alternatives

1. 一个 Engine 一次只允许一种 Runtime type，迫使 Application 创建四套产品入口。
2. 将 Research、Backtest、Sim、Live 的完成/失败绑定成一个共享生命周期状态机。
3. 在当前产品中让一个 Trading Runtime/Account 同时持有多个 Market Product 或 currency authority。
4. 为每个市场复制 Engine、Runtime、Manager 或 Trading Kernel。
5. 以 Market Product plugin、Domain enum、Fixture 或单一 Runtime 产品存在为依据声明正式支持整个市场。
6. 让 Engine/Web 的跨市场汇总成为交易资金、仓位或风险 authority。

## Consequences

- Runtime Environment identity 和兼容性必须包含 exact resolved Market Product、Account identity 与 single currency。
- 市场或币种不兼容的 Cluster 必须拆分 Runtime 或 fail closed。
- Engine 未来需要支持 heterogeneous finite/streaming Runtime Session，并提供单 Runtime lifecycle command 与整体聚合状态。
- 多币种账户、FX valuation、跨市场资金共享、组合保证金与单 Runtime 多市场交易不属于当前目标合同；若引入，必须新增 ADR、
  authority、schema、recovery 与产品认证，不能放宽本 ADR。
- 产品文档必须区分“正式有限产品”与“平台正式支持某市场”。

## Validation / Architecture Guards

后续实现和文档门禁必须证明：

```text
One Engine may own RESEARCH + BACKTEST + SIM + LIVE sessions concurrently
Runtime lifecycles remain independent
One Trading Runtime binds exactly one Account, Market Product and currency
Cross-market aggregation is read-only
No market-specific Engine/Runtime/Manager path
No whole-market support claim before all four Runtime product slices close
```

当前源码尚未实现一个 Engine 中四类 Runtime 的完整异构组合，也未实现 Research/Live 产品 Runtime。本 ADR 是目标架构合同，
不得被描述为当前已完成能力。
