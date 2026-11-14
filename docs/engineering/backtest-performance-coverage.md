# 回测性能覆盖矩阵

本清单描述实际调用与基准入口，不代替正式契约或验收。机器可执行清单见 [inventory.json](../../test-data/backtest-benchmarks/inventory.json)，各库 BENCHMARK.md 负责本库计时口径。基准正确性必须先通过。

| 模块 | 回测中的入口/职责 | 基准入口与单位 | 限制 |
| --- | --- | --- | --- |
| order / position / account / strategy-ledger / risk | Execution 组件创建、更新、checkpoint 与恢复 | benches/recovery.rs：new、首条原始命令、重复命令、完整 restore、warm capture、坏摘要拒绝；操作或 bytes/s | 更新候选在计时外创建；恢复输入三档64/129/326；Account使用原checkpoint5 |
| fee / margin / settlement | Fee绑定/记账、现货无保证金初始化、结算状态 | benches/recovery.rs：new/restore/capture，Fee报价与首次/重复记账，Settlement首次/重复整笔成交准入 | Margin现货空状态，不声称测过永续保证金算法 |
| domain | Bar解析与规范值校验 | benches/workload.rs：16/128/740 bars | 输入解析Value在计时外，领域解码在计时内 |
| clock | 调度与时钟推进 | benches/workload.rs：16/128/740 timers | 排程准备在外，dispatch单独测，不混称策略速度 |
| predicates | 数值判定、nullable分支 | benches/workload.rs：16/128/740 comparisons | 实际gt/ge/le literal比较；typed operands解析在外，true/false/null先功能校验 |
| operators | Native Operator v2 十进制stream | benches/workload.rs：rolling_mean/delay 20窗口，16/128/740 samples | 使用实际algebra::Stream，非未被该回测使用的固定整数SMA |
| calculation | scoped cursor/receipt 有序批处理 | benches/workload.rs：1/32/256 events | prepare+commit，精确工作量和revision断言 |
| strategy | graph executor与checkpoint | benches/workload.rs：16/128/740 bars | 复用公开集成测试NodePort，单独测调度，不冒充真实私有Python因子成本 |
| calculation-bridge | typed Calculation与native operator适配 | benches/workload.rs：stream push/restore | 实际rolling_mean/delay adapter；子进程/IPC成本由后端组合链路追踪 |
| market-data | 行情状态cache更新/恢复 | benches/workload.rs：16/128/740 actual bars | history_limit128，输入读取在外，状态候选创建在外 |
| market-data-construction | Provider-native dependency graph校验/编译 | benches/workload.rs：1/8/32 graphs | 使用当前原始图，不声称执行了未使用的聚合算法 |
| metadata-json | configuration/manifest/证据元数据身份 | benches/workload.rs：实际Bar元数据canonical fingerprint | byte吞吐，预算8MiB，完整canonical一致性预检 |
| integration-contract | source type规范化/选择 | benches/workload.rs：16/128/740 type identifiers | 只测当前source类型入口，不包含网络probe |
| broker | 原生BrokerCommand校验 | benches/workload.rs：16/128/740 submits | 使用原OrderRequest并显式绑定受控account_id，未发送订单，不包含模拟成交或网络 |
| execution | typed组件cold restore / 准入规划 | benches/recovery.rs | 同前缀ADMIT规划、成功/资金不足拒绝的cold/reused检查与恢复分开，完整输入与结果断言 |
| runtime | 原执行日志、checkpoint前缀与切面 | benches/recovery.rs：8/32/128估值历史的恢复和apply/日志追加；retained.rs固定次数 | 三档公开API生成有效持久化状态；完整原始Source只认一个runtime参考 |
| backtest | 终态/native原始回放核验 | benches/retained.rs，固定次数 | 真实策略/规则/输入，包含内部重复复核，原API预算不改变 |

## 尚未认定实际执行的候选

- indicators 的直接消费者是后端 chart/native_indicators；当前回测的数学节点来自 operators/native_operators。不能仅凭 backend Cargo 依赖就把 indicators 数学调用认定为此回测已执行。若实战追踪证明调用，则补相应基准。
- event 未在当前 backtest 本地依赖闭包或该调用路径证明使用，不创建占位目录。
- 市场/数据源/模拟Broker插件与后端持久化、HTTP、工作监督单列链路成本，不用纯库跑分代替。

## 统一条件

短操作使用 Criterion 0.7 的输入分组与原始样本；慢读取使用固定轮数。实际环境、构建、输入/预期结果摘要、三档工作量、准备/析构范围和缓存口径必须留存；数字写入各 BENCHMARK.md 前核对原始报告。观察数据丢失、样本不足、输入/结果/环境不相容均不可输出速度收益结论。不新增性能门禁。

## 基准依赖归属

Criterion固定为0.7.0，只启用cargo_bench_support，默认features关闭，仅进入登记目标的dev-dependencies。发布包声明Apache-2.0 OR MIT、MSRV1.80；锁定闭包新增14个registry包，不移除原包。闭包内clap/clap_builder/clap_lex声明MSRV1.85，其余有声明的包不高于此；均低于当前1.99.1工具链。部分包未声明rust-version，不将缺失字段解释成兼容承诺。许可为MIT、Apache-2.0或二者任选，不引入常驻服务。

精确版本为anes0.1.6、anstyle1.0.14、cast0.3.0、ciborium/ciborium-io/ciborium-ll0.2.2、clap/clap_builder4.6.7、clap_lex1.1.1、criterion0.7.0、criterion-plot0.6.0、itertools0.13.0、oorandom11.1.5、tinytemplate1.2.1。实际解析和包校验值以Cargo.lock为准，许可/MSRV依据固定工具镜像中这些正式发布包的Cargo.toml；不从版本号猜测兼容性。观测依赖在日志库接入时单独登记，不让纯内核生产依赖继承基准工具。

## 诊断基础设施的独立成本

`crates/observability` 不属于回测业务依赖闭包的23库基线。它新增 `overhead` bench，分别测 Off/Basic/Detail 下 no-op、显式 operation、摘要 event 和跨任务传播，工作量为1/32/256项。Session 创建、输出线程启动、flush/关闭和结果 Drop 在计时外；每次迭代使用独立容量1024的队列，最大批次事件数小于容量，关闭时断言无丢失和无 I/O 错误。该吞吐只描述已列出的基础设施操作，不代表持久化磁盘吞吐或完整 Web 链路。

观测依赖沿用 tracing0.1.44，新增 tracing-subscriber0.3.23、tracing-appender0.2.5及实际14个增量 registry 包，现有依赖版本未改变。新增包为 MIT/Apache-2.0 许可，明确声明的最高 MSRV 为 time0.3.55/time-core0.1.9/time-macros0.2.32 的 Rust1.88，低于当前 Rust1.99.1。具体闭包由 Cargo.lock 约束；库不读取环境或安装全局 subscriber，应用负责唯一初始化。
