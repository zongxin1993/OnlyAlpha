# Strategy 模型

按 Accepted ADR0098，正式 Strategy 身份由 immutable Strategy Revision 定义；正常 authoring/Freeze、加载和 Runtime admission
通过各自 owning Authority 完成。旧 callback/Context adapter 不定义另一套正式策略语义。Web 只提交正式 Command 和展示结果。
同一 Revision 进入 BACKTEST / SIM / LIVE 时不得重定义语义。具体算法保留在注册的 Calculation TRADING Plugin 边界。

## Rust decision component boundary

`crates/onlyalpha-kernel/strategy/` 是可独立构建的纯语义库，依赖 Domain、Calculation 与既有 MarketData Construction 值模型。
它使用显式 Revision2 / Definition3 component contract；当前正式 Python Revision1 / Freeze reader 和 Runtime admission 保持原 Authority。
component constructor、fingerprint 和技术比较不会生成正式 Freeze、equivalence evidence 或 LIVE 权限；不提供旧历史转换、别名或 fallback。

Revision2 绑定完整 Universe、RAW Bar semantic、construction recipe、确定性 DAG、逐节点 TRADING implementation 与三个 Boolean role output。
Program 再绑定 engine/runtime/cluster、generation、source、worker artifact 和逐商品逐节点 execution binding。支持当前声明可用的 TIME_SERIES
producer；不存在的 CROSS_SECTION TRADING capability 必须明确拒绝，不能由 Research registration 推断。数值表示与身份演进见
[设计](superpowers/specs/2026-10-18-rust-strategy-execution-design.md)。

只接受 Universe 内、exact semantic、closed/revision0/RAW/end-event 的输入。相同 final observation 不重复调用节点；修订或倒序输入在 mutation
之前拒绝。按稳定图顺序传递当前输入位置的上游输出，严格检查端口类型、nullable 和 readiness；未就绪返回 BLOCKED，不能复用旧 READY。
终端 null 按已声明的 FALSE policy 处理。节点可能已消费输入后的异常、panic、UNKNOWN 或坏 receipt 使整个 owner 待恢复；禁止盲重试前序节点。

checkpoint 绑定 exact Program、完整 input prefix、accepted observation/outcome、每个节点 cursor/receipt/native state 与成功确认时保存的 state fingerprint；恢复先创建完整 fresh
candidate，再原子替换。失败候选不得改变 receiver。外部保留的 expected digest 是信任根，派生 manifest 不是认证签名。

实际 Python Plugin 调用位于 `packages/onlyalpha-calculation-worker/`。同一私有 Protobuf 传输上的封闭 node operation 仅支持 resolve/create/
update/checkpoint/fresh restore/close；没有任意方法或动态模块入口。TIME_SERIES indicator 采用自身 snapshot.ready；当前官方 operator/predicate
采用显式 warmup.minimum_observations。CONTEXT Decimal 使用现有 worker 固定 ROUND_HALF_EVEN policy，绑定在 worker artifact；不读取环境精度。

Infrastructure 的 `StrategyPreparation` 将真实 MarketData immutable plans/accepted preparation receipt 交给 Strategy；pure preparation callback
只确认 preparation，不隐藏 Strategy 状态，也不代表实际决策执行。该首个 coordinator 限定一个 Cluster、一个 primary instrument 和 exact source/
construction recipe；纯 Strategy 支持显式多商品隔离。行情和决策 checkpoint 必须关联同一 cut 并一起 fresh restore。Strategy parent 必须匹配 Pipeline 自己持有的实际 preparation receipt；末根 Bar 相等不能替代输入 prefix 相同。

该组件不拥有 Order/Risk/Portfolio/Broker、外部执行事实、持久业务历史迁移或正式 Runtime activation，也不声明 Web 产品性能已经改善。
