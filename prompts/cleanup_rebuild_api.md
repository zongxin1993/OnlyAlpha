# OnlyAlpha 重构收尾与接口唯一性清理任务

## 1. 任务目标

基于 OnlyAlpha 当前最新 `master` 代码，完成 Engine、Runtime、RunService、配置和输出系统重构后的清理收尾。

当前新产品链已经形成：

```text
CLI
→ OnlyEngine
→ OnlyClusterRunConfig
→ Runtime Planner
→ RuntimeSession
→ ClusterSession
→ Runtime
```

但仓库中仍保留部分旧接口和兼容分支，例如：

```text
OnlyEngine legacy mode
_product_mode
_legacy_runtimes
register_runtime()
OnlyEngineRunService
only_default_run_service()
旧 Runtime 级运行入口
旧 output/ 默认输出路径
旧 type 配置兼容
```

本任务必须彻底删除这些遗留。

最终目标是：

```text
OnlyEngine(OnlyEngineConfig)
→ add_cluster()
→ validate()
→ initialize()
→ start()
→ run()
→ stop()
```

这是唯一合法的产品运行链。

---

# 2. 核心架构原则

从本任务开始，OnlyAlpha 必须明确执行以下长期规则。

## 2.1 接口唯一性

同一功能只能存在一套公开接口。

禁止存在：

```text
新接口 + 旧接口
产品接口 + legacy 接口
正式入口 + compatibility 入口
同义配置字段
同义 Factory
同义生命周期方法
同义运行服务
```

例如，不允许同时存在：

```python
engine.add_cluster(...)
engine.register_runtime(...)
```

作为两个产品装配入口。

不允许同时存在：

```python
OnlyEngine.run()
OnlyEngineRunService.run()
```

作为两个运行入口。

不允许同时存在：

```yaml
plugin: synthetic
type: synthetic
```

作为两个同义配置字段。

---

## 2.2 不保留旧版本兼容

本项目当前不承担稳定公共版本兼容义务。

因此：

```text
不保留 deprecated 接口
不保留 compatibility wrapper
不保留旧参数别名
不保留旧配置字段
不保留旧构造方式
不保留旧测试辅助入口
不保留旧 Exporter 路径
```

发现旧调用时，必须迁移调用方后直接删除旧实现。

禁止使用以下方式延迟清理：

```python
warnings.warn(..., DeprecationWarning)
```

```python
def old_api(...):
    return new_api(...)
```

```python
if legacy_mode:
    ...
else:
    ...
```

```python
try:
    parse_new_format()
except:
    parse_old_format()
```

---

## 2.3 不建立过渡架构

不得为了减少修改量再创建新的过渡层，例如：

```text
LegacyEngineAdapter
CompatibilityRunService
OldConfigConverter
RuntimeCompatibilityFacade
DeprecatedOutputAdapter
```

正确处理方式是：

```text
迁移调用方
→ 删除旧接口
→ 修正测试
→ 更新文档
```

---

## 2.4 所有架构改动必须收敛

以后每次架构重构完成时，都必须执行：

```text
删除旧实现
删除旧入口
删除旧测试
删除旧文档
删除旧配置
删除旧导出
删除旧兼容逻辑
```

不得以“以后再清理”为理由长期保留多套实现。

---

# 3. 开始前检查

修改前必须读取当前实际代码，至少检查：

```text
src/onlyalpha/engine/
src/onlyalpha/runtime/
src/onlyalpha/application/
src/onlyalpha/config/
src/onlyalpha/output/
src/onlyalpha/cli.py
src/onlyalpha/__init__.py
tests/
docs/
prompts/
pyproject.toml
```

全仓搜索：

```text
_product_mode
_legacy_runtimes
register_runtime
OnlyEngineRunService
only_default_run_service
OnlyRuntimeResultExporter
root_directory
"output"
DeprecationWarning
deprecated
compatibility
legacy
"type"
plugin_id
OnlyRunConfig
```

必须识别每一个定义位置和调用位置。

不得只删除定义而留下失效引用。

---

# 4. 删除 OnlyEngine 双模式

当前 `OnlyEngine` 可能支持：

```python
OnlyEngine(OnlyEngineConfig(...))
```

以及：

```python
OnlyEngine("engine-id")
```

必须删除字符串构造和 legacy mode。

最终构造函数只能接受：

```python
class OnlyEngine:
    def __init__(
        self,
        config: OnlyEngineConfig,
        storage: OnlyStorage | None = None,
        *,
        services: OnlyEngineServices | None = None,
    ) -> None:
        ...
```

必须删除：

```text
_product_mode
_legacy_runtimes
字符串 engine_id 构造
legacy 初始化逻辑
legacy start 逻辑
legacy stop 逻辑
legacy runtimes 属性分支
```

`OnlyEngine.runtimes` 只能返回：

```python
tuple(session.runtime for session in self._runtime_sessions.values())
```

不得再根据运行模式分支。

---

# 5. 删除 register_runtime()

删除：

```python
OnlyEngine.register_runtime(...)
```

包括：

```text
方法定义
公开导出
文档说明
测试调用
示例调用
辅助 fixture
```

Runtime 不能被外部直接注册到 Engine。

唯一装配方式必须是：

```text
OnlyClusterRunConfig
→ OnlyRuntimePlanner
→ OnlyRuntimePlan
→ Runtime Factory
→ RuntimeSession
```

如果旧测试需要直接测试 Runtime 生命周期，应直接测试 Runtime，不得通过旧 Engine API 间接测试。

---

# 6. 删除 OnlyEngineRunService

删除：

```text
src/onlyalpha/application/run.py 中的 OnlyEngineRunService
only_default_run_service()
所有导出
所有调用
所有测试
所有文档
```

产品运行必须只调用：

```python
OnlyEngine.run()
```

不得保留：

```python
OnlyEngineRunService
```

作为测试工具、内部辅助或兼容入口。

如果其中仍有可复用逻辑，必须将逻辑迁移到职责正确的组件，例如：

```text
Engine
Runtime
RuntimeAssembler
ResultExporter
```

迁移完成后删除 RunService 类，而不是让 Engine 继续委托它。

---

# 7. 清理 OnlyRunConfig 遗留命名

当前产品配置模型是：

```text
OnlyClusterRunConfig
```

内部 Runtime 装配对象是：

```text
OnlyRuntimeAssemblyPlan
```

必须检查是否仍存在旧产品级：

```text
OnlyRunConfig
```

如果仅剩：

```text
OnlyRunConfigError
_OnlyRunConfigParser
```

则根据实际职责重命名。

推荐：

```text
OnlyClusterConfigError
_OnlyClusterDocumentParser
```

或：

```text
OnlyRuntimeConfigError
_OnlyRuntimeDocumentParser
```

命名必须反映当前职责。

不得继续使用已经不存在的产品概念命名。

检查并更新：

```text
import
异常类型
测试名称
文档
注释
报告
提示词
```

如果 `_OnlyRunConfigParser` 实际同时服务 Cluster 文档和内部 Runtime 配置，应拆分或重命名为中性名称，但不得复制两套 Parser。

---

# 8. 删除旧配置字段兼容

DataSource 和 Broker 配置唯一字段必须是：

```yaml
plugin: synthetic
```

禁止继续支持：

```yaml
type: synthetic
```

必须删除：

```text
type → plugin 的转换
DeprecationWarning
同时支持 type/plugin 的分支
旧字段测试
旧字段文档
旧配置样例
```

遇到旧字段必须明确失败：

```text
UNKNOWN_FIELD: type
```

或项目现有结构化配置错误。

不得自动兼容。

Runtime 本身的：

```yaml
runtime:
  type: BACKTEST
```

属于 Runtime 类型字段，不在删除范围内。

必须准确区分：

```text
runtime.type
```

与：

```text
data_sources[].type
brokers[].type
```

---

# 9. 输出系统唯一化

产品输出唯一根目录必须来自：

```python
OnlyEngineConfig.user_data_root
```

并统一通过：

```text
OnlyUserDataLayout
OnlyEngineResultExporter
```

禁止任何产品路径默认写入：

```text
./output
```

处理以下内容：

```text
OnlyOutputConfig.root_directory
OnlyRuntimeResultExporter
旧 Runtime 独立输出逻辑
默认 Path("output")
示例中的 output/
测试中的 output/
文档中的 output/
```

推荐将 `OnlyOutputConfig` 收敛为只包含运行结果格式和策略，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyOutputConfig:
    formats: tuple[str, ...] = ("JSON",)
    overwrite: bool = False
```

不得再包含能够绕过 `OnlyUserDataLayout` 的独立根目录。

最终所有产品结果必须位于：

```text
<user_data_root>/runs/<engine_id>/<run_id>/
```

包括：

```text
manifest
engine result
runtime result
cluster result
normalized config
fingerprint
logs or diagnostics
```

---

# 10. Engine 生命周期唯一化

删除 legacy 分支后，统一 Engine 生命周期。

合法状态流：

```text
CREATED
→ CONFIGURING
→ READY
→ RUNNING
→ STOPPING
→ STOPPED
```

失败进入：

```text
FAILED
```

必须保证：

```text
initialize() 只装配 RuntimeSession/ClusterSession
start() 只启动已装配会话
run() 只协调正式执行
stop() 统一逆序释放
```

禁止：

```text
Engine 根据构造方式执行不同生命周期
测试模式绕过 Session
Runtime 直接注册
RunService 代替 Engine 执行
```

---

# 11. Engine 是否允许重复运行

本任务必须明确 Engine 实例的使用语义。

推荐采用：

```text
一个 Engine 实例只允许执行一次 run()
```

即：

```text
CREATED/READY
→ RUNNING
→ STOPPED 或 FAILED
```

`STOPPED` 后不得再次：

```text
add_cluster
initialize
start
run
```

如果需要再次运行，创建新的 `OnlyEngine` 实例。

理由：

```text
避免 Session 和资源残留
避免重复 run_id 状态污染
避免 Runtime 重建语义不清
避免未来 Paper/Live 与 Backtest 语义冲突
```

必须增加明确错误：

```text
ENGINE_ALREADY_TERMINATED
```

不得隐式复用已停止 Engine。

---

# 12. Infrastructure Registry 本任务边界

本任务不重构 Infrastructure Registry 为真实实例容器。

只需要保证：

```text
删除 legacy Engine 后引用计数路径仍然正确
正常结束释放所有引用
初始化失败释放所有引用
运行失败仍释放所有引用
stop() 幂等
```

不要在本任务中同时实现：

```text
跨 Runtime 共享真实连接
动态资源实例管理
自动重连
热加载
```

这些属于后续独立任务。

---

# 13. CLI 唯一运行入口

CLI 必须保持：

```text
解析参数
→ 创建 OnlyEngineConfig
→ 创建 OnlyEngine
→ add_cluster_from_file()
→ validate() 或 run()
```

禁止 CLI 直接调用：

```text
OnlyEngineRunService
RuntimeAssembler
RuntimeFactory
Runtime.run()
ResultExporter
```

`--dry-run` 必须调用：

```python
engine.validate()
```

正式运行必须调用：

```python
engine.run()
```

---

# 14. 测试迁移原则

删除旧接口后，必须迁移所有测试。

禁止：

```text
保留旧 API 仅为了测试
测试导入私有 compatibility helper
测试重新实现旧 RunService
测试通过 monkeypatch 绕过新入口
```

测试层级应明确：

## Engine 测试

通过：

```python
OnlyEngine(OnlyEngineConfig(...))
```

并使用：

```text
add_cluster
validate
initialize
start
run
stop
```

## Runtime 测试

直接构造 Runtime 或通过 Runtime Factory 测试。

不得调用 Engine.register_runtime。

## CLI 集成测试

通过正式 CLI。

## Output 测试

只验证 `user_data` 布局。

---

# 15. 必须新增或更新的测试

至少覆盖：

```text
test_engine_requires_engine_config
test_engine_string_constructor_is_removed
test_engine_has_no_legacy_runtime_registry
test_engine_has_no_register_runtime_api
test_only_engine_run_is_the_single_product_run_entry
test_only_engine_run_service_is_removed
test_default_run_service_is_removed
test_data_source_type_alias_is_rejected
test_broker_type_alias_is_rejected
test_plugin_field_is_required
test_output_has_no_output_root_default
test_all_product_outputs_use_user_data_layout
test_engine_cannot_run_after_stopped
test_engine_cannot_initialize_after_stopped
test_engine_stop_is_idempotent
test_initialize_failure_releases_all_resources
test_runtime_failure_releases_all_resources
test_cli_uses_only_engine
```

还必须更新所有现有测试，不得删除核心业务断言。

---

# 16. 全仓静态检查

修改完成后执行全仓搜索。

以下结果必须为零：

```text
_product_mode
_legacy_runtimes
register_runtime(
OnlyEngineRunService
only_default_run_service
DeprecationWarning
data_sources.*type
brokers.*type
root_directory = "output"
Path("output")
```

允许存在 `legacy`、`compatibility` 等词的情况仅限：

```text
历史 ADR 中明确说明已删除
迁移报告中的历史描述
第三方协议术语
```

代码和当前使用文档中不得存在。

---

# 17. 删除过时文档和提示词

检查：

```text
docs/
prompts/
HANDOFF.md
README.md
AGENTS.md
```

删除或更新所有仍描述以下内容的文档：

```text
OnlyEngine legacy mode
OnlyEngineRunService
register_runtime()
旧 type 配置
output/ 默认目录
两套运行入口
兼容旧配置
```

历史 ADR 可以保留，但必须标注：

```text
Superseded
```

并链接到当前架构 ADR。

不要让文档同时描述新旧两种方式。

---

# 18. 增加架构规则文档

新增：

```text
docs/architecture/interface_uniqueness.md
```

内容必须明确：

## 唯一入口原则

同一业务能力只能有一个正式入口。

## 禁止兼容层原则

当前项目不保留旧版本兼容层。

## 重构完成定义

重构只有在旧接口、旧实现、旧测试和旧文档全部删除后才算完成。

## 配置唯一字段原则

同一语义只能存在一个配置字段。

## 生命周期唯一原则

同一组件只能有一套生命周期模型。

## 工厂唯一原则

相同组件类型只能通过一个 Factory/Registry 路径创建。

## 输出唯一原则

产品输出只能通过 `OnlyUserDataLayout`。

---

# 19. 更新 AGENTS.md

在根目录 `AGENTS.md` 中增加强制规则：

```text
## 接口与架构唯一性

1. 同一功能只能保留一套公开接口和一条调用链。
2. 重构后必须删除旧接口、旧实现、旧测试和旧文档。
3. 禁止增加 deprecated wrapper、compatibility adapter 或旧参数别名。
4. 禁止同时支持新旧配置格式。
5. 禁止为测试保留产品已废弃的接口。
6. 新功能必须接入现有正式架构，不得建立平行实现。
7. 发现重复职责的接口时，必须选择一个正式接口并删除其他接口。
8. 当前项目默认允许破坏性重构，不以向后兼容为理由保留旧代码。
9. 同一组件的创建、生命周期、运行和输出路径必须唯一。
10. Codex 在完成架构任务前必须执行全仓重复接口检查。
```

这部分是强制要求，不是建议。

---

# 20. 建议增加架构测试

增加静态架构测试，例如：

```text
tests/architecture/test_interface_uniqueness.py
```

至少验证：

```python
assert not hasattr(OnlyEngine, "register_runtime")
```

```python
from onlyalpha.application import ...
```

不得导出 `OnlyEngineRunService`。

检查源码中不得出现：

```text
_product_mode
_legacy_runtimes
only_default_run_service
```

检查配置模型中不得存在 DataSource/Broker 的 `type` 别名。

检查 Output 配置不得包含独立 root directory。

该测试用于防止旧接口再次被恢复。

---

# 21. 实现顺序

严格按以下顺序执行：

1. 全仓搜索旧接口与调用方；
2. 记录需要迁移的测试和文档；
3. 修改 `OnlyEngine` 构造函数；
4. 删除 `_product_mode`；
5. 删除 `_legacy_runtimes`；
6. 删除 `register_runtime()`；
7. 统一 Engine 生命周期分支；
8. 删除 `OnlyEngineRunService`；
9. 删除 `only_default_run_service()`；
10. 迁移 Runtime 生命周期测试；
11. 清理 `OnlyRunConfig` 遗留命名；
12. 删除 DataSource/Broker `type` 兼容；
13. 统一 Output 配置；
14. 删除 Runtime 独立产品输出路径；
15. 修正 CLI；
16. 更新所有测试；
17. 更新文档；
18. 更新 `AGENTS.md`；
19. 新增接口唯一性架构文档；
20. 新增架构防回归测试；
21. 执行全仓搜索；
22. 运行格式化、类型检查和全部测试；
23. 生成清理报告。

---

# 22. 验证命令

至少运行：

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pytest
```

并运行正式 CLI：

```bash
uv run onlyalpha run \
  --config <single-cluster-config> \
  --user-data ./user_data
```

以及多 Cluster：

```bash
uv run onlyalpha run \
  --config <cluster-a.yaml> \
  --config <cluster-b.yaml> \
  --user-data ./user_data
```

还要运行：

```bash
uv run onlyalpha run \
  --config <single-cluster-config> \
  --user-data ./user_data \
  --dry-run
```

---

# 23. 验收标准

任务完成时必须满足：

```text
OnlyEngine 只能接受 OnlyEngineConfig
不存在 _product_mode
不存在 _legacy_runtimes
不存在 register_runtime()
不存在 OnlyEngineRunService
不存在 only_default_run_service()
不存在旧 Runtime 产品运行入口
DataSource/Broker 只支持 plugin 字段
不存在 type 兼容逻辑
产品输出只进入 user_data
不存在默认 output/ 产品路径
CLI 只调用 OnlyEngine
Engine 生命周期无 legacy 分支
Engine 实例只允许执行一次
旧测试全部迁移
旧文档全部删除或更新
AGENTS.md 已加入接口唯一性规则
存在架构防回归测试
全部测试通过
单 Cluster CLI 通过
多 Cluster CLI 通过
dry-run 通过
```

---

# 24. 一票否决项

出现以下任一情况，任务判定为失败：

```text
保留 deprecated 接口
保留 compatibility wrapper
保留旧构造方式
保留 _product_mode 分支
保留 _legacy_runtimes
保留 register_runtime()
保留 OnlyEngineRunService
保留 only_default_run_service()
保留旧 type 字段兼容
保留 output/ 默认产品路径
为了测试保留旧产品接口
新增新的过渡 Adapter
文档同时描述新旧两套接口
只删除接口定义但未迁移调用方
只修改代码但未增加防回归测试
通过跳过测试获得通过
```

---

# 25. 最终报告

生成：

```text
docs/reports/post_refactor_cleanup_report.md
```

至少包含：

```text
删除的旧接口
删除的兼容分支
迁移的测试
迁移的文档
Engine 构造方式变化
Engine 生命周期变化
RunService 删除结果
配置字段清理结果
输出系统统一结果
AGENTS.md 规则
架构防回归测试
单 Cluster CLI 结果
多 Cluster CLI 结果
dry-run 结果
Ruff 结果
Mypy 结果
Pytest 结果
全仓残留搜索结果
```

最终结论只能是：

```text
ACCEPTED
REJECTED
```

不得使用 `CONDITIONALLY_ACCEPTED`。

只要仍存在一套旧接口、旧兼容入口或旧调用链，必须判定为：

```text
REJECTED
```

不要只提交分析或设计文档。必须完成代码删除、调用迁移、测试迁移、文档更新和完整验证。
