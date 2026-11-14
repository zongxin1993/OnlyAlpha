# ADR 0151：PostgreSQL 业务发布与内存 Research／回测

- 状态：Accepted，负责人于2026-11-14确认总体设计；已授权详细规划，已授权第一阶段契约与接口实施；后续阶段未启动
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
