# 回测结果、完成候选与正式发布

本契约依据[ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md)演进原文件Evidence／SQLite读取与部分终态结果发布规则。完整成员和接口见[有限作业契约](job-execution-contract.md)。第一阶段只补齐定义，旧实现尚未切换；这里不声明新结果已可通过API读取。

## 经济归属

结果组合只观察各owner的事实和计算结果，不重算费用、Account经济、Ledger收益或制造对账调整。Account拥有runtime_performance，StrategyLedger拥有cluster_performance；后者不合成为虚假的Account收益。保留所属金额／数量／收益精度，因子的新数值规范不改变这些边界。

最终持仓、Allocation、完整订单生命周期和交易／费用、Account和各Ledger时间线（含实际genesis）、诊断以及因果事实必须留存。不是只保存PnL。原close_curve的NAV／高水位／回撤／账户序号、已观察sample和同数量buy-and-hold比较由ResultPlan明确绑定；短样本不凭空年化，无成交时仍保留完整合法空集合和轴。

## 完成候选和Authority

经济内部transcript只能证明自身范围，不证明Dataset耗尽、信号／Broker／Event drain、子进程回收、权限或Product发布。只有真实执行owner完成实际输入、经济不变量、drain和ResultPlan成员后才能产生私有CompletedBacktest。Backend监督者正向回收原子进程后，才能组合私有CompletedJobCandidate。manifest、客户端hash／boolean／DTO均不可构造此权限。

内存未发布候选可在取消、失败或进程中断后释放，不能被Freeze／Qualification／Promotion消费。诊断日志不替代正式结果。当前`BACKTEST_RESULT@1`内部transcript与旧BTR／Evidence身份不改写为新格式，也不建立旧reader兼容。

## 身份和完整内容

FrozenJobBinding包含原Run scope、完整配置／初始状态、策略／程序／精确参数、Kernel和规则工件以及有序输入身份。ResultPlan声明全成员的逻辑键、类型、schema、轴和计数要求。最终结果身份绑定全正式内容与该冻结绑定；Attempt、主机、PID、耗时／当前时间不参加经济身份。

canonical编码使用既有规范化指纹算法、精确整数时间和十进制字符串，不用float或展示标签替代原事实。重复引用和错误关联拒绝；成员缺失不能默认空表，读取不可用不能当作确定不存在。集合规范序与因果事件顺序分开。

## 原子发布和查询

全部正式内容、唯一publication及Run／Attempt终态在同一PostgreSQL事务写入。事务核对Run、修订、有效claim／lease／fence、精确绑定和完整成员；相同Run的冲突必须比较全部绑定，不可ON CONFLICT后直接称成功。普通应用角色不得改删正式内容。

提交确认后才能返回完成；COMMIT未知先观察原事务和原Run，不制造FAILED、不换Run。只在证明未发布且获得合法新Claim后，才允许从原冻结输入重算。查询校验权限、正文和成员关联，读取完整正式结果，不再次执行整段回测。

## 终止规则

COMPLETED必须拥有完整发布。CANCELLED、FAILED只保留真实控制／错误原因，不发布前缀结果、假空成交或全零收益。UNKNOWN保留原身份和观察路径，不能映射为已失败／已取消／未提交。CANCEL_REQUESTED是意图，完成竞争沿原状态机裁定；迟到取消不撤销已完成结果。

只有真实经济不变量通过才可完成；开放／UNKNOWN订单、未处理Risk hold、保留现金／Margin或对账错误不能凭终止标签消除。合法持仓和未结算状态按所属契约判断，不能虚构强平取得完成。

## 回归与证据

第一阶段测试只验证冻结值、精确参数引用和完整结果计划谓词。后续必须取得真实PG事务／权限／未知／并发、同Run重算、经济golden、取消、进程与正常Web证据。纯值模型测试不证明这些能力；不以旧SQLitebaseline或文件Witness诊断宣称新发布链路通过。
