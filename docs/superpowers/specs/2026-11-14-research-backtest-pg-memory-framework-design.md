# Research／回测的 PostgreSQL、ClickHouse 与内存框架设计

状态：负责人于2026-11-14确认总体设计，已授权编写详细实施计划；后续已授权第一阶段契约、身份与接口定义；不表示执行、存储或产品链路已经迁移。

## 目标与已确认决定

- 项目业务实现不使用SQLite，不建立文件型事实数据库、封闭发布日志、fs-verity依赖或额外Source服务。
- PostgreSQL拥有需要发布、控制、审计及留存的业务数据；ClickHouse拥有K线实体；有限作业的计算与未发布过程数据在内存。
- Research和回测共享同一策略版本和纯信号逻辑，输入限行情、因子及显式参数。仓位、资金、风控、订单和成交在后续交易环节处理。
- 因子采用有类型表达式和声明式窗口/滚动算子；构建一次不可变程序，不逐行解析AST。新因子与Rust原生算子统一precision28、HALF_EVEN、q12和明确的缺值/错误语义。
- 精确参数组合分别认证；不凭有限样例声称覆盖全参数域。创建不可变版本后自动构建认证；Research只消费其精确绑定已就绪的版本。
- Research/Backtest发布前中断：保留原Run，按现有重试策略创建新Attempt，从冻结输入重算；不要求逐Bar断点续算。
- 开发阶段不保留旧接口/格式兼容、转换器或fallback。不重写历史已发布迁移字节；通过正式架构和schema演进完成新边界。
- 本机固定Docker Compose dev，复用已有工具、镜像和缓存。用户已明确开发容器历史可丢弃；实际定向清理见工程记录。
- 不设新的硬吞吐门槛，保留分层bench和实际链路观测；既有300/120秒Web门槛不修改。信号与收益关系设计在这些框架工作完成后另做。

## 方案对照

1. 继续优化SQLite事实源：与用户明确的存储边界冲突，不采用。
2. 独立封闭文件事实段、追加发布日志及Linux存储能力：已撤回；不实施新VM/内核/挂载/加密签名存储体系。
3. PostgreSQL业务事实＋ClickHouse行情＋内存计算：用户选择。复用已有服务与数值模块，减少跨介质发布和重复历史重建。

## 职责与数据归属

| 数据 | 归属与处理 |
|---|---|
| 草稿、不可变因子/策略定义、源码、构建程序、精确参数绑定、认证证据 | PostgreSQL，由各所属业务Authority验证后发布 |
| Command、Run、Attempt、lease/fence、取消意图、结构化失败、版本/初始状态/输入绑定 | PostgreSQL，沿现有生命周期和权限边界 |
| K线、原行情版本/Seal/segment及其实体 | ClickHouse；PG保存精确引用与摘要，不重复保存K线实体 |
| 因子数组、滚动状态、策略状态、重放游标、未发布模拟订单/成交、计算缓存 | 内存，随Attempt结束释放；按预算有界 |
| 正式Research/Backtest结果、结果计划要求留存的明细/曲线/信号和因果证据 | 成功时PG一次原子发布；不只存PnL摘要 |
| Sim/Live已接受订单意图、提交/未知、场所观察、成交、资金及仓位因果事实 | PG逐步持久化，不能当可丢弃过程数据 |
| 运行时当前对象、由业务事实重建的查询缓存 | 内存，不成为第二份正式事实 |
| 性能诊断日志/bench产物 | 沿既有工程观测输出，不作为业务存储、恢复或完成Authority |

“过程历史在内存”不表示真实交易事实可以丢失；它取消的是有限作业的逐步持久化和重复全量状态副本。最终正式结果的成员由ResultPlan明确，不把未发布候选给Freeze/Qualification/Promotion消费。

## 模块边界与依赖

- `operators`、`indicators`：既有纯Rust数学/金融原语及明确数值规则。
- `calculation`：有类型计算定义/计划、参数和输入输出/readiness语义；不持有数据库凭据、权限或发布Authority。
- `strategy`：共同的eligibility/entry/exit计算和实例状态；不读取账户仓位，不产生PG权限。
- `runtime`、`backtest`：当前typed owner、事件驱动协调、临时执行和恢复所需port。退役SqliteStore、文件路径create/open、文件Source/codec及逐Bar持久恢复接口。
- `onlyalpha-broker-virtual`：撮合与虚拟场所计算留在插件；回测临时场所状态在内存，Sim正式场所事实通过后端PG适配器持久化。退役broker.sqlite3和文件型业务journal。
- Backend Application/Persistence/Workers：正式入口、授权、输入准备、构建调度、PostgreSQL/CH接线、claim/fencing、发布与恢复。
- 通用前处理按上述职责拆入已有模块。先不新增crate、ORM、存储引擎、服务或无实际需要的依赖；必要新增依赖另按工程规则调研确认。

PG客户端和事务接线留在Backend；纯Kernel不根据RESEARCH/BACKTEST/SIM/LIVE分叉经济规则。Driver选择内存工作或正式PG持久化能力，不能把内存receipt用作实盘提交许可。

## 因子构建与认证

1. PG创建不可变定义/源码版本，产生独立构建任务；不把每次Research变为一次重复认证。
2. 复用现有受限Python编写入口及标准AST解析能力，在隔离构建边界解析/检查一次，降为严格有类型、canonical程序。不执行用户Python字节码；拒绝任意while、可变容器及隐藏外部输入。
3. Rust拥有程序格式/type检查和实际数值执行；batch/event共享程序及同一原语语义。不通过重排Decimal运算或改变round/null/readiness来获得“等价”。
4. 通用程序构建身份与实际参数绑定身份分开：源码/API/构建器/数值规范/原语实现等决定构建身份；解析后的精确参数及影响执行的契约决定认证绑定。
5. 版本创建自动认证默认参数；新参数生成新绑定并做受影响认证，不重新解析同一通用程序。未认证绑定明确BUILDING/不可用，不在Research worker内隐式补做整套构建认证。
6. 认证使用声明的独立受控输入、因果前缀、batch/event逐点值与缺失值、warmup及恢复用例。真实作业仍校验实际输入、版本/参数/工件和输出约束；构建成功不是任意数据上必然成功的承诺。
7. 因子版本、执行绑定和认证状态须分别建模，不能把“版本可用”解释为任意参数都已认证。不同Run/instrument的可变窗口状态不共享。

当前正式策略仍是结构化Definition/DecisionGraph；本轮保留其共同信号语义，不扩展任意可编程策略callback接口。信号图不得消费Target或未来数据；研究Target计算仍是独立角色。

## 有限作业的执行与重算

1. 正式API提交时，PG持久记录Command幂等身份、Run和冻结意图；提交成功后才返回受理。
2. 冻结绑定包含策略/因子版本、精确程序和认证参数、Kernel/实现工件、初始资金及执行配置、日历/费用/规则、明确的CH输入切片。
3. CH绑定不能只是时间范围：包含来源、商品/Bar语义、精确版本/Seal/segment、行数、轴和规范化内容摘要。每次Attempt重新取得并验证相同输入，不能用最新K线替换。
4. Worker以短PG事务取得Attempt、Worker、lease和fence；加载已冻结输入与程序进入内存。计算期间不持有长PG事务。
5. Research批量计算；Backtest经共同信号和完整交易Kernel进行事件计算。内存保存当前typed state、紧凑必要观测及ResultPlan输出，不保存每Bar整套账户/组件历史副本。
6. 去掉每步从持久源重读全历史、恢复全部组件、重复构造完整JSONcheckpoint再比对的流程；不能把旧SQLite记录原样搬成Vec<Value>。
7. 发布前，真实执行owner检查输入耗尽/适用结束原因、事件与broker drain、经济不变量、精确代码与输入绑定、结果成员及实际子进程回收，产生私有完成候选。客户端JSON/boolean/hash不能产生此资格。
8. 发布前进程丢失：丢弃未发布内存工作。先观察原PG结果/提交状态；若已正式发布则复用原结果，不能重算制造第二份；只有确认未发布且获得新有效Claim后才从冻结输入重算。过期Worker不能发布。

Attempt/PID/耗时/主机不进入业务结果身份。新Attempt继续使用原Run的业务scope、初始状态和冻结绑定，不能按当前时间生成新经济身份或选择最新实现。程序/数据不可用时明确拒绝，不替换版本。

## PG原子发布与只读查询

内存先完成实际结果、完整性和canonical编码准备。一个短PG事务完成：

1. 锁定原Run，核对修订、状态、实际Attempt/Worker/fence及未过期lease；保持既有独立租约时钟与领域生命周期时钟。
2. 写全部正式结果成员及证据，核对ResultPlan、精确输入/程序绑定和内容身份。
3. 插入原Run唯一发布记录；冲突必须读取原记录比较全部绑定，不能ON CONFLICT后不检查就当成功。
4. 同事务更新Attempt及Run终态。完整结果与COMPLETED不能出现跨介质半发布。
5. COMMIT明确成功后才对外返回成功。未知则保留原Run/发布身份；通过原事务已解决的Run锁和实际结果观察判断，不能一次无锁NOT_FOUND就宣布未提交，也不写FAILED掩盖未知。

正式内容表由PG权限和受控业务写口防止普通运行角色UPDATE/DELETE；控制状态按各自领域规则CAS演进。迁移/管理权限不交给作业执行者。读取验证权限、当前正式发布关联、完整类型、canonical身份/摘要与成员关系；不在每次GET重新跑整个历史回测。数据库管理员/迁移操作仍按独立运维权限管理，不声称抵御被攻破数据库超级用户。

## 取消与失败

保留取消意图、fencing和现行安全边界：CANCEL_REQUESTED不是已经停止或已经回滚。取消/失败不生成全零收益、假空成交或假的完成证明。

Q12已确认：首版终态CANCELLED不发布部分结果。无论健康执行者是否仍持有真实前缀，均只留取消状态与原因，释放未发布内存候选；不生成收益报告、空成交占位或供定版/晋升消费的结果。

已正式完成发布的结果不因迟到取消撤销。CANCEL_REQUESTED仍是意图；取消与完整完成的竞争沿正式领域状态机，在PostgreSQL受控事务中裁定，不重写既有终态。取消恢复先观察原Run的实际发布；没有发布且已无ACTIVE时，只结束取消控制流程，不创建Attempt去生成取消结果。

失败同样只保留真实控制/错误事实，不伪造业务结果。临时进度或诊断输出不是已发布结果，也不能被定版或晋升消费。

## Sim/Live正式持久化与恢复

不将有限作业重算模式用于真实/持续交易事实：

- 正式订单意图及必要outbox先PG持久，再准许实际外部提交。
- 实际场所响应、未知、成交、资金及仓位因果事实PG留存，稳定外部订单/Event身份幂等。
- 从PG真实业务事实恢复typed owner并做外部对账；不能重新执行市场回放来盲重发订单。
- 已提交未完成投影按原事实和原计划恢复；外部提交未知继续观察原订单/对账并降低风险。
- 内存缓存丢失可重建；发布/派单资格不能由内存后端或调用方DTO伪造。

该要求定义共用基础的正确边界，不宣称本轮交付完整Sim/Live产品、真实券商接入或实盘授权。

## 迁移与退役范围

所有旧接口/格式兼容、SQLite/文件业务journal、Source封闭段/发布日志/新VM方案均不实施。以新ADR明确演进下位契约：ADR0089中PG禁止结果内容、ADR0091中PG-free结果读平面、旧文件Result/Artifact发布与Backtest后续Attempt强制Resume原SQLite等条款。Constitution及其指纹不改。

保留已发布迁移bytes/校验身份，使用正式迁移机制演进schema，不以开发数据已清空为由覆盖已发布迁移。旧已接受ADR保留为历史，新ADR只替代明确条款。

退役必须同时覆盖Runtime生产依赖、虚拟券商生产依赖、Backtest dev依赖；Cargo.lock中的rusqlite/libsqlite3-sys及全部实际调用者、测试、benches、SDK/验证脚本、镜像构建和活动文档。旧文件Source API不能以换名、fallback或隐藏路径保留。历史调查/ADR仅作材料，不作为新实现入口。

质量门禁从“限定位置可用SQLite”演进为业务依赖全面拒绝SQLite，覆盖alias/传递依赖；正反例都验证，其他C/Zstd编译隔离规则只按实际消费者变更。

## 开发环境与已执行清理

固定本机onlyalpha-dev，不换Docker daemon、不新建VM、不新增服务；PG18.6/CH26.3及现有工具镜像复用。

用户明确授权后，已持有host/container生命周期锁并核对唯一引用，删除onlyalpha-dev-postgres-data、onlyalpha-dev-clickhouse-data、onlyalpha-dev-user-data、onlyalpha-dev-agent-state；移除停止的旧dev应用及重建PG/CH容器。PostgreSQL/CH同镜像健康、PG用户关系为空；validation工具容器及编译缓存保留，旧业务程序未启动。host源码/调查存档、镜像和无关build卷未删除。记录位于test-results/strategy-research-framework/2026-11-14-baseline/dev-reset/receipt.json。

应用数据库schema/权限仍待新设计实施后通过显式prepare/migration建立；当前数据库健康不等于应用可用或功能验收通过。新工具/业务工件必须绑定最终源码，不用旧业务binary冒充新实现。

## 验证与完成条件

- 数值/信号：手算golden、null/error/warmup、同前缀batch/event、独立实例状态、精确参数认证隔离；信号无账户/资金访问。
- 有限作业：完整内存执行和经济结果/因果关系；中断后同Run新Attempt重算相等；失去lease的Worker拒绝发布；不同输入不可复用。
- PostgreSQL：真实事务回滚、发布原子性、并发唯一发布、COMMIT未知原身份观察、取消竞争、CANCELLED无部分结果/无发布记录、迟到取消不撤销已完成结果、读权限与正式内容不可改、查询不重算。
- Sim/Live基础：PG正式订单/成交/资金源恢复、committed-unready、未知外部提交、不重复订单，内存后端不授予真实派单许可。
- 市场输入：CH切片缺失/变更/歧义、错商品/版本/范围/摘要拒绝；不重复存K线实体到PG。
- 退役：源码/依赖树/构建/测试/活动文档无业务SQLite，原经济正确性与权限门禁仍有效。
- benches：纯计算与完整内存交易、CH输入准备、PG发布/读取/正式事实恢复分口径；冻结代码、机器/存储、输入、样本和缓存条件。无新增吞吐硬阈值，不用旧SQLite基线声称收益。
- 本地DB/OpenAPI/Web测试只通过固定dev入口。受影响的正常Web工作流、API、示例和生成类型一并验证；新的正式Web取证预算另按实际任务约定，不在本设计自动启动。
- 高风险业务持久化/恢复/身份/门禁由实现者之外的审查者独立核对；设计评审不代替实施回归。

资源压力、Docker失响应、连续异常超时按AGENTS停止；同一问题三次失败停止，保留证据。不放宽门禁或吞错误取得通过。

## Constitution Impact

NO。正式事实有唯一归属，重算不产生第二Run/冲突发布；计算候选可丢但关键控制与已发布事实不只存在内存；Sim/Live资金与订单事实可恢复；版本/输入显式绑定且UNKNOWN不盲重试；权限/市场适配边界保留。此设计不改变实盘必须人授权的规则。

## 实施计划

详见[分阶段详细实施计划](../plans/2026-11-14-research-backtest-pg-memory-framework.md)。计划不代表业务实施、测试或独立审查已完成。
