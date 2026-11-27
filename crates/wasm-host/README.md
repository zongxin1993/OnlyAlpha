# onlyalpha-wasm-host

## 目的与职责

本库实现 [ADR 0152](../../docs/adr/0152-unified-runtime-dual-kernel-operators-qlib-dag-and-wasm-plugins.md) 阶段 2 定义的 L3 WebAssembly 确定性插件宿主、版本化 WIT 契约校验器、扩展算子双内核自动准入认证器与运行期热加载／热卸载管理器。

- 配置确定性 `wasmtime` 引擎（启用 Component Model、fuel 计量与 Cranelift NaN 规范化；关闭 threads、relaxed SIMD、memory64、epoch interruption 与 debug info）。
- 严格封禁一切 WASI 与隐式外部导入，并在编译加载阶段静态校验导出的 WIT 接口名、函数集合与完整递归参数／返回值签名（`contracts/wasm/v1/onlyalpha-plugin.wit`，`onlyalpha:plugin@1.0.0`），拒绝多余导出与异步组件函数。
- 为每次调用设置显式线性内存上限、燃料配额与宿主侧 Component Model lifting 内存配额（`hostcall_fuel`），对 trap、越界、内存超限、lifting 超限与燃料耗尽执行 Fail-Closed 隔离，确保宿主进程与其余插件状态不受影响。
- 严格按 `DECIMAL28_HALF_EVEN_Q12_V1` 普通十进制字符串格式校验跨边界数值（拒绝科学计数法、`-0`、空白及精度／标度越界）。
- `CertificationRequest::golden_cases` 必须提供独立计算的参考输入和预期，并至少包含一个有效数值。准入器同时检查双内核逐点等价、多前缀因果、warmup／null、燃料确定性，以及在新实例和已有状态上恢复快照的结果。`max_certification_fuel` 约束从首次实例化起的整轮客体执行，包含读取元数据和拒绝损坏快照所消耗的燃料。全部检查通过后签发 `ReadyCertificate`，其摘要绑定参考用例的输入与预期。
- 管理扩展算子、市场规则与策略三类 L3 插件的运行期热加载、精确 SHA-256 与参数绑定回放校验、热卸载与线性内存回收统计。

## 边界与依赖

- **拥有**：L3 WASM 确定性执行沙箱、版本化 WIT 契约校验、扩展算子双内核自动认证与 `ReadyCertificate` 签发、插件运行期热加载／热卸载管理、线性内存与隔离故障计量。
- **不拥有**：L1 内置算子数值语义（归属 `onlyalpha-operators`）、L2 声明式因子表达式的编译与执行（归属 `onlyalpha-calculation`）、L4 券商与数据源子进程插件协议、HTTP／WS 路由、持久化存储、风控准入、订单身份或实盘人工授权门槛。
- **直接依赖**：`onlyalpha-domain`（策略输入输出与账户只读视图的交易值对象，见 `onlyalpha_domain::strategy`）、`onlyalpha-operators`、`wasmtime`（仅启用 `cranelift`、`runtime`、`std`、`component-model`，不含任何 `wasmtime-wasi`）、`sha2`、`serde_json`；测试依赖 `wat` 与 `wit-parser`。全库遵守 workspace `unsafe_code = "forbid"`。

## 公开接口

公开入口位于 [src/lib.rs](src/lib.rs)：

- 配置与指标（[src/config.rs](src/config.rs)）：`ResourceBudget`、`WasmHostEngine`、`HostMetricsSnapshot`、`MIN_MEMORY_BYTES`、`HARD_MAX_MEMORY_BYTES`、`HARD_MAX_ARTIFACT_BYTES`、`MIN_HOST_LIFT_BYTES`、`HARD_MAX_HOST_LIFT_BYTES`、`HARD_MAX_SNAPSHOT_BYTES`、`HARD_MAX_OUTPUT_ITEMS`、`HARD_MAX_TABLE_ELEMENTS`、`HARD_MAX_INSTANCES`、`HARD_MAX_TABLES`、`HARD_MAX_MEMORIES`、`HARD_MAX_FUEL_PER_CALL`、`HARD_MAX_CERTIFICATION_FUEL`。
- 契约与绑定（[src/contract.rs](src/contract.rs)）：`WIT_CONTRACT_VERSION`、`HOST_RUNTIME_VERSION`、`EXTENDED_OPERATOR_INTERFACE`、`MARKET_RULE_INTERFACE`、`STRATEGY_INTERFACE`、`NUMERIC_POLICY`、`MAX_DECIMAL_PRECISION`、`MAX_DECIMAL_SCALE`、`MAX_CANONICAL_PARAMETERS`、`MAX_PARAMETER_KEY_BYTES`、`MAX_PARAMETER_VALUE_BYTES`、`PluginKind`、`ArtifactBinding`、`ReadyCertificate`、`CallOutcome`、`OperatorMetadata`、`MarketRuleMetadata`、`MarketRuleInput`、`MarketRuleDecision`、`StrategyMetadata`、`Error`、`Result`、`sha256_hex`、`is_valid_sha256_hex`。
- 插件句柄与认证（[src/operator_plugin.rs](src/operator_plugin.rs)、[src/certification.rs](src/certification.rs)、[src/market_rule_plugin.rs](src/market_rule_plugin.rs)、[src/strategy_plugin.rs](src/strategy_plugin.rs)）：`WasmExtendedOperator`（实现 `onlyalpha_operators::execution::VectorKernel`）、`WasmOperatorStream`、`MAX_OPERATOR_ARITY`、`MAX_OPERATOR_WARMUP`、`MAX_VECTOR_CELLS`、`CertificationRequest`、`GoldenCase`、`WasmMarketRulePlugin`、`WasmStrategyPlugin`。
- 热插拔生命周期管理（[src/manager.rs](src/manager.rs)）：`WasmPluginManager`、`LoadedPluginSummary`、`UnloadReceipt`。

所有沙箱、契约、认证与绑定错误均通过 `Error` 以 Fail-Closed 语义返回，不触发宿主进程 panic 或状态污染。

## 状态与生命周期

- `WasmPluginManager` 以 `RwLock<BTreeMap<String, LoadedEntry>>` 持有当前已加载的已编译组件与元数据；扩展算子仅在自动双内核认证全部通过并签发 `ReadyCertificate` 后方可注册为 READY。
- 每次向量求值、市场规则校验和策略 `on_event` 均在独立的全新 `wasmtime::Store<SandboxState>` 中运行，调用结束后立即销毁 Store 并回收全部线性内存。
- `WasmOperatorStream` 独占一个隔离 `Store`，保存增量事件状态，支持 `capture_state`／`restore_state` 跨新实例确定性恢复；`WasmPluginManager::unload` 从注册表移除插件并报告剩余引用。已有事件流继续持有自己的 Store，释放后可通过 `HostMetricsSnapshot::live_linear_memory_bytes` 核对内存回收。
- 历史回放通过 `ArtifactBinding` 核对 `.wasm` SHA-256、WIT 契约版本、宿主执行契约版本与规范参数。准入或执行语义变化会改变宿主执行契约标识；WIT 版本单独绑定客体接口。

`load_strategy` 在加载时冻结规范参数。回放时将保存的完整 `ArtifactBinding` 传给 `get_strategy`，管理器在同一把读锁内核对绑定并返回句柄。`on_event` 接收与 `required_factors` 逐名匹配的因子和只读账户状态，始终使用句柄自己的参数。同一插件 ID 卸载后以其他参数重载，已有句柄仍按原参数执行。

## 使用与验证

从仓库根目录运行 Rust 库单元测试，脚本通过 Cargo 的 `--lib` 目标执行本库和其他 `crates/` 库的模块自测。

```bash
python3 scripts/unit_tests.py
```

跨平台复核时，在 macOS 和 Linux 的同一份源码上分别运行以下目标。[市场规则功能测试](tests/portable_market_rule.rs) 读取随测试保存的同一份 `.wasm`，先核对 SHA-256，再逐字段核对买入放行和卖出拒绝的结果。

```bash
cargo test --locked -p onlyalpha-wasm-host --test portable_market_rule
```
