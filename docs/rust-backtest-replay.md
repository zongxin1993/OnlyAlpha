# Rust 回测事件执行与恢复契约

有限回测调用 `runtime.backtest(replay, spec, &inputs, executor, policy, venue)`，传入冻结行情回放、运行规格、逐条输入、策略执行器、下一开盘策略和冻结场所配置，成功后取得 `FiniteBacktestTask<'_, C>`。调用 `task.run(consume)` 进入与 SIM、LIVE 共用的交易事件循环，回调接收每个事件及其处理结果。`run` 成功返回后，调用 `task.finish()` 消费任务，核验成功后返回 `CompletedBacktest`。见[有限任务实现](../crates/runtime/src/trading/backtest/playback.rs)。

需要自行装配因子、策略和执行端口时，使用 [`OnlyAlphaRuntime::backtest_with_ports`](../crates/runtime/src/trading/backtest.rs)，返回通用 `TradingTask`。有限作业的内存完成与正式发布遵循 [ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md) 和[有限作业契约](job-execution-contract.md)。原 Backend 退役期间没有 PostgreSQL 发布服务。

## 输入与唯一信号

Research 与交易按同一冻结因子定义和精确参数逐点对齐。预热推进因子，不产生订单意图。Research 标签可使用未来数据，仅用于评估；回测策略只读取当时已知的因子和只读交易状态。

每Attempt加载一次原ClickHouse精确切片，绑定来源、商品／Bar语义、原版本／Seal／segment、时间范围、轴、行数和规范化内容摘要。warmup与sample分别计数，不能只按时间范围读取最新值，不能从Research状态直接携带隐含交易初始信号。

## 经济与事件顺序

`NEXT_OPEN_LONG_ONLY_V1` 在 T 收盘保留信号，到 T+1 的真实 `bar_start`，用开盘价、冻结的买卖乘数、费用和当时账户状态准入。拒绝须保留原因，订单、派发、成交均为零。通过后由绑定的虚拟场所按同一开盘整笔成交，场所回报依次经 `stage → apply_venue → acknowledge` 入账。该 Bar 的收盘估值与策略决策发生在其后。

当前next-open示例保留0.01 BTC、10000 USDT、单多头、无加仓／做空／杠杆及原有费用／滑点规则；这些是例子的绑定，不是通用Kernel硬编码。全量成交模型必须证明其实际capacity／fee资源假设，不能用任意摘要替代；其他市场模型按各自精确规则执行。

订单、资金、仓位及Ledger由各owner维护。持仓按实际最后可见价估值；输入结束不虚构平仓／手续费／成交。缺失或未知状态不能误标完成，取消不表示所有外部影响已撤销。

## 内存会话与完成

typed owner常驻，维护完整因果与必要紧凑结果。不每Bar重读持久历史、全量组件restore或构造整套checkpoint比较，也不把旧Source表原样改成Vec<Value>。预算不足明确拒绝，不自动落文件或SQLite。

有限任务完成要求实际耗尽输入、标记末根无后继开盘的信号、排空场所回报并验证经济应用及终态。[独立核验函数 `verify_finite_backtest`](../crates/runtime/src/trading/backtest/finite.rs) 按原冻结输入和回执重建执行前缀、收盘权益、回撤、基准及闭合交易周期。产品宿主还须证明实际子进程已回收、Attempt 仍持有有效认领。客户端数据、空队列或摘要相同均不足以建立完成。

正式结果由PostgreSQL一次原子发布，全成员和Run／Attempt终态同时可见；查询读取正式成员，不重新跑整段回测。

## 中断、未知和取消

保留原Run与冻结输入，新Attempt按既有重试策略从头重算；先观察原发布／未决事务。已发布复用原结果；确证未发布且新Claim有效才重算。不得新建Run规避幂等，也不得用最新工件或行情补缺。Attempt和进程元信息不进入经济结果身份。

CANCEL_REQUESTED只是意图。终态CANCELLED只留控制状态和原因，不发布前缀／部分结果、不生成假零收益；已完整发布完成不因迟到取消撤销。失去lease/fence的旧worker不可发布。完成／取消竞争由现有领域规则和受控事务裁定。

## 验证和计量

完整回归覆盖OPEN／BAR顺序、拒单／成交／费用／风险／资金／仓位／结算、重复输入和身份冲突、drain与伪造完成拒绝、同Run重算经济结果相等、取消及未知窗口。实际行情与工件不可用明确拒绝。

分别测输入准备、纯信号、完整交易执行、结果整理、PG发布和查询／响应；bars/s分母注明实际输入／warmup／sample，不把内部OPEN／BARstep混作K线。保留既有Web300/120秒要求，不新增硬吞吐阈值。信号—收益科学方法与额外优化不纳入本轮。
