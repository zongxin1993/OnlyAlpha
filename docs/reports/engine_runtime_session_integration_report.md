# Engine Runtime Session 架构收敛集成报告

## 本次新增组件

- 原生单 Cluster `OnlyClusterRunConfig`
- 内部 `OnlyRuntimeAssemblyPlan`
- `OnlyRuntimeCompatibilityKey`、`OnlyRuntimePlan`、`OnlyEngineExecutionPlan`、`OnlyRuntimePlanner`
- `OnlyRuntimeSession`、`OnlyClusterSession`

## 接入的 Vertical Slice 位置

```text
CLI -> OnlyEngine -> ClusterDefinition -> RuntimePlanner -> RuntimeSession -> ClusterSession
-> Synthetic Historical Source -> Replay -> Factor/Strategy -> Risk/Order -> Virtual Broker
-> ExecutionProcessor -> Position/Allocation/Ledger/Account -> Engine Result -> user_data
```

## 复用的已有组件

复用 Runtime/Cluster/DataSource/Broker Factory、Synthetic Source、Historical Replay、Virtual Broker、MarketData Pipeline、
Risk、Order、ExecutionProcessor、Position、Allocation、Strategy Ledger、Account 和 `OnlyUserDataLayout`。未复制或旁路交易链。

## 新增场景

- 原生单 Cluster 配置且无 `run_config` 包装
- 拒绝 `clusters[]`
- add_cluster 无 Runtime 构建/关闭副作用
- 兼容 Cluster Runtime 分组、不兼容 Cluster 拆分
- Engine initialize 后持有真实 RuntimeSession/ClusterSession
- Engine 源码不使用 RunService 或旧 merge
- runtime plan、normalized config、fingerprint 全部输出到 user_data
- stop 幂等

## 修改场景

该阶段核心 MACD 回归曾使用 `tests/runtime_support/macd_plugin.py`。后续 Plugin SPI 重构已将其迁入独立安装的测试
distribution，并通过 Entry Point/公共注册接口加载；原信号、T+1、订单 ID、结果扩展和确定性预期保持不变。

## 历史场景运行结果

全仓 `uv run pytest -q`：304/304 PASS。

## 组件单元测试结果

Config、Planner、Session、Lifecycle、Output 目标测试 PASS。

## 直接集成测试结果

Engine -> Planner -> Assembler -> Runtime/Cluster Session 测试 PASS。

## 全链路测试结果

单 Cluster与多 Cluster Synthetic/Virtual Broker 正式 CLI 均 COMPLETED；完整 Vertical Slice 34/34 PASS。双 Cluster 共享
`backtest-ebfcd998d9293216` Runtime，Cluster 输出保持隔离。

## 确定性重放结果

历史 MACD Runtime 指纹保持 `bcc238d9724e49801a7ed4f148e3f3b64dad2da5bc827d0138a09e636b1a1d13`；
Engine 单/多 Cluster 重放断言 PASS。

## 关键不变量检查

Runtime/Cluster Scope、事件顺序、订单状态、重复 Fill、Reservation、Position/Allocation、Ledger/Account、T+1、Cash/PnL
对账和相同输入确定性均由历史 Vertical Slice 覆盖并通过。

## 使用的 Placeholder/Fake

Synthetic Historical Source 和 Virtual Broker 是正式内建确定性实现。核心动态组件使用明确的 Test Adapter；没有未标明 Fake。

## 尚未接入的真实能力

真实数据源、真实 Broker、Paper/Live 热加载、Entry Point 插件发现均不在本任务范围。

## 发现的回归

未发现架构或业务回归。

## 已知限制

- 后续接口唯一性清理已迁移历史 Runtime 测试并删除旧配置名称与运行服务；本条仅记录当时阶段状态。
- 三仓目录已建立；官方 Strategy、Factor、扩展组件、Cluster 配置与真实基础设施适配器迁入 OnlyAlpha-plugins 属于后续任务。
- Paper/Live/Research 产品循环仍未实现。

## 是否允许进入下一组件

当前结论：**ACCEPTED**。全仓 Pytest、Ruff lint、Ruff format check、strict Mypy 和正式 CLI 门禁全部通过。
