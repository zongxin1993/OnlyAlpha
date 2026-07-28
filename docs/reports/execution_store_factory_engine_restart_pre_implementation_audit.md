# Execution Store Factory 与 Engine Restart 预实现审计

日期：2026-07-28
基线：`418636a Feat: Ready Query、Runtime Recovery Hook 与真实故障矩阵`

## 结论

当前产品链为 `OnlyEngine.initialize()` → `OnlyEngineRunAssembler.build()` →
`OnlyBacktestRuntimeFactory.create()` → `OnlyBacktestRuntime(...)`。Factory 没有创建或注入 Execution Transaction
Store；`OnlyBacktestRuntime.__init__()` 以
`execution_transaction_store or OnlyInMemoryExecutionTransactionStore()` 隐式创建进程内 Store。因此现有正式产品链不能重新打开
SQLite transaction tail。

## 强制问题审计

1. `OnlyEngine` 的 `user_data` 来自 `OnlyEngineConfig.user_data_root`。`OnlyEngine.run()` 当前以随机
   `run-{uuid4().hex}` 生成一次性 Run ID，并由 `OnlyUserDataLayout.run_root()` 写入
   `user_data/runs/<engine-id>/<run-id>`。
2. `OnlyEngineRunAssembler.build()` 已把 `user_data_root` 放入 `OnlyRuntimeBuildRequest`，所以 Runtime Factory 能获得
   user_data 根目录；当前没有 Runtime 专属 state 目录 API，只有 artifact 的 `run_root()`/`cluster_root()` 和行情缓存目录。
3. `OnlyRuntimeConfig` 当前只有 engine/runtime identity、runtime type、时间、base currency 与 `extensions`，没有正式
   Execution Store 配置。
4. Core 没有可复用的通用 Storage Backend 枚举。`onlyalpha.storage` 只有通用 `OnlyStorage` port 和 SQLite 实现，不能表达
   Execution Transaction Store 的 MEMORY/SQLITE 产品语义。
5. `OnlySqliteExecutionTransactionStore.__init__()` 直接 `sqlite3.connect()` 并执行两个
   `CREATE TABLE IF NOT EXISTS`；`close()` 直接关闭 connection。`OnlyInMemoryExecutionTransactionStore` 没有统一的
   `close()`。
6. Store 当前没有 schema version 或 metadata table，只以业务表是否存在作为隐式 schema。
7. Runtime 当前不拥有 Store 生命周期。Store 只通过多个窄 port 放入 `OnlyRuntimeServices`。
8. `OnlyRuntime.close()` 依次 stop、unload Cluster、关闭插件、EventBus 与 Clock，不关闭 Execution Store。
9. `OnlyBacktestRuntimeFactory.validate()` 调用 `_plugin_plan()`，会构造 Clock/EventBus 并关闭，但当前不创建 Store 文件。
   新 Store 校验必须保持无 state 目录、SQLite、metadata 副作用。
10. `OnlyEngine.initialize()` 会关闭已加入 `created` 的 Runtime；但 Store 若在 Runtime 构造完成前创建失败，当前没有任何
    Store 清理责任。新的 Factory 必须在 Runtime 接管前关闭已创建 Store，接管后由 Runtime/Engine cleanup 关闭。
11. `tests/runtime/test_execution_runtime_recovery_sqlite_restart.py` 直接替换
    `runtime._services` 中的 coordinator/recovery/query/projection/outbox，清空
    `cluster_manager._clusters`，清空 diagnostics 并把 `runtime._state` 改回 `CREATED`。该测试只能证明预建 authority 的
    Runtime hook，不是产品 Engine restart。
12. 当前 bootstrap authority 由 `OnlyBacktestRuntimeFactory._plugin_plan()` 编译 market/fee/runtime 配置，
    `OnlyBacktestRuntime.__init__()` 创建 Account 与各 Runtime Manager，`OnlyEngine.initialize()` 之前的
    `runtime.register_instrument()` 和 `runtime.add_cluster()` 创建 Instrument、Cluster Ledger 和 Risk binding。
13. 仅凭配置不能重建动态 Order submit/accepted 状态、Risk Reservation、Account/Strategy cash Reservation、Position
    Reservation，以及成交前由行情产生的 valuation/version。Account 初始现金和 Cluster Ledger 初始资本可重建；成交后的
    Account、Ledger、Position、Allocation、Fee、Settlement 也不能在没有 transaction tail 或 snapshot 时凭配置重建。
14. 合法的真实重启场景只能在 durable commit 后、第一项 Projection 前中断，并要求同一正式产品配置能重建 transaction 的
    Expected/Before authority。若 Order/Reservation 不能由现有配置重建，必须增加最小、公开、强类型的 Backtest bootstrap
    输入边界；不得复制旧 Runtime、修改私有字段或把 Manager 对象 pickle 化。
15. `OnlyEngine` 是单次使用对象，但新的 Engine 可使用同一 `OnlyEngineId` 与同一配置。Run ID 在 `run()` 尾部随机新建，因此
    不存在“复用同一个 Run ID”的产品入口，也不应让 recovery state 依赖 Run ID。
16. Artifact Run Directory 与可恢复 Runtime State Directory 必须分离：前者保留当前
    `runs/<engine-id>/<run-id>`，后者应由 `OnlyUserDataLayout` 以稳定 engine/runtime identity 定位，并禁止时间、UUID、Run ID
    和 Cluster ID 作为主隔离键。

## 恢复场景与故障点冻结

产品恢复测试采用实现正式 Store Factory port 的测试 decorator，在 `commit()` 已成功持久化 transaction/outbox 后、Coordinator
开始第一项 Projection 前抛出受控异常。Engine A 必须通过 `OnlyEngine` 和正式 Backtest Runtime Factory 创建 SQLite Store；Engine B
是全新 Engine，使用相同配置和 user_data，由 Factory 自动重开 Store，`initialize()` 自动恢复，`start()` 在 Cluster 前发布
recovered Outbox。

当前能力仍严格定义为“正确 Bootstrap/Before Authority + ordered committed transaction tail”，不是 Full Bootstrap Snapshot、Empty
Runtime Recovery 或通用进程恢复。该结论与 ADR 0040、0041、0042 一致。
