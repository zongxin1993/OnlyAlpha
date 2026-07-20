你现在负责 OnlyAlpha 单仓工程的基础设施收敛任务：

# OnlyAlpha Monorepo CI, Python, Release and Documentation Consolidation

中文名称：

# OnlyAlpha 单仓 CI、Python 版本、发布与工程文档收敛

本任务必须从第一性原则重新审查当前单仓工程的：

```text
Python 支持范围
uv Workspace
包依赖关系
测试门禁
静态检查
构建
发布
版本策略
文档
交接信息
```

本任务不是简单修改一份 GitHub Actions YAML。

最终目标是：

> 对仓库中每一个正式 Python distribution，建立唯一、明确、可重复的开发、测试、构建和发布路径；所有工程元数据、CI、发布流程、文档和交接信息必须描述同一个真实工程状态。

---

# 一、第一性原则

整个任务必须遵守以下原则。

## 1. 声明支持的环境必须被真实验证

如果工程声明支持：

```text
Python 3.12
Python 3.13
Windows
Linux
macOS
```

则对应环境必须进入自动化门禁。

没有被 CI 或明确外部验收验证的环境，不得在：

```text
pyproject.toml
README
发布元数据
文档
```

中宣称正式支持。

---

## 2. 一个 distribution 必须能够独立构建

仓库中每个正式包必须能够独立执行：

```text
依赖解析
导入
类型检查
单元测试
构建 wheel
构建 sdist
安装构建产物
Entry Point 发现
最小 smoke test
```

不能因为从源码 Workspace 中可以导入，就认为发布包正确。

---

## 3. 安装全部包不等于测试全部包

以下命令：

```bash
uv sync --all-packages
```

只能证明 Workspace 依赖能够解析。

它不能证明：

```text
所有包的测试已执行
所有包通过 Ruff
所有包通过 Mypy
所有包能够构建
所有 Entry Point 能从 wheel 中发现
```

CI 必须显式覆盖每一个 distribution。

---

## 4. Core 不得隐式依赖具体插件

依赖方向必须保持：

```text
Plugin
    ↓
OnlyAlpha Core 公共 API
```

禁止：

```text
OnlyAlpha Core
    ↓
具体 Provider/Broker/DataSource 插件
```

测试或示例需要插件时，应通过：

```text
Workspace dependency
Entry Point
Plugin Registry
正式 Factory SPI
```

装配。

历史装配代码曾直接导入具体 Virtual Broker 和 Synthetic DataSource，因此本任务必须检索并清理所有仍然存在的同类具体实现泄漏。

---

## 5. CI、构建和发布必须使用同一套元数据

禁止出现：

```text
Core 声明 Python <3.13
但发布 workflow 使用 Python 3.13

开发环境安装全部包
但发布只构建根包

插件声明支持 3.13
但 Core 不允许安装在 3.13

README 描述多仓
实际代码已经单仓

CI 只检查 src/ 和 tests/
但 packages/ 未进入检查
```

工程必须只有一个真实答案。

---

## 6. 不保留旧兼容路径

本任务不考虑对旧 Workspace、旧子模块、旧发布脚本、旧包路径和旧 CI 的兼容。

如果旧配置和新配置表达相同目的：

```text
删除旧配置
迁移正式调用方
更新测试
更新文档
```

禁止保留两套正式 workflow。

---

# 二、当前工程背景

当前 OnlyAlpha 已经迁移为单仓多包结构，至少包含：

```text
src/onlyalpha/                         Core

packages/provider/
    onlyalpha-plugin-tushare
    onlyalpha-plugin-miniqmt
    其他供应商插件

packages/data/
    数据源插件

packages/fake/ 或等价目录
    测试和虚拟实现包

examples/
tests/
docs/
```

实际路径必须以当前仓库源码为准。

当前已经发现的工程不一致包括：

```text
Core Python 版本声明与实际 Python 3.13 使用不一致
发布 workflow 与 Python 元数据不一致
主 CI 未明确执行全部 packages 下的测试
主 Ruff/Mypy 范围可能未覆盖全部包
发布流程可能只构建根 Core distribution
部分文档仍描述旧的多仓结构
README 工程结构和当前能力说明不完整
```

不得把这些结论直接当成最终事实；开始修改前必须根据当前主分支重新验证。

---

# 三、开始前必须完成全局审计

编码前必须遍历整个仓库。

至少审计：

```text
pyproject.toml
uv.lock
.python-version
.github/workflows/
README.md
AGENTS.md
HANDOFF.md

docs/architecture.md
docs/workspace_structure.md
docs/plugin_system.md
docs/plugin_testing.md
docs/release*.md
docs/roadmap.md

src/onlyalpha/
packages/
examples/
tests/
```

检查所有：

```text
pyproject.toml
requires-python
dependencies
optional-dependencies
tool.uv.sources
tool.uv.workspace
pytest testpaths
ruff include/exclude
mypy files/exclude
Entry Point
包版本
包名称
```

先新增审计报告：

```text
docs/reports/
monorepo_ci_python_release_documentation_audit.md
```

报告必须包含以下内容。

## 3.1 Distribution 清单

为每一个正式包记录：

```text
Distribution Name
Package Path
Import Name
Current Version
requires-python
Core Dependency Constraint
Platform Constraint
Entry Points
Unit Test Path
Integration Test Path
External Dependency
Release Status
```

必须至少包括 Core、Tushare、MiniQMT 和当前全部一方插件包。

## 3.2 Python 版本矩阵

记录每个包在以下环境的真实结果：

```text
Python 3.12
Python 3.13
Windows
Linux
macOS
```

如果某个包具有明确的平台限制，应记录：

```text
SUPPORTED
UNSUPPORTED
NOT VERIFIED
```

不得把未验证写成支持。

## 3.3 当前 CI 覆盖表

为每个 distribution 标记：

```text
Install
Import
Unit Test
Integration Test
Ruff
Format
Mypy
Build Wheel
Build Sdist
Install Wheel
Entry Point Smoke
```

## 3.4 当前发布能力

确认：

```text
哪些包会被构建
哪些包会被上传
发布由什么 Tag/Release 触发
版本从哪里读取
是否使用 PyPI Trusted Publishing
是否验证 wheel 内容
是否测试 wheel 安装
```

## 3.5 文档漂移

列出所有仍描述：

```text
旧多仓
旧 Workspace
旧子模块
旧包路径
错误 Python 版本
错误安装命令
错误发布方式
```

的文档。

---

# 四、确定唯一 Python 支持策略

不得凭偏好直接修改版本号。

必须根据：

```text
Core 测试
全部一方插件测试
第三方 SDK 支持
构建工具支持
PyPI 包支持
目标平台
```

确定支持矩阵。

## 4.1 决策规则

如果 Core 和全部正式一方包都能在 Python 3.12、3.13 上通过完整门禁，则统一声明：

```toml
requires-python = ">=3.12,<3.14"
```

如果任一正式发布包无法在 Python 3.13 上通过，则统一采用明确的 3.12 策略，例如：

```toml
requires-python = ">=3.12,<3.13"
```

并确保：

```text
CI 只使用声明支持的 Python
Publish workflow 使用声明支持的 Python
README 明确支持范围
不支持版本安装时立即失败
```

如果 MiniQMT 的平台 SDK 与 Core 支持范围不同，允许插件使用更窄约束，但不能使用更宽且与 Core 不相交的约束。

例如：

```text
Core: >=3.12,<3.14
MiniQMT: >=3.12,<3.13
```

是允许的。

以下情况禁止：

```text
Core: >=3.12,<3.13
MiniQMT: >=3.13
```

---

# 五、统一 uv Workspace

## 5.1 Workspace 成员

根 `pyproject.toml` 必须明确列出或匹配所有正式包。

例如：

```toml
[tool.uv.workspace]
members = [
    "packages/provider/*",
    "packages/data/*",
    "packages/broker/*",
    "packages/fake/*",
]
```

实际目录以当前代码为准。

必须确保：

```text
没有正式包遗漏
没有已删除目录残留
没有测试资源被误当 distribution
没有平台插件导致非目标平台无法完成基础 sync
```

## 5.2 Workspace Source

Workspace 内部依赖使用：

```toml
onlyalpha = { workspace = true }
```

不得使用：

```text
绝对本地路径
开发者机器路径
旧 sibling repository 路径
Git submodule 路径
```

发布构建时必须能够转换为正常版本约束。

## 5.3 Platform-specific Package

MiniQMT 等平台包不得阻塞 Linux/macOS 的 Core CI。

可通过以下一种正式方案解决：

```text
Workspace marker
平台条件依赖
独立 Windows CI job
只在兼容平台执行 package sync
```

不得通过从 Workspace 完全排除后再使用随意 editable path 的方式形成两套依赖模型，除非 uv 当前能力确实无法表达；若必须如此，应在 ADR 中说明原因和唯一操作方式。

---

# 六、重新设计 CI

CI 必须按职责分层，而不是一个模糊的总 Job。

建议建立以下 Jobs。

## 6.1 Core Quality

运行平台：

```text
Linux
Windows
macOS
```

Python 矩阵使用正式支持版本。

执行：

```bash
uv sync --frozen
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/onlyalpha
uv run pytest tests -q
```

根据当前测试结构调整路径，但必须完整覆盖 Core。

## 6.2 Package Quality Matrix

根据 Distribution 清单生成 matrix。

每个包执行：

```bash
uv sync --package <distribution> --group dev
uv run --package <distribution> ruff check <package-src> <package-tests>
uv run --package <distribution> ruff format --check <package-src> <package-tests>
uv run --package <distribution> mypy <package-src>
uv run --package <distribution> pytest <package-tests> -q
```

如果当前包没有独立 dev group，应统一设计，不得跳过检查。

## 6.3 MiniQMT Windows

MiniQMT 只能在实际支持平台执行。

标准 CI 至少验证：

```text
包可以安装
模块可以导入
不连接真实 QMT 的单元测试
Callback / Mapper / Factory Contract
Broker/DataSource Entry Point
```

真实 MiniQMT 集成测试使用明确标记：

```text
integration
real_xtquant
requires_local_qmt
```

不能在缺少本地 QMT 服务的 GitHub Runner 上伪造通过。

如果真实测试只能由开发者机器执行，必须：

```text
提供正式命令
提供环境变量
在 HANDOFF 记录最近真实结果
不把它写成普通 GitHub-hosted CI 已验证
```

## 6.4 Scenario and Conformance

单独执行正式 Scenario 和 Conformance 门禁：

```text
A 股
Generic T0
Futures
Crypto Spot
Cross-Version
```

执行结果必须区分：

```text
PASSED
FAILED
ERROR
INCOMPLETE
SKIPPED
```

## 6.5 Build Matrix

对每个 distribution 执行：

```bash
uv build --package <distribution>
```

随后：

```text
检查 wheel
检查 sdist
创建干净虚拟环境
从 wheel 安装
执行 import smoke
执行 Entry Point discovery
```

不能只检查源码环境。

## 6.6 Dependency Boundary

增加自动化门禁：

```text
Core 不依赖具体插件
插件不依赖 Core 私有模块
插件之间不形成循环依赖
Examples 只使用公共 API
```

---

# 七、测试分类和 Marker

统一 pytest marker：

```text
unit
contract
integration
external
windows
requires_network
requires_token
requires_local_qmt
slow
scenario
conformance
```

默认 CI 必须执行：

```text
unit
contract
无外部依赖的 integration
scenario
conformance
```

默认 CI 不应依赖：

```text
真实 Tushare Token
本地 MiniQMT 客户端
本地券商登录
私有数据库
外部网络
```

外部测试必须可独立显式运行，例如：

```bash
uv run pytest -m real_xtquant
uv run pytest -m requires_token
```

禁止仅通过环境变量不存在而静默让核心门禁全部跳过，却仍宣称插件已验证。

---

# 八、统一 Ruff、Format 和 Mypy

## 8.1 Ruff

根配置应覆盖：

```text
src/
tests/
packages/*/src/
packages/*/tests/
examples/
```

如果不同包确实需要例外，应使用最小路径级配置。

禁止只执行：

```bash
ruff check src tests
```

然后宣称单仓全量通过。

## 8.2 Format

以下必须成为硬门禁：

```bash
ruff format --check .
```

必须修复当前所有既有格式失败。

不得以“这是旧文件”为理由继续保留失败。

## 8.3 Mypy

为每个正式 distribution 建立明确入口。

不得只检查：

```text
src/onlyalpha
```

而遗漏插件源码。

第三方无类型 SDK 应通过：

```text
局部 Protocol
Adapter Boundary
最小 ignore_missing_imports
Stub
```

隔离。

禁止在整个插件包中全局关闭类型检查。

---

# 九、发布设计

## 9.1 Distribution 独立发布

Core 和插件是不同的 Python distributions，必须独立构建。

例如：

```text
onlyalpha
onlyalpha-plugin-tushare
onlyalpha-plugin-miniqmt
onlyalpha-plugin-broker-virtual
```

不得只构建根目录 Core。

## 9.2 版本策略

确定并记录以下一种策略：

### 推荐：独立版本

```text
onlyalpha==0.x.y
onlyalpha-plugin-tushare==0.a.b
onlyalpha-plugin-miniqmt==0.c.d
```

插件通过版本约束声明兼容 Core：

```toml
dependencies = [
    "onlyalpha>=0.x,<0.(x+1)",
]
```

或者采用统一版本，但必须由 ADR 明确说明。

不得出现包版本、Tag、Release 名称彼此无法映射。

## 9.3 Tag 规则

推荐明确到 distribution：

```text
onlyalpha-v0.3.0
onlyalpha-plugin-tushare-v0.2.0
onlyalpha-plugin-miniqmt-v0.2.0
```

CI 根据 Tag 确定唯一 package path。

禁止一个普通 Release 自动上传仓库内所有包，除非明确采用同步统一版本。

## 9.4 发布前门禁

发布 Job 必须依赖：

```text
对应包测试通过
Ruff 通过
Format 通过
Mypy 通过
Build 通过
Wheel install smoke 通过
Entry Point discovery 通过
版本与 Tag 一致
工作树/锁文件一致
```

## 9.5 PyPI 认证

优先使用：

```text
PyPI Trusted Publishing
GitHub OIDC
```

不再使用长期保存的 Twine 密码，除非当前发布环境暂时无法采用 Trusted Publishing。

## 9.6 发布产物

每个正式包发布：

```text
wheel
sdist
SHA-256
build manifest
```

构建环境必须使用正式支持的 Python 版本。

---

# 十、更新工程文档

## 10.1 README

重写当前 README 的核心部分，至少包括：

```text
OnlyAlpha 当前定位
当前完成能力
尚未完成能力
单仓目录结构
安装 Core
安装插件
开发环境初始化
运行测试
运行示例
运行 Scenario
运行 Conformance
Python 支持范围
平台限制
发布包列表
```

不得继续保留空的“工程结构”或“当前能力”章节。

## 10.2 Architecture

更新：

```text
docs/architecture.md
docs/workspace_structure.md
docs/plugin_system.md
docs/plugin_testing.md
```

确保只描述当前单仓多包结构。

删除：

```text
旧三仓
旧 sibling repository
旧 submodule
旧 OnlyAlpha-workspace 操作
```

## 10.3 Python Support

新增：

```text
docs/python_support.md
```

记录：

```text
正式 Python 版本
各平台支持情况
各插件特殊限制
CI 验证矩阵
升级 Python 版本的门禁
```

## 10.4 CI 文档

新增：

```text
docs/ci_quality_gates.md
```

说明：

```text
每个 Job 的职责
哪些测试是硬门禁
哪些是外部验收
如何本地复现 CI
如何运行 MiniQMT 真实测试
```

## 10.5 Release 文档

新增或重写：

```text
docs/release_process.md
```

说明：

```text
包列表
版本策略
Tag 策略
发布命令
Trusted Publishing
回滚方式
发布后验证
```

## 10.6 ADR

新增：

```text
docs/adr/
xxxx-monorepo-python-ci-and-release-policy.md
```

必须固化：

```text
单仓多包边界
Python 版本策略
平台支持策略
独立包版本策略
CI 分层
发布方式
外部集成测试定位
不保留旧多仓兼容
```

---

# 十一、更新 AGENTS 和 HANDOFF

## 11.1 AGENTS.md

必须明确 Codex 和开发者在修改工程时遵守：

```text
新增 package 必须加入 Workspace
新增 package 必须加入 CI matrix
新增 package 必须有独立 pyproject
新增 Entry Point 必须有 wheel smoke test
Core 不得导入插件实现
插件不得导入 Core 私有组件
Python 支持范围不可局部随意修改
文档必须与源码同步
```

## 11.2 HANDOFF.md

更新为真实单仓状态，至少记录：

```text
当前 commit
Python 支持矩阵
Distribution 清单
CI Jobs
发布包清单
最近真实测试结果
MiniQMT 外部测试状态
未完成门禁
下一步开发计划
```

不得保留旧的三仓门禁结论。

---

# 十二、删除和清理

主动搜索并删除：

```text
旧三仓说明
旧 Workspace 子模块说明
旧 sibling path 配置
旧发布 workflow
旧 Python 版本声明
只检查 Core 的伪全仓门禁
重复 Ruff/Mypy 配置
失效 package path
失效 editable source
未使用的 CI script
```

如果存在历史报告，可保留为历史文档，但必须标明：

```text
Historical
Superseded
Not current operational guidance
```

---

# 十三、必须执行的真实门禁

最终必须真实执行并记录。

## 13.1 Workspace

```bash
uv lock --check
uv sync --frozen --all-groups --all-packages
```

如果平台插件不能进入该命令，应提供唯一、文档化的平台分支命令。

## 13.2 Core

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/onlyalpha
```

## 13.3 每个插件

对每个正式 package 执行：

```bash
uv run pytest <package-tests> -q
uv run ruff check <package-src> <package-tests>
uv run ruff format --check <package-src> <package-tests>
uv run mypy <package-src>
uv build --package <distribution>
```

## 13.4 全仓

```bash
uv run ruff check .
uv run ruff format --check .
git diff --check
```

## 13.5 构建产物

对每个 wheel：

```text
干净环境安装
import smoke
Entry Point discovery
版本检查
```

## 13.6 场景门禁

运行当前正式 Scenario 和 Conformance。

不得只运行 Parser 或 Unit Test。

## 13.7 Python Matrix

在每个正式声明支持的 Python 版本中执行对应门禁。

---

# 十四、完成标准

以下全部满足才可宣称任务完成：

```text
所有正式 distribution 已纳入清单
所有正式 package 已进入 CI
Core 和插件 Python 约束一致
CI Python 与发布 Python 一致
平台限制已明确
全部包 Ruff 通过
全部包 Format 通过
全部包 Mypy 通过
全部包 Unit/Contract Test 通过
正式 Scenario/Conformance 通过
全部包能够独立构建
全部 wheel 能在干净环境安装
全部 Entry Point 能从 wheel 发现

发布 workflow 能按 distribution 正确选择包
Tag 与包版本严格一致
发布前门禁完整
PyPI 认证策略明确
不再只构建根包

README 已重写
Architecture 已更新
Workspace 文档已更新
Plugin 文档已更新
Python Support 文档已新增
CI 文档已新增
Release 文档已新增
ADR 已新增
AGENTS.md 已更新
HANDOFF.md 已更新

旧三仓和旧发布路径已删除
不存在两套正式 CI
不存在两套 Python 支持声明
不存在未进入门禁的正式 package
```

如果任一项未完成，最终报告必须明确：

```text
本任务未完成
```

不得使用“基本完成”代替硬门禁。

---

# 十五、最终报告格式

完成后输出中文报告。

## 1. 修改前审计

列出：

```text
Python 冲突
CI 覆盖缺口
构建缺口
发布缺口
文档漂移
```

## 2. Distribution 清单

逐包列出：

```text
名称
版本
路径
Python
平台
Entry Point
测试
发布状态
```

## 3. Python 决策

说明：

```text
最终支持版本
放弃的版本
决策依据
实际验证结果
```

## 4. Workspace

说明成员、依赖方向和平台包处理方式。

## 5. CI

列出所有 Job、平台、Python 和执行命令。

## 6. 构建与安装

列出每个包的 wheel/sdist 和干净安装结果。

## 7. 发布

说明版本、Tag、Trusted Publishing 和包选择机制。

## 8. 文档

列出新增、重写和删除的文档。

## 9. 删除内容

列出旧三仓、旧 CI、旧发布和旧版本配置。

## 10. 质量门禁

列出真实命令、退出码和结果。

## 11. 外部集成测试

明确区分：

```text
CI 已验证
开发者机器已验证
本轮未验证
```

## 12. 明确未完成

不得把未执行的真实 MiniQMT、Tushare 在线测试或 PyPI 正式上传写成已完成。

---

# 十六、最终原则

> `pyproject.toml`、uv Workspace、CI、构建、发布和文档必须对“OnlyAlpha 支持什么”给出同一个答案。

> 单仓中的每一个正式 distribution 都必须被独立测试、构建和安装验证。

> Python 支持不是一条字符串，而是一组经过真实平台和测试证明的能力。

> 发布流程发布的是独立 distribution，不是仓库目录。

> 外部集成测试可以依赖真实环境，但必须与默认 CI 明确分层，不能通过静默跳过制造虚假的绿色门禁。

> 工程文档是当前系统的操作契约，不是历史设计草稿。
