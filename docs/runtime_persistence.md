# Runtime 持久化边界

本页按已接受的[ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md)定义目标契约。完整值模型、接口与迁移映射见[有限作业契约](job-execution-contract.md)。当前只完成第一阶段定义，旧SQLite实现尚未退役，不能把本页当作已上线证明。

## 唯一归属

需要发布、控制和留存的业务事实属于PostgreSQL；K线实体属于ClickHouse。Runtime纯库不持有数据库客户端、连接串、权限或后端类型。Backend适配数据库，Runtime／Execution owner负责经济语义和确定性状态恢复。日志、文件或内存缓存不是第二份正式事实。

## 有限作业

Research／Backtest的计算、滚动窗口、当前组件、未发布模拟历史留内存。PostgreSQL留存原Command／Run、冻结绑定、Attempt／lease／fence、取消／失败及最终完整结果。禁止逐Bar持久化过程历史，也不能把旧表行机械搬成每Bar完整checkpoint数组。

发布前中断先观察原发布和未解决事务；确证未发布且取得新Claim，才按原Run和冻结输入从头重算。不是续接最后一根Bar，也不是新建经济身份。已发布就复用原结果；输入／实现不可用则明确拒绝，不能用最新替换。

## 持续交易

正式ORDER_INTENT、资金／仓位因果事实、Outbox及场所观察逐步提交PostgreSQL，完成持久化及必要投影后才能获得派单许可。相同业务身份且相同内容幂等；同身份不同内容冲突。外部提交未知保留原订单继续观察／对账，禁止盲重试。

Committed但投影未Ready按原事实／原计划恢复，不回滚外部事实、不根据历史行情重发真实订单。checkpoint只能是已证明的确定性状态边界，不含socket、线程、队列或隐含时钟。缓存丢失可以重建，正式成交与资金不能只在内存。

## 原子性、权限与失败

正式结果全成员、唯一发布记录和Run／Attempt终态在同一PostgreSQL事务提交。正式内容普通角色不得UPDATE／DELETE，控制状态由所属领域CAS演进。未知提交先观察原事务，不伪造FAILED；缺证、不可读、确定不匹配分别报告。

CANCELLED不发布部分结果；迟到取消不撤销已完成发布。取消意图不能等同资源已经停止。业务SQLite、文件型journal、旧格式fallback均退役，不增设文件事实库或Source服务。后续schema通过前向迁移演进，不改已发布迁移字节。

## 验证

有限作业重算与原子发布、持续交易提交／投影／对账分别测试，纯对象重建、实际进程重启、服务重启和部署升级分别说明证据。数据库和运行中应用验证使用固定onlyalpha-dev；本阶段不创建新数据库schema或运行旧长Web取证。
