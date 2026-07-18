# OnlyAlpha 新旧运行架构收敛任务

## 任务目标

基于 OnlyAlpha 当前最新源码，解决以下架构叠加问题：

```text
新产品入口：
CLI
→ OnlyEngine
→ add_cluster()
→ run()

当前内部实际链路：
OnlyClusterRunConfig
→ 旧 OnlyRunConfig
→ 合并 clusters
→ OnlyEngineRunService
→ RuntimeAssembler
→ 一次性运行并关闭
```

最终必须收敛为：

```text
CLI
→ OnlyEngine
→ OnlyClusterRunConfig
→ Runtime Planning
→ RuntimeSession
→ ClusterSession
→ Engine.run()
```

`OnlyEngine` 必须真正负责 Cluster、Runtime 和基础设施的生命周期，不得继续只是旧 `OnlyEngineRunService` 的包装层。

---

## 一、执行原则

开始修改前，必须完整阅读当前实际代码，重点检查：

```text
src/onlyalpha/cli.py
src/onlyalpha/engine/
src/onlyalpha/config/
src/onlyalpha/runtime/
src/onlyalpha/cluster/
src/onlyalpha/output/
src/onlyalpha/data/synthetic/
src/onlyalpha/broker/virtual/
tests/
```

所有修改必须基于当前接口完成，不得建立第三套平行架构。

本任务只处理架构收敛，不处理：

```text
外部插件仓库拆分
Entry Point 插件发现
真实券商接入
真实数据源接入
Paper/Live 热加载
策略示例仓库迁移
```

---

## 二、原生单 Cluster 配置

重构 `OnlyClusterRunConfig`，使其成为真正的单 Cluster 配置模型。

禁止继续使用：

```python
class OnlyClusterRunConfig:
    run_config: OnlyRunConfig
```

禁止在解析时重新构造：

```python
{"clusters": [cluster_payload]}
```

目标模型必须直接包含：

```text
schema_version
cluster
runtime
reference_data
universes
data_sources
accounts
brokers
strategy
factors
output
```

一个配置文件只能定义一个 Cluster。

发现旧格式：

```yaml
clusters:
  - ...
```

必须明确报错，不得静默兼容。

---

## 三、消除旧 OnlyRunConfig 产品职责

检查当前 `OnlyRunConfig` 的所有调用位置。

将其处理为以下两种方式之一：

### 优先方案

完全删除产品运行路径中的 `OnlyRunConfig`。

### 可接受方案

将其改造成纯内部规划对象，并重新命名，例如：

```text
OnlyRuntimeAssemblyPlan
OnlyRuntimeGroupPlan
```

内部规划对象不得再承担：

```text
用户配置文件解析
Cluster 配置领域模型
CLI 输入模型
多个 Cluster 的配置容器
```

不得通过将多个单 Cluster 配置重新合并成旧 `clusters` 数组来运行。

---

## 四、Engine 运行模型

重构 `OnlyEngine`，明确区分：

```text
ClusterDefinition
ClusterSession
RuntimeSession
```

建议结构：

```python
class OnlyEngine:
    _cluster_definitions: dict[OnlyClusterId, OnlyClusterRunConfig]
    _cluster_sessions: dict[OnlyClusterId, OnlyClusterSession]
    _runtime_sessions: dict[OnlyRuntimeId, OnlyRuntimeSession]
```

### ClusterDefinition

表示不可变的 Cluster 配置定义。

### ClusterSession

至少持有：

```text
cluster_id
cluster instance
runtime_id
state
resource references
configuration fingerprint
```

### RuntimeSession

至少持有：

```text
runtime_id
runtime instance
compatibility key
bound cluster ids
state
```

不得只保存 Config 和 Handle，然后在 `run()` 中重新构造全部对象。

---

## 五、add_cluster 语义

保留：

```python
engine.add_cluster_from_file(path)
engine.add_cluster(config)
```

其中：

```text
add_cluster_from_file()
```

只能负责文件读取和配置解析，最终必须调用：

```text
add_cluster(config)
```

启动前调用 `add_cluster()` 时，应完成：

```text
配置校验
Cluster ID 去重
资源冲突检查
Runtime Compatibility 规划
Cluster Definition 注册
```

可以延迟创建真实运行实例到 `initialize()` 或 `run()`，但不得调用 RuntimeAssembler 创建后立即关闭，仅用于模拟验证。

需要验证装配时，应提供独立的无副作用验证逻辑。

---

## 六、Engine 生命周期

统一 Engine 状态：

```text
CREATED
CONFIGURING
READY
RUNNING
STOPPING
STOPPED
FAILED
```

建议运行链路：

```python
def run(self) -> OnlyEngineRunResult:
    self.initialize()
    self.start()

    try:
        return self._run_runtime_sessions()
    finally:
        self.stop()
```

### initialize()

负责：

```text
根据 Cluster Definitions 生成 Runtime Plan
创建 RuntimeSession
创建 ClusterSession
绑定 Cluster 与 Runtime
初始化共享基础设施
```

### start()

负责：

```text
启动基础设施
启动 Runtime
启动 Cluster
```

### run()

负责：

```text
协调一个或多个 RuntimeSession 执行
等待回测 Runtime 完成
汇总运行结果
```

### stop()

必须按逆序关闭：

```text
Cluster
→ Runtime
→ Broker/DataSource
→ Output
```

关闭必须幂等。

---

## 七、Runtime Planning

实现明确的 Runtime Planner，不得继续依赖旧 RunConfig 合并行为。

至少定义：

```text
OnlyRuntimeCompatibilityKey
OnlyRuntimePlan
OnlyEngineExecutionPlan
```

Runtime Compatibility Key 至少考虑：

```text
runtime_type
start_time
end_time
clock policy
replay policy
data version
broker environment
account environment
```

兼容的 Cluster 可以进入同一个 Runtime Plan。

不兼容的 Cluster 必须创建不同 RuntimeSession。

不得仅根据 `runtime_type == BACKTEST` 强制共享 Runtime。

---

## 八、RuntimeAssembler 职责

可以继续使用现有 `RuntimeAssembler`，但必须修改其职责。

RuntimeAssembler 应接受明确的 Runtime Plan：

```text
OnlyRuntimePlan
→ RuntimeSession
```

不得接受旧的多 Cluster 用户配置文档。

不得在 Engine 外部直接控制完整产品运行。

RuntimeAssembler 只负责对象装配，不负责：

```text
CLI
Engine 生命周期
配置文件读取
运行结果汇总
Cluster 注册
```

---

## 九、Infrastructure Registry

保留现有配置指纹、资源冲突检查和引用计数能力。

本任务至少要求：

```text
Engine 初始化时按 Runtime Plan 获取资源
相同资源 ID 且配置一致时允许复用
相同资源 ID 但配置不一致时失败
ClusterSession 记录资源引用
Engine 停止时按引用关系释放资源
```

本任务不强制完成 Paper/Live 动态资源热插拔，但接口不得阻碍未来实现。

---

## 十、输出系统收敛

所有产品运行输出必须统一通过：

```text
OnlyUserDataLayout
```

禁止保留任何默认：

```python
Path("output")
```

产品运行路径。

所有运行结果必须位于：

```text
<user_data>/runs/<engine_id>/<run_id>/
```

至少包含：

```text
manifest
engine summary
runtime results
cluster results
normalized configs
configuration fingerprints
```

旧 Exporter 如果仍被内部使用，必须改为接收 `OnlyUserDataLayout` 生成的路径。

不得由旧 RunService 和新 Engine 分别输出两套结果。

---

## 十一、旧接口处理

检查以下旧入口：

```text
OnlyEngineRunService
only_default_run_service()
旧 Engine.register_runtime()
旧 Engine.start()
旧 Engine.stop()
旧 RunConfig 产品入口
```

处理原则：

1. 产品 CLI 不得再调用它们；
2. 新 Engine 不得再委托旧 RunService 完成运行；
3. 无外部用途的接口直接删除；
4. 暂时保留的接口必须标记 deprecated；
5. 测试必须迁移到新 Engine 产品链路；
6. 不得长期保留两个功能等价的运行入口。

---

## 十二、必须保持通过的完整回测

使用核心内建：

```text
Synthetic Historical DataSource
Virtual Broker
Backtest Runtime
```

通过正式 CLI 跑通：

```bash
uv run onlyalpha run \
  --config <synthetic-cluster-config> \
  --user-data ./user_data
```

完整链路必须包含：

```text
CLI
→ OnlyEngine
→ ClusterDefinition
→ RuntimePlan
→ RuntimeSession
→ ClusterSession
→ Synthetic DataSource
→ Historical Replay
→ MarketData Pipeline
→ Indicator
→ Factor
→ Strategy
→ Order
→ Risk
→ Virtual Broker
→ Matching
→ ExecutionProcessor
→ Position
→ Ledger
→ Account
→ Engine Result
→ user_data
```

不得：

```text
CLI 直接调用 RunService
Engine 将配置重新合并为旧 OnlyRunConfig
Strategy 手工构造成交
测试绕过 Virtual Broker
测试绕过 ExecutionProcessor
使用独立 Demo 脚本代替 CLI
```

---

## 十三、多 Cluster 验收

必须通过：

```bash
uv run onlyalpha run \
  --config <cluster-a.yaml> \
  --config <cluster-b.yaml> \
  --user-data ./user_data
```

验证：

```text
两个配置分别对应一个 ClusterDefinition
Engine 生成正确 Runtime Plan
兼容 Runtime 正确复用
不兼容 Runtime 正确拆分
ClusterSession 相互隔离
Strategy、Factor、Indicator 状态相互隔离
输出目录按 cluster_id 隔离
不存在旧 RunConfig 合并执行
```

---

## 十四、测试要求

至少增加或更新：

```text
test_cluster_run_config_is_native_single_cluster
test_cluster_config_rejects_clusters_array
test_engine_add_cluster_does_not_build_and_close_runtime
test_engine_creates_cluster_sessions
test_engine_creates_runtime_sessions
test_runtime_planner_groups_compatible_clusters
test_runtime_planner_separates_incompatible_clusters
test_engine_run_does_not_use_legacy_run_service
test_single_cluster_synthetic_virtual_backtest
test_multi_cluster_synthetic_virtual_backtest
test_all_outputs_use_user_data_layout
test_engine_stop_is_idempotent
```

必须运行：

```bash
uv run pytest
```

不得删除、跳过或放宽已有测试来获得通过。

---

## 十五、完成标准

任务只有同时满足以下条件才算完成：

```text
OnlyClusterRunConfig 不再包装 OnlyRunConfig
单 Cluster 配置不再转换为 clusters 数组
OnlyEngine 不再调用旧 OnlyEngineRunService
engine.run() 不再重新合并旧 RunConfig
Engine 持有 RuntimeSession 和 ClusterSession
Runtime Planning 有明确模型
RuntimeAssembler 只负责装配
所有输出统一进入 user_data
单 Cluster 回测通过
多 Cluster 回测通过
Synthetic DataSource 和 Virtual Broker 完整链路通过
全部测试通过
```

---

## 十六、一票否决项

出现以下任一情况，任务判定为失败：

```text
保留新旧两套产品运行入口
OnlyClusterRunConfig 仍持有 OnlyRunConfig
多个配置仍被合并为旧 clusters 数组
Engine 仍只是 RunService 包装器
add_cluster 仍创建 Runtime 后立即关闭
engine.run() 仍重新装配整套旧运行模型
Engine 不持有真实 Session
CLI 绕过 Engine
回测绕过 Virtual Broker
输出仍可能写入 output/
通过删除或跳过测试掩盖问题
```

---

## 十七、最终输出

完成后提供简洁报告，包含：

```text
删除或废弃的旧接口
新增的配置模型
新增的 RuntimePlan
新增的 RuntimeSession
新增的 ClusterSession
Engine 生命周期变化
RuntimeAssembler 职责变化
输出系统变化
单 Cluster 回测结果
多 Cluster 回测结果
全部测试结果
剩余兼容层及删除计划
```

不要只提交设计文档。必须完成代码修改、测试和正式 CLI 回测验证。
