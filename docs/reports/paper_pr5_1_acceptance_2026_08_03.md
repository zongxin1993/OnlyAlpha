# PR5.1.1 MiniQMT Historical Warmup Isolation 验收报告（2026-08-03）

## 结论

```text
Isolation Implementation : PASS
MiniQMT Compatibility     : BLOCKED
Paper Product Acceptance  : FAILED
```

隔离实现已经把不可捕获的 XtQuant native abort 限制在单请求 Worker 子进程，并转换成可诊断的 `WORKER_ABORTED`。本机真实兼容性矩阵 13/13 Case 仍触发相同 BSON assertion，没有任何可用参数组合，因此不能宣称 MiniQMT Historical Warmup 或 Paper 产品验收通过。Warmup 保持 `REQUIRED`。

## 修改前审计

修改前的正式路径为：

```text
OnlyEngine
→ Paper Runtime
→ OnlyStreamingRuntime._bootstrap
→ MiniQMT DataSource.load_bars
→ Historical Cache Provider（Cache miss 时）
→ historical.load_bars
→ download_history_data / get_market_data_ex
```

XtQuant 在 OnlyAlpha 主解释器内进入 BSON C++ assertion。`try/except`、`finally` 和线程都不能拦截 `abort()`，因此 Engine、Runtime、Clock、EventBus 和清理流程存在同时终止的风险。现有 Cache 能校验 Parquet 覆盖，但 Cache miss 仍在主进程回源，且 Key 尚未包含 data version 与 compatibility profile。Paper bootstrap 在历史成功后才订阅实时行情，失败会关闭资源，但 native abort 发生时 Python 没有机会执行该路径。

## 架构与协议

Core 新增 provider-neutral `OnlyHistoricalWarmupRequest/Result/Diagnostic/Status/Port`，不导入 MiniQMT、XtQuant、pandas 或 BSON。MiniQMT 插件使用：

```text
Parent Isolated Client
→ request-scoped work directory
→ sys.executable -m onlyalpha_plugin_miniqmt.historical_worker.worker
→ delayed import xtquant
→ one historical request
→ atomic JSON/JSONL result
→ process exit
```

线程不能隔离进程级 abort；显式 subprocess 可以。每请求一个 Worker 可避免 SDK 状态污染，能保留真实 stdout/stderr 和退出码，也保证没有 Runtime、Clock、EventBus、Cluster 或 Callback 被继承。正式 Runtime 只消费显式 Profile，不自动盲试参数；诊断矩阵的每个 Case 单独启动 Worker。

协议版本为 `1`：

- Request：简单 JSON 类型，UTC ISO/ns，Decimal 字符串，包含 Profile 与 Instrument precision；
- Result：provider、row count、首末 Bar、Request/Content/Bars File Fingerprint；
- Failure：结构化 status/code/exception/message/有界 traceback；
- Exit Code：`0, 10..18, 21, 22`；无有效 Failure Manifest 的异常退出映射为 `WORKER_ABORTED`；
- Atomic Output：`.bars.jsonl.tmp/.result.json.tmp/.failure.json.tmp → flush → fsync → os.replace`；
- Parent 重新验证协议、三个 Fingerprint、数量、顺序、唯一性、OHLC、正负值、周期、Instrument、价格精度和闭合边界。

Cache Key 已加入 data version 与 compatibility profile。只有完整覆盖当前请求且 manifest/fingerprint 有效时才复用；过期 Coverage 会重新启动 Worker，Worker 失败不会回退到旧数据。

## Paper Bootstrap

Paper Runtime 不再通过通用 `load_bars()` 执行正式 Warmup，而只接受 Historical Warmup Port。成功 Bar 进入正式 MarketData Processor，并建立 `last_historical_bar_end`。为避免 1m Warmup 从 3m 聚合窗口中间开始，Runtime 会按内部周期 LCM 请求有界 overlap，并在 Trading Calendar Session 边界选择可对齐起点。失败发生在实时订阅前，Runtime 进入 `FAILED`，DataSource/Clock/EventBus 被关闭；不存在 `subscribe_quote(count=...)` 历史旁路。

## 修改文件

新增：

- `src/onlyalpha/data/warmup.py`
- `packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/historical_worker/{__init__,models,protocol,client,worker,query,validation,compatibility,exit_codes,cache}.py`
- `scripts/diagnose_miniqmt_historical.py`
- `tests/data/test_historical_warmup.py`
- `packages/provider/onlyalpha-plugin-miniqmt/tests/helpers/historical_worker.py`
- `packages/provider/onlyalpha-plugin-miniqmt/tests/test_historical_worker.py`
- `tests/integration/test_engine_paper_historical_warmup.py`
- `docs/miniqmt_historical_isolation.md`
- `docs/paper_runtime.md`
- 本报告

修改：

- `src/onlyalpha/plugin/data_source.py`
- `src/onlyalpha/cache/historical/models.py`
- `src/onlyalpha/cache/historical/fingerprint.py`
- `src/onlyalpha/runtime/streaming/config.py`
- `src/onlyalpha/runtime/streaming/runtime.py`
- `src/onlyalpha/runtime/paper/factory.py`
- `packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/data_source/resource.py`
- `packages/provider/onlyalpha-plugin-miniqmt/tests/integration/test_real_xtquant_history.py`
- `tests/architecture/test_paper_streaming_boundaries.py`
- `tests/position/test_position_component.py`
- `examples/configs/miniqmt_paper_macd.yaml`
- `README.md`
- `docs/roadmap.md`

未修改 `schema_version`，未增加生产 test mode，未运行 `pre-commit`。

## 自动化验收

```text
uv lock                                                        PASS
uv sync --frozen --all-packages --all-groups                   PASS
uv run ruff check src tests examples packages scripts          PASS
uv run ruff format --check src tests examples packages scripts PASS
uv run mypy src/onlyalpha                                      PASS (427 files)
MiniQMT plugin mypy                                            PASS (35 files)

scripts/test_suite.py fast              PASS (926 collected)
scripts/test_suite.py integration       PASS (105 passed)
scripts/test_suite.py miniqmt-contract  PASS (23 passed)
scripts/test_suite.py ashare            PASS (22 passed)
scripts/test_suite.py recovery          PASS (240 passed)
scripts/test_suite.py full              PASS (1296 collected)
```

Native abort 自动化证据：测试 Worker 执行 `os.abort()` 后，父 pytest 继续执行；结果为 `WORKER_ABORTED`，保留非零真实退出码及 stdout/stderr tail，没有有效 `result.json`，Paper Runtime 集成测试在 live subscribe 前进入 `FAILED`，无残留 Worker。

## 真实 MiniQMT 结果

环境：Windows、本地 `userdata_mini` 存在、XtQuant 可导入、`XtMiniQmt` PID 13044 正在运行。诊断输出位于本机临时目录：

```text
C:\Users\zongxin.DESKTOP-MVCBG71\AppData\Local\Temp\onlyalpha-miniqmt-history-pr511\report.json
```

结果：

```text
PASS            : 0
PROCESS_ABORT   : 13
Worker exit code: 3221226505 (all cases)
stderr          : Assertion failed: u < 1000000, bsonobj.cpp line 1388
```

失败 Case 包括 `TIME_RANGE`、`END_TIME_WITH_COUNT`、`COUNT_ONLY`；Count `1/10/50/100/200`；Period `1m/5m/1d`；download on/off；default/explicit fields；`fill_data` false/true。候选 `miniqmt-history-v1` 的正式 1m/50 Warmup 同样返回 `WORKER_ABORTED`。`scripts/test_suite.py miniqmt-local` 已真实执行并按严格成功断言失败，不能记为通过。

进程隔离解决了 OnlyAlpha 主进程安全性，但没有修复 XtQuant native Bug。后续只有取得至少一个真实 PASS Profile 并完成 PR5.1.2～PR5.1.5 的 Catch-up、恢复与产品闭环后，才能重新评估 Paper Product Acceptance。
