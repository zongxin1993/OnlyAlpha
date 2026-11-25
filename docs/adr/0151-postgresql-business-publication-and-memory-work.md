# ADR 0151：PostgreSQL 业务发布与内存 Research／回测

- 状态：Accepted；负责人于 2026-11-14 确认总体设计，2026-11-17 确认开发阶段不保留历史兼容的实施准则
- 日期：2026-11-14
- 决策人：仓库负责人
- Constitution Impact：NO
- 相关：ADR0068、0072、0089、0090、0091、0133、0134、0136、0148、0150

## 背景

当前Runtime与虚拟券商依赖SQLite，Research/Backtest通过文件式证据与SQL控制状态跨介质发布，读取/完成检查重复恢复和验证历史。负责人明确要求：业务发布、控制和留存统一PostgreSQL，K线ClickHouse，过程历史内存；有限作业发布前中断按冻结输入重算；不做旧接口/格式兼容，复用本机Docker Compose dev，不增加额外存储体系或无必要依赖。

## 决策

1. PostgreSQL是需发布/控制/留存业务内容的持久归属，含正式研究/回测结果与必要证据。K线实体留在ClickHouse，PG保留精确引用与摘要。
2. Research/Backtest在内存计算，未发布结果为候选，不能用于Freeze、Qualification或Promotion。PG保留Run、冻结输入、Attempt/lease/fence及取消/失败控制事实。
3. 发布前进程丢失时，原Run可以由新有效Attempt从精确冻结输入重算；不能选择最新数据/实现或制造第二Run。重算不是无限重试。
4. 真实执行owner确认结束、drain、经济不变量及精确绑定后，一个PG事务提交全部正式结果、唯一发布记录和Run/Attempt终态。COMMIT未知只观察原身份，不用FAILED掩盖未知。
5. Sim/Live的订单、成交、资金等正式业务事实仍须PG逐步持久化。回测与持续交易共用经济Kernel，持久化能力在Driver/基础设施组合，不在经济规则内按运行模式分叉。
6. 首版取消终态只留状态与原因，不发布部分结果；已正式完成的结果不因迟到取消撤销。取消意图/完成竞争沿正式领域状态机和受控事务裁定。
7. 退役全部业务SQLite依赖、文件型业务journal及相应读写/恢复路径；不以旧格式reader、fallback或别名提供兼容。既有原经济事实语义、权限和UNKNOWN安全路径保留。
8. 不建设独立封闭文件事实库、追加文件发布账本、fs-verity能力要求或额外Linux环境；不新增数据库/存储服务。继续固定本机onlyalpha-dev，PostgreSQL/CH及工具缓存复用。

9. Research与交易共用纯信号层，只依赖行情、因子及显式参数；仓位、资金、风险、成交和提交意图在后续交易环节。该分层细化ADR0150的策略能力，不新增第二份信号实现。构建认证与每次作业实际输入校验分别负责，精确参数独立认证，不逐行解析AST。

## 替代范围与保留范围

本决策明确替代ADR0089中PG不得保存正式结果/Artifact内容的存储边界、ADR0091中PG-free Artifact读平面及内容在PG外的要求，以及ADR0090中跨介质semantic-commit再SQL-finalize的顺序。替代Backtest活动契约中后续Attempt必须Resume原SQLite、禁止从头重算和文件先发布再SQL终态的要求。

保留Run/Attempt身份分离、幂等、lease/fence及其时钟职责、取消/失败领域规则（部分结果留存按本文新决定）、精确数据/程序绑定、市场无关经济语义、可恢复正式事实、发布前真实执行证明、禁止盲重试和实盘人授权。Dataset身份规则保留，介质由CH实体和PG绑定表达。

不修改PROJECT_CONSTITUTION.md及其指纹。不覆盖已发布迁移字节，schema通过正式迁移机制演进。旧ADR保留历史身份，本ADR不把历史调查或CI结果变为验收Authority。

## 后果与验证

有限作业不再逐Bar写盘或恢复过程历史；未发布工作可以丢失，已发布结果与关键控制不能只在内存。内存模型必须消除旧每步完整状态副本，不能把SQLite表机械换成Vec。

公开调用、私有资产示例、生成契约、测试、bench、镜像构建、Source检查和依赖门禁须同步退役旧接线。高风险PG发布/恢复与身份证明必须取得真实固定环境回归及独立审查；设计批准不代表代码已实现。

完整方案见[框架设计](../superpowers/specs/2026-11-14-research-backtest-pg-memory-framework-design.md)。

## 单次 SIM 运行准入归属

负责人于 2026-11-24 确认，**单次 SIM 运行的准入决定由 Rust 后端应用层的「启动 SIM」生命周期命令作出**。人或已获相应权限的 Agent 通过正式 API 发起请求。命令核验发起主体的权限、指定策略版本的 `BACKTEST_TO_SIM` 晋级证据、目标模拟账户和虚拟券商配置，将准入决定及上述绑定连同本次 Run、Generation 持久化到 PostgreSQL。策略晋级证据的归属见 [ADR 0118](0118-evidence-backed-qualification-and-promotion-authority.md)。

后端 SIM Driver 在接手与重启恢复时读取原 Run 的准入记录，核验本次执行与原绑定一致。逐单派发仍须通过风控、确认原意图和 outbox 已正式提交、核验投影就绪，再向绑定的虚拟券商派发。节点写锁证明连接持有写权，仓储回执证明对应事实已提交，两者均不能授予运行准入。此决定仅适用于 SIM；LIVE 授权依照[项目宪章](../../PROJECT_CONSTITUTION.md)。

### 模拟账户与虚拟券商配置的精确读取

负责人于 2026-11-24 确认以下 SIM 契约。Rust 后端应用层管理模拟账户定义，在 PostgreSQL 发布不可变账户修订。账户具有稳定的 `account_id`，每份修订记录部署、计价币种、开户资金和绑定的券商 Integration 实例。后端 Integration 配置模块管理该实例已发布的配置修订，虚拟券商插件负责撮合、滑点和延迟等参数的解析与规范化。每次 Run 固定本次使用的账户修订和券商配置修订。配置修订的产品归属及插件解析职责见 [Integration 配置契约](../integration_type_configuration_contract.md)。

启动命令在同一 PostgreSQL 事务 `tx` 中按下表读取两份修订。主体取自认证上下文，券商实例 ID 取自已核验的账户修订。

| 后端读取接口 | 精确核验与返回值 |
|---|---|
| `read_sim_account_revision(tx, deployment_id, account_id, account_revision_fingerprint)` | 核对部署、账户 ID 和已发布修订指纹。返回原账户修订及其中的计价币种、开户资金、`broker_integration_id`、允许标的（含价格/数量精度与 `multiplier`）及经风险 owner 校验的非空风控规则。 |
| `read_virtual_broker_revision(tx, integration_id, revision_fingerprint)` | 核对实例 ID、已发布修订指纹、`BROKER` 类别和虚拟券商类型。返回已核验的 Integration 修订、类型、配置正文及 `runtime_configuration_fingerprint`。 |

负责人于 2026-11-25 明确：**SIM 允许交易标的、标的精度/`multiplier` 和交易风控规则由模拟账户修订显式绑定**（不默认空风控，至少包含一条 `ENFORCING` 规则，且全部规则由风险 owner `onlyalpha-risk` 经 `onlyalpha-execution::Components` 校验与规范化，禁止覆盖或改写 `SYSTEM` / `system.*` 强制系统规则，符合 [ADR 0012](0012-risk-pipeline-profile-and-reservation.md)）。由 `SimAccountRevision::trading_binding(&self, run_id, generation, kernel, strategy, universe)` 构造单策略单 Cluster（`cluster = "strategy"`，按 [ADR 0034](0034-fixed-capital-multi-cluster-performance-authority.md) 承接原账户全部开户资金）的 SIM `TradingBinding`：`engine` 使用稳定名 `"onlyalpha-sim"`，`runtime` 取原 `run_id`（UUIDv4），`account` 取原账户 ID，`gateway` 取绑定的虚拟券商实例 ID，`generation` 取原 Generation 绑定，`profiles.strategy.revision` 取已核验策略指纹。装配前必须证明冻结策略声明的 `universe` 全部属于本账户修订批准的标的集，且生成的 `profiles.strategy.instruments` 与 `instruments` 清单仅限该批冻结且获准的标的。数据库层通过新增迁移 `0092_sim_account_trading_policy.sql` 约束现行唯一契约，不覆盖已存在迁移文件。

Human 的 `sim_start` 授权项中，`broker_configuration_fingerprint` 使用第二个接口读回的 `runtime_configuration_fingerprint`，与策略版本指纹、账户 ID 一起匹配同一主体的同一授权条目。Run 持久化账户和券商的精确修订引用，以 `revision_fingerprint` 定位原券商发布记录。装配方核验实际插件工件，使用原配置构造插件，并核对 `source_binding()` 中的工件、作用域、开户资金和规范化配置。

首次接手和重启均从已提交的 Run 准入记录重读这两份修订，核对原 Generation 和执行绑定。开户资金只用于账户初始化；恢复时从原交易事实重建资金与仓位，并与同一虚拟场所的订单和成交观察对账。多个 Run 使用同一账户时，必须证明它们接续或共享同一份账户状态。[账户与券商事实归属](0015-account-broker-ports-and-virtual-broker.md)

两个读取接口均区分三种失败：完整查询后确认修订不存在、修订归属或内容不匹配、存储不可读。工件不可读同样保留为不可核验。上述情况均阻止新增派发；恢复时保留原 Run 和订单身份，继续允许观察原单及对账。

### 回测资格指标与初始 SIM 政策契约

负责人于 2026-11-25 确认 `BACKTEST_TO_SIM` 资格评估消费的 PG 回测发布（`PG_JOB_RESULT_V1`）权威标量契约。评估器仅消费经 `onlyalpha_execution::verify_finite_backtest_result` 与 `onlyalpha_backtest::verify_finite_backtest` 全量验签后的 `VerifiedBacktestEvidence`（仅接受真实 Research Freeze 链来源，拒绝 `MANUAL_BACKTEST`），绝不在评估器内重算收益、回撤或分析指标：

- 执行完整性与计数标量（`u64`）：`backtest.execution_completed`（已验签发布恒为 `1`）、`backtest.close_curve_point_count`（`CLOSE_CURVE` 总行数，核对 `binding.market.sample_rows`）、`backtest.valuation_count`（`summary.valuation_count`）、`backtest.order_count`（`execution.order_count`）、`backtest.fill_count`（`execution.trade_count`）、`backtest.roundtrip_count`（`ECONOMIC_RESULT.body.roundtrip_count`）。
- 账户权威经济与风险标量（来自 `economic_result.runtime_performance.summary`）：`backtest.return_since_start`（8 位小数；无有效定义时为 `null`）、`backtest.maximum_drawdown`（8 位非正小数；高水位非正时为 `null`）、`backtest.net_pnl`、`backtest.realized_pnl`、`backtest.unrealized_pnl`、`backtest.fees`、`backtest.final_equity`。
- 规范化与 fail-closed 边界：全部 `observed_value` 归约为与 Policy `threshold` 一致的无尾零、无 `-0`、无科学计数法十进制串；当政策引用某经济指标而该 Run 的 `summary` 值为 `null` 时，评估边界返回 `QUALIFICATION_EVIDENCE_MISSING`；已退役的文件式计数（`backtest.artifact_count`、`backtest.implementation_count`）及未知指标继续返回 `QUALIFICATION_POLICY_UNSUPPORTED`。
- 初始 `BACKTEST_TO_SIM` 政策：命名空间策略扩展与节点启动核验同步置备并验证无盈利承诺的证据完整性政策 `experimental-sim/1`（`gate = "BACKTEST_TO_SIM"`，`missing_evidence_behavior = "FAIL"`，`aggregation = "ALL"`，要求 `backtest.close_curve_point_count GE 1` 且 `backtest.execution_completed EQ 1`）。运营方后续通过独立 `policy_id/policy_version` 置备含经济或交易阈值的严格 SIM 政策。

## 2026-11-17 开发阶段实施准则补充

负责人确认：全部任务和代码不考虑历史代码、接口、格式及开发数据兼容。遇到不兼容时，按 [AGENTS.md](../../AGENTS.md#42-开发环境重建与正式数据) 核对 `onlyalpha-dev` 资源并成套删除旧数据卷及配对状态，使用当前契约重新初始化；复用仍适用的环境和缓存。不新增旧格式 reader、fallback 或数据迁移兼容层。当前版本的唯一事实、确定性、权限、UNKNOWN、原子发布及恢复要求不变，不修改 Constitution。此前要求保留旧开发 Run、旧工件查询或恢复接口的实施安排不再执行；明确发行工件不覆盖，正式／真实账户数据不在开发清理范围。
