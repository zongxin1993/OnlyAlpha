# OnlyAlpha 工程质量工具链

OnlyAlpha 的质量验证按反馈速度和计算成本分层。原则是：开发者运行能最快否定当前修改的最小检查；完整回归、安全扫描和重型分析由 GitHub 自动执行，避免本地等待和重复 CI。

## 执行矩阵

| Tool | Purpose | Local | PR | Nightly | Release |
| --- | --- | ---: | ---: | ---: | ---: |
| Import Linter | Architecture | ✓ | ✓ |  |  |
| Hypothesis | Properties | dev | ci | exhaustive |  |
| Semgrep | Project rules | selective | ✓ |  |  |
| CrossHair | Formal contracts | selective |  | ✓ | critical |
| mutmut | Test strength |  |  | ✓ | critical |
| Branch Coverage | Test paths | optional | ✓ |  |  |
| CodeQL | Static/security |  | ✓ | scheduled |  |
| Dependency Review | Supply chain |  | ✓ |  |  |
| pytest-benchmark | Performance | selective |  | ✓ | ✓ |
| ASV | Historical performance | check |  | ✓ | ✓ |

Dependabot independently checks `uv`, GitHub Actions and pre-commit dependencies weekly. It is not a test lane.

## 本地开发

普通修改只运行 changed-file Ruff、相关 mypy 和相关 pytest。架构边界变化再运行：

```bash
uv run lint-imports
```

Domain invariant 变化运行相关 property tests；默认 profile 是 `dev`（100 examples）：

```bash
uv run pytest tests/property/test_domain_properties.py -q --tb=short
```

Semgrep 只在修改 Domain 确定性或 MiniQMT 边界时扫描相关路径：

```bash
semgrep scan --config semgrep/onlyalpha.yml src/onlyalpha/domain
```

性能关键路径变化可选择运行相关 pytest benchmark。ASV 配置变化运行 `asv check`。CrossHair 仅在对应纯函数合同变化时运行指定文件或函数。

本地普通开发不要运行完整 coverage、CrossHair 全量、mutmut、ASV 历史、CodeQL、Dependency Review 或 exhaustive Hypothesis。这些检查耗时更长且已有唯一自动执行层。

## Pull Request

`quality.yml` 执行完整 Ruff、format、mypy、Import Linter、Semgrep、构建和产品专项 lanes。`core-full --coverage` 是 fast/integration/core regression 与 branch coverage 的唯一完整执行，使用 `HYPOTHESIS_PROFILE=ci`（300 examples），不会再重复执行 fast 和 integration suites。

CodeQL 与 Dependency Review 使用独立职责 workflow。Dependency Review 对新引入的 `high` 及以上漏洞 fail closed。

Coverage 统一写入 `test-results/coverage/`，runner 只打印 line/branch 摘要。初始 baseline 的综合覆盖率为 83%，PR floor 设为 82%，在阻止明显回退的同时为平台差异保留小幅余量。

## Nightly 与 Release

Nightly 只承担 PR 未执行的重型验证：exhaustive lane/Hypothesis（2000 examples）、CrossHair contracts、限定 Domain value-object mutation baseline、pytest-benchmark 和 ASV 当前提交性能点。它不重复 PR 已覆盖的 core-full、recovery、A-share、MiniQMT contract 或 build。

Release workflow 运行 critical formal/mutation subset 和稳定性能指标。普通 PR 不等待这些重型任务。mutation 初期只报告 generated/killed/survived/timeout，不以任意分数阻塞 PR。

## 常用命令

```bash
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py core-full --coverage
HYPOTHESIS_PROFILE=ci uv run pytest tests/property -q --tb=short
uv run crosshair check tests/formal/contracts.py
uv run mutmut results
uv run pytest tests/performance/test_quality_benchmarks.py -q --benchmark-only
asv check
```

生成的 coverage、mutation、pytest-benchmark 和 ASV 结果均被 `.gitignore` 排除，不应提交机器相关 cache 或绝对路径。
