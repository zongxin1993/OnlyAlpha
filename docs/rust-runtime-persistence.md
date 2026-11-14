# Rust Runtime 状态、持久化与恢复

本契约落实[ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md)，取代本页原SQLite、文件Source、逐Barcheckpoint和强制续接要求。值接口见[有限作业契约](job-execution-contract.md)，经济规则仍由Execution及各组件契约负责。当前仅第一阶段定义，现有`SqliteStore`、`Runtime::create/open`和只读快照还在代码中，按计划五至八阶段迁移，不新增兼容入口。

## 职责与接口

`crates/runtime`提供typed当前会话及持久化／恢复port，不拥有Product准入、租约、用户权限或LIVE授权。目标`Session::new(&RunConfiguration,&RunBinding)`、`apply(&TradingInput)`只消费纯领域值；Backend从已验证FrozenJobBinding映射RunBinding，纯库不反向依赖Backend。

有限会话保留当前Components、幂等关系及ResultPlan所需紧凑结果，不每步读完整历史／恢复全部组件，不保存每Bar全套JSONcheckpoint副本。事件顺序、事实身份、费用、资金、风控、投影和对账要求不因更换介质而取消。

## 事实和提交

Backend持久适配器实现`DurableFactPort`，异步提交实际PreparedTradingFacts，返回绑定原计划和事实的receipt。经济计算保持纯同步，Driver在持久边界等待。receipt不是LIVE权限；真实派单入口仍要求后端私有提交证明与既有准入授权。

同身份同payload幂等，同身份不同authority或前驱不符拒绝。正式事实、索引、必要Outbox及控制关联按所属事务原子提交，committed-unready继续原投影；Ready前不得对外派单。外部观察以原场所稳定事件／订单身份去重，不把送达回执当成交。

## 两种恢复

- Research／Backtest：原Run、精确程序／参数、初始配置、Kernel工件、CH切片和ResultPlan冻结。发布前工作可丢；先观察原发布和未知事务，确认未发布且有新有效Claim后重算。不存在`open`原SQLite继续Bar的生产接口。
- Sim／Live：从PostgreSQL正式事实恢复typed owner并外部对账。已提交未投影继续原计划；提交未知继续观察原订单及降低风险，不能通过重算盲重发外部指令。

缺失、不可读、确定冲突和确定匹配分别处理；不能拿一个合法checkpoint掩盖缺失因果事实。恢复时检查完整scope、配置、版本、事实关联、投影及经济不变量，持久源不可信时拒绝增加风险并保留观察和恢复能力。

## 完成与验证

Runtime当前状态或内部经济transcript不等于Product完成。输入耗尽、Strategy／Broker／Event drain、完整成员、真实子进程join及发布由各所属owner证明；客户端manifest或boolean不能创建资格。

定向回归必须覆盖每个提交／投影窗口、原身份观察、错误前驱／配置／版本、重复与冲突事实、实际重启不重复派单。有限作业性能、PG事实恢复和结果读取分别benchmark；第一阶段不声称这些后续测试通过。
