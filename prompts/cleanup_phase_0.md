你现在负责 OnlyAlpha 核心仓库的“架构收敛与清理”任务。

项目仓库：

```text
OnlyAlpha
```

当前项目已经完成：

* Engine / Runtime / Cluster 基础运行链路；
* Strategy / Factor / Indicator 边界；
* EventBus 与 Clock；
* DataSource / Broker Plugin SPI；
* Historical Replay；
* Synthetic DataSource；
* Virtual Broker；
* Risk、Order、ExecutionProcessor；
* Position、Allocation、Strategy Ledger、Account；
* 单 Cluster、多 Cluster 与确定性回放测试；
* CLI → OnlyEngine → RuntimePlanner → RuntimeSession → Runtime.run() 正式入口。

当前任务不是增加新业务能力，也不是重新设计架构，而是清理历史兼容层、同步文档、稳定公共 API，并确保核心仓库能够独立通过完整质量门禁。

# 一、任务目标

完成 OnlyAlpha 核心仓库的架构收敛与清理，使项目达到以下状态：

1. README、roadmap 和实际源码进度一致；
2. 删除已经不在正式产品链使用的历史兼容代码；
3. 正式运行入口只有一套；
4. 配置字段和插件装配路径统一；
5. 核心仓库不依赖兄弟仓库源码；
6. 测试不依赖特殊工作目录或脆弱的 `tests` 顶层导入；
7. 公共 API 与内部实现边界明确；
8. Python 3.12 和 Python 3.13 均通过完整质量门禁；
9. 不改变现有有效交易语义和确定性结果。

# 二、开始前必须完成的分析

开始修改前，先完整阅读：

```text
AGENTS.md
README.md
pyproject.toml
docs/architecture.md
docs/roadmap.md
docs/engine.md
docs/runtime.md
docs/plugin_system.md
docs/data_source_plugin.md
docs/broker_plugin.md
docs/workspace_structure.md
docs/testing.md
docs/adr/
```

重点搜索并整理以下内容的定义、引用和测试覆盖：

```text
OnlyRunConfig
OnlyEngineRunService
OnlyClusterRunConfig
OnlyRuntimeAssemblyPlan
OnlyRuntimePlan
OnlyRuntimePlanner
OnlyRuntimeSession
OnlyClusterSession
OnlyEngine
type
plugin
class_path
tests.
onlyalpha-test-plugin
pre-commit
```

在修改前输出一份简短分析，说明：

* 当前正式产品链路；
* 历史兼容链路；
* 哪些符号只被历史测试引用；
* 哪些配置字段已废弃；
* 哪些文档与实现不一致；
* 哪些测试依赖当前工作目录；
* 哪些模块属于公共 API；
* 哪些模块应视为内部实现。

不要仅凭名称删除代码。必须先通过源码引用、测试和文档确认其实际用途。

# 三、正式产品链必须保持不变

正式入口固定为：

```text
CLI
→ OnlyEngine
→ OnlyClusterRunConfig[]
→ OnlyRuntimePlanner
→ OnlyRuntimePlan
→ OnlyRuntimeSession
→ OnlyRuntime.run()
```

Engine 负责：

* Cluster Definition；
* Cluster Session；
* Runtime Session；
* Runtime 兼容性分组；
* 共享资源协调；
* 生命周期；
* user_data 输出；
* 运行结果汇总。

禁止重新引入以下行为：

* CLI 直接创建 Runtime；
* CLI 直接创建 DataSource 或 Broker；
* Engine 使用旧 RunService 代理整个运行；
* 将多个 Cluster 配置合并回旧的全局 RunConfig；
* Runtime 硬编码第三方 Broker 或 DataSource；
* Plugin 直接访问 Engine、Runtime 私有容器或 Manager；
* Broker 直接修改 Order、Position、Ledger 或 Account；
* 核心依赖 OnlyAlpha-plugins 或 OnlyAlpha-examples。

# 四、具体工作内容

## 4.1 更新 README

修改根目录 `README.md`。

必须删除或修正以下过时表述：

```text
OnlyAlpha 是 MyQuant 的重构版本
当前只有 Phase 0、Phase 1 和 Domain 第一版
尚无撮合、执行和 Broker 能力
```

OnlyAlpha 应描述为独立的新项目，不是 MyQuant 的重构版本。

README 应准确说明当前状态：

* 模块化单体架构；
* Engine / Runtime / Cluster 运行模型；
* Strategy / Factor / Indicator 分层；
* Synthetic Historical Replay；
* Virtual Broker；
* Risk / Order / ExecutionProcessor；
* Position / Allocation / Ledger / Account；
* DataSource / Broker Plugin SPI；
* 单 Cluster、多 Cluster、确定性回放；
* 当前尚未完成真实 A 股数据、完整交易规则、Paper、Live 和 Research 产品循环。

README 需要包含：

* 项目定位；
* 三仓职责；
* 当前能力；
* 当前限制；
* 快速开始；
* 质量验证命令；
* 文档入口。

三仓职责固定为：

```text
OnlyAlpha
    核心框架、领域模型、运行时、内建基础实现和公共 SPI

OnlyAlpha-plugins
    官方 Strategy、Factor、扩展组件、真实 DataSource、Broker 和 Cluster 配置

OnlyAlpha-examples
    官方教程、示例入口、运行说明和生成结果
```

## 4.2 更新 roadmap

修改：

```text
docs/roadmap.md
```

不得再把全部回测能力描述为“尚未开始”。

将回测阶段拆分为清晰子阶段，例如：

```text
Phase 2A：确定性回测内核
Phase 2B：真实历史数据
Phase 2C：A 股市场规则
Phase 2D：回测分析与报告
```

根据实际源码标记：

* 已完成；
* 部分完成；
* 未完成。

至少准确反映：

已完成或基本完成：

* Engine / Runtime / Cluster；
* Synthetic Replay；
* Virtual Broker；
* Next-Bar 基础撮合；
* Risk / Order / Execution；
* Position / Allocation；
* Strategy Ledger / Account；
* Plugin SPI；
* 确定性重放；
* 多 Cluster Runtime 分组。

尚未完成：

* 真实历史数据源；
* 完整 A 股交易规则；
* 复权与公司行为；
* 完整手续费和税费；
* 成交量约束；
* 完整回测报告；
* Paper 产品循环；
* Live 产品循环；
* Research 产品工作流；
* Web；
* 性能与分布式。

不要夸大实现程度。

## 4.3 清理历史 Engine / Runtime 兼容层

重点检查：

```text
OnlyRunConfig
OnlyEngineRunService
旧 Runtime Factory 或旧 Assembler 入口
旧配置合并逻辑
旧产品链适配器
```

处理规则：

1. 如果符号已经不被正式产品代码使用，只被历史测试使用：

   * 先迁移测试到正式产品链；
   * 再删除兼容符号。

2. 如果符号仍被少量内部实现引用：

   * 先替换为正式类型；
   * 再删除兼容层。

3. 不保留“以后可能有用”的死代码。

4. 如果暂时不能删除：

   * 必须写明具体阻塞原因；
   * 标记明确 deprecation；
   * 给出删除条件；
   * 不允许静默保留。

目标是正式代码中不再出现：

```text
OnlyRunConfig
OnlyEngineRunService
```

除非分析确认它们仍有不可替代的内部用途。

正式代码包括：

```text
src/onlyalpha/
```

测试夹具、迁移文档和历史 ADR 可保留必要文字说明，但不能继续执行旧链路。

## 4.4 清理旧配置字段

当前插件公共配置应统一使用：

```yaml
plugin: <plugin-id>
```

重点搜索：

```text
type:
class_path:
```

处理要求：

* DataSource 和 Broker 正式配置统一使用 `plugin`；
* 不允许通过任意 `class_path` 创建 DataSource 或 Broker；
* 核心只解析公共字段；
* 插件专属字段保存在 `extensions`；
* 内部统一使用 `plugin_id`；
* 测试、示例配置、文档全部同步。

如果旧 `type` 兼容层仍存在：

* 判断项目尚未正式发布，是否可以直接删除；
* 优先删除而不是继续保留到未来版本；
* 如确实需要保留，必须只存在于明确的配置迁移边界；
* 不得进入内部标准模型；
* 必须有测试验证 warning 和冲突行为。

检查以下冲突：

```yaml
plugin: synthetic
type: synthetic
```

应返回清晰结构化错误，而不是随机选择一个字段。

## 4.5 修正依赖分类

检查 `pyproject.toml`。

`pre-commit` 不应是正式运行依赖。

目标结构类似：

```toml
[project]
dependencies = [
    "pyarrow>=...",
    "pyyaml>=...",
    "tzdata>=...; sys_platform == 'win32'",
]

[dependency-groups]
dev = [
    "mypy>=...",
    "onlyalpha-test-plugin",
    "pre-commit>=...",
    "pytest>=...",
    "ruff>=...",
]
```

同时检查是否还有以下错误分类：

* pytest 出现在运行依赖；
* ruff 出现在运行依赖；
* mypy 出现在运行依赖；
* 测试 fixture 包出现在正式依赖；
* 非运行期工具出现在核心包依赖。

不得随意升级所有依赖版本，只修正分类和明确必要的问题。

## 4.6 清理测试导入和运行目录依赖

当前部分测试可能使用：

```python
from tests.xxx import ...
```

这会导致从 Workspace 根目录或安装环境运行时出现：

```text
ModuleNotFoundError: No module named 'tests'
```

目标：

* 测试不依赖当前工作目录；
* 测试辅助代码应通过明确包路径导入；
* 不使用脆弱的顶层 `tests` 包名；
* 不依赖手工设置 `PYTHONPATH`；
* 从仓库根目录运行 pytest 正常；
* 从 Workspace 使用 `uv run --directory OnlyAlpha pytest` 正常；
* 测试安装环境正常。

可选方案：

* 将测试辅助模块放到明确命名的测试支持包；
* 使用相对导入；
* 增加必要的 `__init__.py`；
* 将通用 fixture 移入 `tests/support` 或 `tests/runtime_support`；
* 避免与其他 Workspace 成员的 `tests` 包冲突。

不要为了绕过问题，在 Workspace 根中堆叠多个 `pythonpath`。

优先修复测试本身。

## 4.7 明确公共 API 与内部 API

检查：

```text
src/onlyalpha/
```

确定哪些模块是外部插件和用户可以依赖的公共 API。

至少明确：

```text
onlyalpha.plugin.api
Domain 公共模型
DataSource 公共 Port
Broker 公共 Port
Strategy / Factor / Indicator 公共接口
Engine 公共入口
配置公共类型
```

内部实现应避免被外部插件依赖，例如：

```text
Runtime Assembler
Manager 私有实现
Engine Session 内部状态
Registry 内部容器
ExecutionProcessor 内部编排细节
```

需要完成：

* 检查公共包的 `__init__.py` 导出；
* 删除错误导出的内部符号；
* 对公共 API 增加清晰 docstring；
* 避免插件测试直接 import 私有实现；
* 必要时使用 `_internal` 或私有命名表达边界；
* 不要为了追求目录美观做大规模无价值移动。

如涉及破坏性导入路径变更，因为项目尚未正式发布，可以直接修正，但必须同步所有测试和文档。

## 4.8 核心仓库独立性检查

OnlyAlpha 核心仓库不得依赖以下兄弟仓库源码：

```text
OnlyAlpha-plugins
OnlyAlpha-examples
```

检查：

* 路径依赖；
* editable dependency；
* sys.path 注入；
* 相对路径读取；
* 测试中直接导入兄弟仓库；
* 文档命令默认兄弟仓库一定存在；
* CI 隐式依赖 Workspace。

核心测试可使用：

```text
tests/fixtures/external_plugins/onlyalpha_test_plugin
```

该测试插件必须作为独立 distribution 安装，并通过真实 Entry Point 发现，不允许在测试中绕过 metadata 手工注册来伪造插件加载成功。

## 4.9 Python 3.12 / 3.13 兼容性

当前最低版本是：

```text
Python 3.12
```

验证：

```text
Python 3.12
Python 3.13
```

检查：

* typing API；
* dataclass 行为；
* importlib.metadata；
* enum；
* datetime；
* pathlib；
* SQLite；
* PyArrow；
* 平台条件依赖。

不要使用 Python 3.13 独有语法或 API，除非同步提高最低版本；本任务不得提高最低 Python 版本。

# 五、测试要求

必须先运行现有测试，记录基线。

修改后至少执行：

```bash
uv sync --dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

如果项目已有更严格命令，使用项目现有命令。

还必须重点运行：

* Engine 生命周期测试；
* Runtime Planner 测试；
* Runtime Session 测试；
* Cluster Session 测试；
* CLI 测试；
* Plugin Discovery 测试；
* DataSource SPI 测试；
* Broker SPI 测试；
* Historical Replay 测试；
* Virtual Broker 测试；
* ExecutionProcessor 测试；
* Vertical Slice 集成测试；
* 确定性重放测试；
* 多 Cluster 共享 Runtime 测试；
* user_data 输出测试。

新增或修改测试，至少覆盖：

1. 正式产品链不引用旧 RunService；
2. 正式代码不引用 `OnlyRunConfig`；
3. DataSource/Broker 配置统一使用 `plugin`；
4. `plugin` 与旧字段冲突时明确失败；
5. 核心仓库不依赖兄弟仓库；
6. 测试从仓库根目录运行；
7. 外部测试插件通过 Entry Point 加载；
8. 公共 API 可从预期路径导入；
9. 内部 API 不被公共 `__init__.py` 错误导出；
10. 相同输入的确定性指纹和业务结果保持不变。

# 六、不可破坏的不变量

本次重构不得改变以下行为：

* 相同输入产生相同结果；
* Event 只在状态成功修改后发布；
* Broker Update 只能通过 BrokerInboundQueue；
* ExecutionProcessor 是执行回报唯一业务入口；
* Strategy 不直接修改账户、持仓或订单；
* Factor 没有交易权限；
* Cluster 只能读取受限 Snapshot；
* Account 与 Strategy Ledger 分离；
* Position 与 Allocation 两层账分离；
* Fill 去重；
* Reservation 正确释放；
* T+1 现有测试语义保持；
* 多 Cluster 输出隔离；
* 兼容 Cluster 的 Runtime 分组保持；
* stop/close 幂等；
* 失败时资源逆序回滚；
* OnlyAlpha 核心不依赖外部官方插件仓库。

# 七、禁止事项

不要：

* 增加新的大型架构模块；
* 实现真实 A 股 DataSource；
* 实现 MiniQMT；
* 实现完整 Market Rules；
* 实现新的撮合算法；
* 开始 Paper、Live、Research 或 Web；
* 引入多线程、Actor、Redis 或分布式；
* 重写已经稳定的 Domain；
* 为了“统一风格”进行无关的大规模改名；
* 删除仍有业务覆盖的测试；
* 通过跳过测试解决问题；
* 使用 `# noqa`、`type: ignore` 或降低 mypy 严格度掩盖问题；
* 放宽 Ruff 或 pytest 配置来隐藏错误；
* 修改确定性期望值来迎合非确定性实现。

# 八、执行方式

按以下顺序执行：

```text
1. 阅读文档和源码
2. 运行当前质量门禁，记录基线
3. 输出清理分析
4. 更新 README 和 roadmap
5. 清理旧 Engine / Runtime 兼容层
6. 清理旧插件配置字段
7. 修正 pyproject 依赖分类
8. 修复测试导入和工作目录依赖
9. 收敛公共 API
10. 检查核心仓库独立性
11. 补充测试
12. 运行完整质量门禁
13. 输出最终报告
```

每完成一个逻辑阶段后运行相关测试，不要把所有改动堆积到最后才验证。

# 九、最终交付内容

任务完成后，输出一份中文报告，必须包含：

## 1. 修改前状态

* 正式产品链；
* 历史兼容链；
* 过时文档；
* 测试导入问题；
* 依赖分类问题；
* 公共 API 问题。

## 2. 删除内容

列出删除的：

* 类型；
* 类；
* 函数；
* 模块；
* 配置字段；
* 兼容入口；
* 测试适配器。

说明每项为什么可以删除。

## 3. 保留的兼容内容

如果仍有任何兼容层，列出：

* 名称；
* 保留原因；
* 使用位置；
* 删除条件；
* 预计在哪个阶段删除。

不得只写“暂时保留”。

## 4. 文档更新

说明：

* README 如何重新定位 OnlyAlpha；
* roadmap 如何反映当前真实阶段；
* 哪些架构文档同步修改。

## 5. 公共 API

列出确认后的公共入口及内部边界。

## 6. 测试结果

给出实际执行结果：

```text
pytest
ruff check
ruff format --check
mypy
Python 3.12
Python 3.13
```

不得虚构通过结果。

## 7. 回归情况

说明是否发现：

* 架构回归；
* 业务语义回归；
* 确定性回归；
* Plugin SPI 回归；
* CLI 回归；
* Workspace 运行回归。

## 8. 剩余问题

只列出本任务范围内未完成的问题，不要扩展成新路线图。

# 十、完成判定

只有满足以下条件才算完成：

* README 不再将 OnlyAlpha 描述为 MyQuant 重构；
* roadmap 与源码真实进度一致；
* 正式产品链只剩一套；
* 无无意义历史 RunConfig / RunService 兼容层；
* DataSource/Broker 使用统一插件配置；
* `pre-commit` 不在运行依赖；
* 测试不再依赖顶层 `tests` 导入和特殊工作目录；
* OnlyAlpha 核心可脱离兄弟仓库独立测试；
* 公共 API 边界清楚；
* Python 3.12 和 3.13 验证通过；
* pytest、Ruff、format check、strict Mypy 全部通过；
* 原有确定性纵切面和业务不变量不变。

本任务的核心原则是：

> 删除已经失去价值的历史兼容层，统一唯一产品链，修正文档和测试边界，为下一阶段真实 A 股回测能力提供稳定核心。

不要继续扩张架构。优先减少概念、减少入口、减少兼容路径，并用现有完整纵切面证明清理没有破坏系统。
