# Indicator 标准库

Indicator 是无交易副作用的最底层确定性计算单元。统一接口包含 identity/type、ready、Warmup、`update_bar()`、`snapshot()`、`reset()` 和可选 `canonical_score()`。它不访问 Factor、Strategy、Cluster、Runtime、Broker 或 Manager，也不读取系统时间。

内置标准库位于各自子目录：MACD、RSI、EMA、SMA、ATR、Bollinger、Rolling Return、Rolling Volatility 和 Z-Score。Config 自己提供默认参数并校验；Factory 只把请求交给 Config。专有结果通过不可变强类型 Snapshot 输出，不增加任意 getter。

Canonical Score 的值域为 `[-1, 1]`，但 Dimension 决定语义：Momentum 的正值可以表示正动量，Volatility 的正值只表示波动较高，不能解释为看涨。原始 Snapshot 始终是权威结果。

## RESEARCH batch readiness publication

以下是 ADR 0137 的内部 RESEARCH 发布合同，不是 Trading incremental Indicator 的 `ready`/Snapshot 接口，也不是 chart Product API。
Trading 的 Config、增量状态和强类型 immutable Snapshot Authority 保持不变。

### 支持范围

| 维度 | 当前合同 |
|---|---|
| Production readiness V1 registration | 仅 `onlyalpha.indicator.sma@1` 的 RESEARCH backend；EMA、RSI 等没有 readiness V1 注册 |
| Graph / execution | 一个 TIME_SERIES node，server-side batch execution；不支持 dependent DAG 或 CROSS_SECTION readiness |
| Input | exact immutable Dataset Snapshot，closed historical input；无 Preview、实时增量 readiness 或 LIVE Authority |
| SMA period | 注册合同要求整数 `period >= 1`；内部语义没有 chart resource policy 的最大值限制 |
| SMA state | period 1 从首点 READY；更大 period 的前 `period - 1` 点为 PARTIAL / WARMUP_INCOMPLETE，其后 READY / NONE |
| Numeric output | 保留已有 partial-window Decimal mean；partial/ready 的 exact zero 都是真实数值，不是 unavailable |

backend 在同一次执行中原子产生 values 和 readiness。Core executor 校验完整 output membership、axis/row alignment、
state/reason/value compatibility 后 seal execution；Core 不包含 SMA warmup 推导规则。SMA 的缺失输入 FAIL，
不会为了完成发布而伪造 UNAVAILABLE 行。通用 carrier 能表示更多状态，不代表其他生产计算已获支持。

### Readiness Contract V1

| State | Reason | Value rule |
|---|---|---|
| PARTIAL | WARMUP_INCOMPLETE | Nonnull，或仅当 output nullable 时为 null |
| READY | NONE | Nonnull，包括 exact zero |
| READY | VALUE_UNDEFINED | Null，且 output 必须 nullable |
| UNAVAILABLE | INPUT_UNAVAILABLE | Null；这是 producer 明确产生的事实，不是缺失 proof |
| UNAVAILABLE | DEPENDENCY_UNAVAILABLE | Null；不表示当前已支持 dependent graph |

每个 output point 都必须有一个 non-null、canonical state/reason；value 的类型/nullability 仍独立受 Definition 校验。
missing/malformed readiness 是错误，不能升级为 READY 或合成 UNAVAILABLE。Web/Query 不得从 row index、参数、truthiness、
zero 或 null 独立推导 readiness；页面切分也不改变正式点事实。

### Versioned internal publication 与 identity

Research Job Plan V2 携带 exact publication contract schema 1：Calculation Result schema **2**、Execution Evidence schema **2**、
Readiness Contract **1**。V1 Job Plan 没有 publication 请求，V1 execution/result/evidence 行为和身份不变。
Calculation semantic identity 仍为 **Dataset Snapshot + Calculation Graph**（既有 RESEARCH identity domain）；
publication versions、implementation、audit time、path 和 Job identity 不进入该语义身份。

Result V2 在原 Result Authority 的 `v2/sha256` namespace 中绑定 exact **Values + Readiness**；Evidence V2 在原 Evidence
Authority 的版本 namespace 中绑定该 Result/content 与 **live sealed producer + exact implementation**，不是公开 Result 模型的
自我声明。合法 V1 Result 只能作为 exact numeric parity；V1 Evidence 永远不能满足 readiness evidence。V2 不 fallback 到 V1。

### Durable publication / recovery

| 已证明的 durable state | Job 行为 |
|---|---|
| Complete Result2 + unique exact Evidence2 | REUSED；不执行 backend，也不检查 V1 parity |
| No Result2（authoritative NOT_FOUND） | 一次 exact sealed V2 execute、可选 V1 parity、Result commit、Evidence publish，EXECUTED |
| Result2 without exact Evidence2 | 新 live sealed execution、可选 parity、idempotent Result reuse、Evidence publish，EXECUTED；随后可 REUSED |
| Corrupt / ambiguous / unavailable authority | Fail closed；不可解释成 cache miss，不得 rebuild 或覆盖历史 |

Result-only 是 Result commit 后、Evidence publish 前 crash 的合法不完整状态。恢复必须证明新执行与原 immutable Result 完全相同，
不得从 read model mint Evidence；hard restart 后原 Result bytes/identity 保持不变。显式 authoring generation 选择 exact producer occurrence；
没有显式选择时多个 producer 保持歧义。V1/V2 numeric parity 比较 exact partition/order、Arrow schema/metadata、timestamps、nulls 和
values，忽略 chunk layout；不匹配在 publication 前停止。

### 显式边界

内部 foundation 不提供 Product Command、chart Run admission、Specification V3、Research Result V4、Artifact V2、
Query/HTTP/OpenAPI、generated Web client 或 chart overlay。不接受 custom user code，也不提供 preview/incremental readiness。
未来 Product Slice 需独立 owner 授权，并通过 formal API 消费已有 Authority；不得在 HTTP/Web 重算 readiness 或绕过 sealed producer。
