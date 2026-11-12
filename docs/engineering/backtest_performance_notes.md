# 回测性能测量口径

本文件规定回测与内核吞吐的测量口径、可比较范围和已确认的成本结构。

它是 `AGENTS.md` 第 4 节性能验证的方法说明，不拥有独立的 Task Acceptance、Architecture、Quality、Progress 或 Certification Authority。某次运行的数字属于任务上下文与基准输出，不进入本文件作为结论；与 `PROJECT_CONSTITUTION.md`、架构契约或已接受 ADR 冲突时，以更高层 Authority 为准。

---

## 1. 为什么需要口径

回放吞吐的两个直观说法都不成立，混用会得出错误结论：

- **“每秒多少根 K 线”不是内核的计量单位。** 内核的一步是一次可持久化的 Replay 状态转移；原生 next-open 参与者把一根 K 线拆成 OPEN 与 BAR 两个阶段，因此 740 根 K 线产生 1481 步（`crates/backtest/src/run.rs` 的步生成、`packages/backend/src/workers/backtest_service.rs` 的进度换算）。同一段行情按不同参与者数量换算的“K 线/秒”可以相差数倍。
- **端到端耗时不等于回放速度。** 一次 Run 的墙钟时间还包含 Preparation、行情物化、结果封板和工件写入。封板按多遍全历史 pass 计算（`packages/backend/src/workers/backtest_result.rs`），在短 Run 中可能占主要部分。

因此任何性能陈述必须同时给出：步数口径、计时边界、构建档、运行环境与存储类型。缺任一项时只允许说“本次观察”，不得用于比较。

## 2. 计时边界

- `create`：运行时目录、SQLite 建库与绑定写入，不含策略执行。
- `run`：从首步到末步提交完成，不含封板。基准输出按步数换算 `steps_per_s`，并给出中位数与样本数。
- `seal`：结果封板与工件发布。`run + seal` 才对应产品在 Web 上从“运行中”到“已完成”的等待。

比较优化效果时只比较同一边界内的数字；跨边界必须显式相加并说明。

## 3. 构建档与运行环境

- 工作区在 `Cargo.toml` 中对 `dev` 与 `release` 都启用 `overflow-checks`，`release` 未启用 LTO。构建档差异不足以解释数量级差距，任何“因为用的是 debug 所以慢”的判断都必须先核对实际启动的二进制（本地 Web E2E 走 release 构建，见 `scripts/native_http_contract.py` 与 `scripts/native_workstation_build.py`）。
- 内核测试与基准在容器内运行。容器根是 overlay，宿主 bind mount 是 virtiofs，两者的 `fsync` 与文件锁行为不同；`synchronous=FULL` 下这个差异直接进入每步成本。运行环境 MUST 记录：镜像、是否容器本地存储还是 bind mount、宿主 OS 与 CPU 代次。
- `scripts/dev_verification.py` 的冻结只读视图是正式验证入口。基准测量若使用一次性容器，必须在报告里写明“非正式验收拓扑”，不得冒充正式验收证据。

## 4. 已确认的每步固定成本结构

以下是结构事实，不是速度结论：

- **每步两次 SQLite 提交**，库以 `journal_mode=DELETE` 与 `synchronous=FULL` 打开，`busy_timeout` 为零（`crates/runtime/src/store.rs`）。回滚日志模式下写者提交需要短暂独占，读者在读事务内会阻止该独占窗口。
- **每个不可变 JSON 工件 5 次 `fsync`**：stage 目录、文件本体、stage 目录、目标目录、目标父目录（`packages/backend/src/security/immutable_json.rs`）。逐事件发布工件时，`fsync` 次数按事件数线性增长。
- **每步 canonical JSON 与 SHA-256**，以及按序号重复读取 records/replay 行的路径（`crates/runtime/src/references.rs`、`store.rs`）。
- **每步一次全历史校验**：回放结果每步调用 `check()`，其内部 `verified_source_with_genesis` 遍历 `1..=sequence` 的全部账户交易（`crates/execution/src/reconciliation.rs`）。`sequence` 是账户交易笔数，不是 K 线数。只有在真正产生账户交易的 Run 上才出现，且总代价随交易笔数呈二次增长。
- **每步增长主要落在提交路径**：增长探针按段拆分后，每步成本随账户交易笔数的增长集中在 `coordinate`（提交与投影推进）与 `prepare`（规划与前置校验），只读投影次之；只读全链对账 `reconcile` 的边际成本明显更低，其遍历有折叠缓存支撑。因此“每步都校验历史”不是主要成本项，优化应针对提交路径的历史折叠，而不是先动对账遍历。具体占比属任务上下文，按第 6 节复现。
- **不是瓶颈的部分**：指标增量流不逐步重算全序列；行情只物化一次；每步写入不经过 PostgreSQL。

## 5. 与开源回测速度的可比范围

外部公开数字与 OnlyAlpha 不是同一单位工作量，引用时必须带上其口径：

| 引擎 | 公开口径 | 数值 | 来源 |
| --- | --- | --- | --- |
| NautilusTrader（Rust） | 20 000 事件纯回放（`run_preloaded`），bar EMA 交叉含 450 笔成交，LTO 构建，机器相关 | 23.285 ms / 37.326 ms | [BENCHMARKS.md](https://github.com/nautechsystems/nautilus_trader/blob/master/crates/backtest/benches/BENCHMARKS.md)（v2，2026-08-10） |
| backtrader（Python） | 事件驱动、含下单的逐 bar 循环 | 约 12 700 candles/s | [backtrader 官方博客 2019-10-25](https://www.backtrader.com/blog/2019-10-25-on-backtesting-performance-and-out-of-memory/) |
| vectorbt | 向量化：1 000 bar × 1 000 列，100 万订单 | 0.058820 s | [vectorbt Features 文档](https://vectorbt.dev/getting-started/features/)，自陈不构成通用速度优势 |
| zipline-reloaded / QuantConnect LEAN | 未公布可核对的绝对吞吐 | 无 | 官方文档与仓库 |

以上口径都不含“每步可持久化状态转移 + 逐事件不可变工件 + 每步全历史校验”。因此正确表述是：**单位工作量不同，不能直接比较绝对速度；但 OnlyAlpha 每步固定开销的构成需要按第 4 节逐项证明，再决定优化顺序。** 声称“达到或超过某开源速度”必须先复现对方的口径。

## 6. 基准入口与解读

- `cargo bench -p onlyalpha-backtest --bench replay_throughput`：空参与者回放骨架，给出每步固定开销基数与增长比例；`OA_BENCH_SIZES` 覆盖步数。骨架不产生成交，因此不含交易链二次项。
- `cargo test -p onlyalpha-execution --release --test chain_growth -- --ignored --exact --nocapture`：用内存 `MemoryStore` 隔离账户交易链的增长形态。`reconcile_once_us` 是单次全链校验成本，`chain_replay_ms` 与 `chain_append_ms` 之差是“每步校验前缀”的净开销，`fixture_total_ms`、`prepare_total_ms`、`coordinate_total_ms` 拆分每步提交路径成本，`quadratic_model_ms` 用于核对二次拟合。该探针默认忽略，且因内核布局闸门只能位于 `tests/`。
- SQLite 并发行为属于故障与锁语义，不用 `cargo bench` 承载；按第 4 节的打开参数在容器内构造写者与只读观察者并发，分别记录写者提交延迟、`SQLITE_BUSY` 次数和读者持锁时长。

比较规则：同一台机器、同一镜像、同一 profile、同一存储类型；至少 1 次预热加 3 次取样取中位数；同时记录工作目录大小与 `profile` 自报字段。缺少任一项时，结论降级为“本次观察”。

## 7. 尚未证明的部分

LTO 与代码生成选项的影响、WAL 或降低 `synchronous` 对恢复语义的影响、封板多遍 pass 的合并、每步工件批量发布、全链校验的增量替代，都改变持久化、恢复或证据语义，MUST 先出 ADR 并按 `AGENTS.md` 第 4.3 节取得专项证据与独立审查，不得以性能基准结果直接实施。
