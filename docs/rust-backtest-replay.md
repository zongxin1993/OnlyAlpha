# Rust 回测事件执行与恢复契约

本页依据[ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md)取代原文件Source／SQLite续接及跨介质发布要求。详见[冻结身份和接口](job-execution-contract.md)。当前阶段只定义目标接口；旧RunLoop／TerminalSnapshot仍待迁移，本页不是性能或正式Web验收结论。

## 输入与唯一信号

Research和回测使用同一不可变策略版本、因子程序和精确参数。共同信号只依赖行情、因子和显式参数，输出eligibility／entry／exit；资金、仓位、风控、订单及成交由后续交易环节处理。batch/event同前缀逐点一致，不能把交易过滤后的NO_SIGNAL与Research原始信号比较。

每Attempt加载一次原ClickHouse精确切片，绑定来源、商品／Bar语义、原版本／Seal／segment、时间范围、轴、行数和规范化内容摘要。warmup与sample分别计数，不能只按时间范围读取最新值，不能从Research状态直接携带隐含交易初始信号。

## 经济与事件顺序

回测仿真实时，使用共同交易Kernel。信号在已关闭Bar上形成，最早下一OPEN执行；不得在OPEN偷看未来close。撮合／滑点／费用／数量／风险与时钟均是显式绑定。市场差异留插件。

当前next-open示例保留0.01 BTC、10000 USDT、单多头、无加仓／做空／杠杆及原有费用／滑点规则；这些是例子的绑定，不是通用Kernel硬编码。全量成交模型必须证明其实际capacity／fee资源假设，不能用任意摘要替代；其他市场模型按各自精确规则执行。

订单、资金、仓位及Ledger由各owner维护。持仓按实际最后可见价估值；输入结束不虚构平仓／手续费／成交。缺失或未知状态不能误标完成，取消不表示所有外部影响已撤销。

## 内存会话与完成

typed owner常驻，维护完整因果与必要紧凑结果。不每Bar重读持久历史、全量组件restore或构造整套checkpoint比较，也不把旧Source表原样改成Vec<Value>。预算不足明确拒绝，不自动落文件或SQLite。

`BacktestRun::finish(self)`只在实际输入耗尽、事件／broker drain、完整经济不变量及结果成员成立后返回私有CompletedBacktest；Backend补足实际子进程回收后产生私有完成候选。该对象不能从客户端JSON反序列化，内部经济transcript、空队列、hash相同均不能单独建立完成。

正式结果由PostgreSQL一次原子发布，全成员和Run／Attempt终态同时可见；查询读取正式成员，不重新跑整段回测。

## 中断、未知和取消

保留原Run与冻结输入，新Attempt按既有重试策略从头重算；先观察原发布／未决事务。已发布复用原结果；确证未发布且新Claim有效才重算。不得新建Run规避幂等，也不得用最新工件或行情补缺。Attempt和进程元信息不进入经济结果身份。

CANCEL_REQUESTED只是意图。终态CANCELLED只留控制状态和原因，不发布前缀／部分结果、不生成假零收益；已完整发布完成不因迟到取消撤销。失去lease/fence的旧worker不可发布。完成／取消竞争由现有领域规则和受控事务裁定。

## 验证和计量

完整回归覆盖OPEN／BAR顺序、拒单／成交／费用／风险／资金／仓位／结算、重复输入和身份冲突、drain与伪造完成拒绝、同Run重算经济结果相等、取消及未知窗口。实际行情与工件不可用明确拒绝。

分别测输入准备、纯信号、完整交易执行、结果整理、PG发布和查询／响应；bars/s分母注明实际输入／warmup／sample，不把内部OPEN／BARstep混作K线。保留既有Web300/120秒要求，不新增硬吞吐阈值。信号—收益科学方法与额外优化不纳入本轮。
