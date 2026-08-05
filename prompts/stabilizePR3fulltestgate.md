你正在维护 OnlyAlpha 工程：

* Repository: https://github.com/zongxin1993/OnlyAlpha
* Branch: `master`
* 当前基线提交：`e6ca4218f8408be207a6adcbdb322828056262de`
* 当前提交说明：`Feat: A 股 Instruction-Driven Durable T+1 Settlement Authority Closure`
* Python 工程使用 `uv`
* 当前 GitHub Actions 工作流：`.github/workflows/quality.yml`
* 当前失败位置：

  * `static` Job 已通过
  * `main-gate` Job 中的 `uv run python scripts/test_suite.py full` 失败
  * 后续 `recovery`、`ashare` 和 `build` 因此被跳过

本任务只针对当前 `master` 的测试失败进行诊断、修复和验证。

# 一、任务目标

完成以下闭环：

1. 在本地复现 `scripts/test_suite.py full` 失败。
2. 获取完整 pytest 失败信息和根因。
3. 判断失败属于以下哪种类型：

   * PR3 实现缺陷；
   * 已失效或仍验证旧架构语义的测试；
   * Fixture、测试数据或 Snapshot 未随 PR3 更新；
   * 测试顺序依赖或全局状态污染；
   * 时间、时区、交易日或非确定性问题；
   * Checkpoint、恢复或持久化 Schema 不一致；
   * CI 环境与本地环境差异；
   * 超时、资源使用或并发问题。
4. 修复真正的根因。
5. 完整运行项目要求的所有门禁。
6. 输出清晰的失败分析、修改说明和验证结果。

最终目标是恢复当前 `master` 的绿色基线，为后续 PR4.1 提供可信的工程起点。

# 二、严格范围

本任务允许：

* 修复 PR3 已实现能力中的代码缺陷；
* 更新因 PR3 架构变化而失效的测试；
* 删除只验证已明确废弃旧语义的测试；
* 修复 Fixture、Snapshot、Checkpoint 测试数据和测试辅助代码；
* 修复测试隔离、全局状态清理、确定性和执行顺序问题；
* 对测试脚本增加必要的诊断输出；
* 对 CI 工作流做最小范围修正，但前提是确认属于工作流配置问题。

本任务禁止：

* 开始或实现 PR4；
* 重构 Fee Kernel；
* 增加 A 股费用规则；
* 增加外部费用对账；
* 引入新的业务模块；
* 为了让测试通过而跳过、屏蔽或弱化有效测试；
* 对失败测试统一添加 `skip`、`xfail`；
* 删除仍然验证有效业务语义的测试；
* 修改断言以迎合错误实现；
* 通过放宽精度、顺序、幂等性或一致性要求掩盖问题；
* 恢复已经被 PR3 明确废弃的旧 Execution-specific Persistence 兼容逻辑；
* 为旧 Checkpoint 或旧 Persistence Schema 添加无要求的兼容层；
* 对整个工程进行无关格式化或大范围重命名。

# 三、执行要求

## 阶段 1：建立干净基线

先检查当前仓库状态：

```bash
git status
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
```

要求：

* 当前分支基于最新 `master`；
* 确认基线提交；
* 不覆盖用户已有的未提交修改；
* 如果工作区不干净，先说明已有改动，不要擅自删除。

同步依赖：

```bash
uv sync --frozen --all-packages --all-groups
```

不要修改锁文件，除非确认锁文件本身损坏或与声明文件不一致，并在结果中明确说明原因。

## 阶段 2：复现原始失败

首先执行与 CI 完全相同的命令：

```bash
uv run python scripts/test_suite.py full
```

保存以下信息：

* 失败测试完整节点 ID；
* 完整 traceback；
* assertion 左右两侧实际值；
* 首个失败点；
* 总通过、失败、跳过数量；
* 测试运行时间；
* 是否存在测试超时、进程退出、OOM 或信号终止。

不要在第一次失败后立即修改代码。

如果 `scripts/test_suite.py full` 的输出隐藏了 pytest 细节，检查该脚本实际构造的命令，并使用等价 pytest 命令重新执行失败项，例如：

```bash
uv run pytest <failure-node-id> -vv -s --tb=long
```

必要时使用：

```bash
uv run pytest <failure-node-id> -vv -s --tb=long --showlocals
```

## 阶段 3：最小化失败

对每个失败测试：

1. 单独运行该测试；
2. 单独运行所属测试文件；
3. 按原测试套件顺序运行；
4. 必要时重复运行至少 10 次；
5. 判断是否存在顺序依赖或非确定性。

建议命令：

```bash
uv run pytest <failure-node-id> -vv
uv run pytest <test-file> -vv
for i in $(seq 1 10); do
    uv run pytest <failure-node-id> -q || break
done
```

如果单独运行通过，但完整套件失败，重点检查：

* 模块级或单例 Registry；
* 全局 Clock；
* Event Bus 订阅残留；
* Runtime Registry；
* 临时目录或数据库复用；
* 环境变量污染；
* Checkpoint Store 状态；
* UUID、随机数或序列号；
* 交易日、时区和系统时间；
* monkeypatch 未恢复；
* Mutable Fixture 被跨测试复用。

## 阶段 4：建立根因链

修复前必须明确写出根因链：

```text
触发条件
→ 错误状态如何形成
→ 哪个组件首先违反合同
→ 为什么现有测试捕获了该问题
→ 正确行为应该是什么
→ 应修改生产代码还是测试代码
```

不得仅以“测试预期不一致”“PR3 改了接口”作为根因。

需要判断测试验证的是：

### A. 有效的新架构合同

例如：

* Durable Transaction 原子提交；
* Projection 失败后的 Forward Recovery；
* Settlement Maturity 幂等性；
* Checkpoint 恢复确定性；
* Runtime Ready Gate；
* 多次重放不重复记账；
* Position、Allocation、Settlement、Account 最终一致；
* 新交易日第一根 Bar 前完成应执行的结算；
* Persistence Schema 4 身份一致性。

这种测试失败时，应优先修复实现。

### B. 已废弃的旧架构语义

例如：

* 旧 Execution-specific Persistence；
* 已删除的旧 Coordinator；
* 旧 Schema 可继续无条件恢复；
* 已明确移除的兼容接口；
* 与当前 PR3 设计冲突的测试假设。

这种测试应被重写或删除，并补充验证新合同的测试。

## 阶段 5：实施最小修复

修复必须满足：

* 修改范围与根因直接相关；
* 保持 `Only*` 命名规范；
* 不引入新的重复权威；
* 不绕过 Runtime Transaction Coordinator；
* 不绕过 Projection、Store、Ready Gate 或 Recovery 机制；
* 不在测试中复制生产逻辑来制造相同结果；
* 时间、金额、数量等领域数据继续使用工程既有确定性类型；
* 不使用二进制浮点代替现有 Decimal 语义；
* 不依赖真实当前时间来通过测试；
* 不使用随机等待或增加 `sleep` 解决竞态；
* 不通过扩大超时时间掩盖死锁或阻塞；
* 不吞掉异常；
* 不降低一致性检查。

如果必须修改测试，请说明：

* 原测试验证的旧语义；
* 新语义由哪个测试覆盖；
* 为什么删除或重写不会降低覆盖质量。

# 四、重点检查 PR3 相关区域

根据当前提交范围，优先检查以下领域：

## 1. Runtime Transaction

检查：

* `OnlyPreparedRuntimeTransaction`
* `OnlyRuntimeTransactionCoordinator`
* Runtime Transaction Store
* Transaction Operation 类型
* Projection Commit 顺序
* 幂等键
* Forward Recovery
* Ready Gate
* Transaction Fingerprint

重点确认：

```text
TRADE_FILL
ORDER_TERMINAL
SETTLEMENT_MATURITY
```

是否在：

* prepare；
* durable append；
* projection；
* recovery；
* checkpoint；
* replay

阶段保持相同身份和语义。

## 2. Settlement Maturity

检查：

* 结算指令是否只成熟一次；
* 多 Fill 是否错误合并；
* 多 Cluster 是否串账；
* 交易日切换是否正确；
* 第一根 Bar 前是否完成应完成结算；
* 失败恢复后是否重复增加可卖数量；
* Position、Allocation 和 Account 是否最终一致；
* 恢复时是否错误使用墙上时钟而不是 Trading Day/Runtime Clock。

## 3. Persistence Schema 4

检查：

* Schema Version；
* Snapshot 和 Journal Identity；
* Runtime ID；
* Account ID；
* Cluster ID；
* Transaction ID；
* Operation Type；
* Projection Cursor；
* Checkpoint Fingerprint；
* 恢复后下一序列号。

旧 Schema 不兼容属于允许行为，但必须：

* 明确拒绝；
* Fail Closed；
* 给出稳定错误；
* 不得部分加载后继续运行。

## 4. 测试基础设施

检查：

* `scripts/test_suite.py`
* 测试 Suite 分类；
* full、recovery、ashare 的路径选择；
* pytest markers；
* CI 和本地命令是否一致；
* 测试是否遗漏新目录；
* 是否重复执行同一测试；
* 临时数据库是否按测试隔离；
* Artifact 目录是否互相污染。

# 五、测试补充要求

修复根因后，必须增加或完善能够直接锁定问题的回归测试。

回归测试要求：

* 修复前稳定失败；
* 修复后稳定通过；
* 不依赖测试执行顺序；
* 不依赖本机时区；
* 不依赖真实日期；
* 不依赖网络；
* 不依赖随机 sleep；
* 明确验证业务后置条件；
* 对 Durable 逻辑同时验证正常执行和故障恢复。

如果问题涉及 Transaction 或 Settlement，至少考虑以下场景：

```text
1. 正常一次提交
2. 相同操作重复提交
3. Durable Store 已写入但部分 Projection 失败
4. 重启后 Forward Recovery
5. Recovery 再次执行
6. 最终状态与连续无故障执行一致
```

如果涉及状态隔离，至少增加：

```text
1. 两个 Runtime
2. 两个 Account
3. 两个 Cluster
4. 两个 Order 或 Instruction
```

中的相关交叉隔离场景。

# 六、完整验证门禁

完成修改后，按以下顺序执行。

## 1. 定点回归

```bash
uv run pytest <新增或修改的测试> -vv
```

## 2. 原失败文件

```bash
uv run pytest <原失败测试文件> -vv
```

## 3. Full Suite

```bash
uv run python scripts/test_suite.py full
```

## 4. Recovery Suite

```bash
uv run python scripts/test_suite.py recovery
```

## 5. A-share Suite

```bash
uv run python scripts/test_suite.py ashare
```

## 6. Static Gate

```bash
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-tushare/pyproject.toml \
  packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml \
  packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt
uv run python scripts/version_sync.py check
```

## 7. Build Gate

```bash
uv build --all-packages
```

所有命令必须实际执行，不得仅根据局部测试推断完整门禁通过。

如果某项因环境原因不能执行，必须说明：

* 具体命令；
* 具体错误；
* 为什么属于环境限制；
* 已完成的替代验证；
* 仍然存在的风险。

# 七、结果输出格式

最终输出必须包含以下章节。

## 1. 原始失败

```text
失败命令：
失败测试：
首个失败：
错误类型：
是否可稳定复现：
```

## 2. 根因

使用完整因果链说明，不要只描述表面异常。

## 3. 修改文件

逐个文件说明：

```text
文件路径
修改目的
关键修改
为什么是最小修改
```

## 4. 测试变化

说明：

* 新增哪些测试；
* 修改哪些测试；
* 删除哪些测试；
* 每项变化验证什么合同。

## 5. 门禁结果

使用明确表格：

| Gate         | Command | Result    |
| ------------ | ------- | --------- |
| Focused      | ...     | PASS/FAIL |
| Full         | ...     | PASS/FAIL |
| Recovery     | ...     | PASS/FAIL |
| A-share      | ...     | PASS/FAIL |
| Ruff         | ...     | PASS/FAIL |
| Format       | ...     | PASS/FAIL |
| Mypy Core    | ...     | PASS/FAIL |
| Mypy Plugins | ...     | PASS/FAIL |
| Version Sync | ...     | PASS/FAIL |
| Build        | ...     | PASS/FAIL |

## 6. 剩余风险

只列真实存在且未解决的风险。

如果所有门禁通过，明确说明：

```text
当前 master 已恢复为可验证的绿色 PR3 基线，可以作为 PR4.1 的开发起点。
```

如果仍有门禁失败，明确说明：

```text
当前 master 仍不满足进入 PR4.1 正式实现阶段的条件。
```

# 八、提交要求

完成后：

1. 展示 `git diff --stat`；
2. 展示关键差异；
3. 检查是否存在无关修改；
4. 不自动推送；
5. 不自动创建 PR；
6. 未经明确要求不要修改版本号；
7. 未经明确要求不要更新 CHANGELOG；
8. 不把生成的测试日志、缓存和构建产物提交到仓库。

建议提交标题：

```text
Fix: stabilize PR3 full test gate
```

如果根因更具体，应使用更准确的标题，例如：

```text
Fix: make settlement maturity recovery idempotent
```

或：

```text
Test: align persistence recovery coverage with schema 4
```

# 九、完成标准

只有满足以下全部条件才算完成：

* 已复现原始 CI 失败；
* 已明确根因；
* 已实施最小且正确的修复；
* 已增加能够锁定根因的回归测试；
* `full` 通过；
* `recovery` 通过；
* `ashare` 通过；
* Static Gate 全部通过；
* 所有包构建通过；
* 没有通过跳过测试掩盖问题；
* 没有开始任何 PR4 功能；
* 没有恢复已废弃的旧架构兼容层；
* 最终工作区只包含与此次故障相关的修改。
