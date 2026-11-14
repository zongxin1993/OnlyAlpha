# runtime 性能基准

## 职责与范围

直接测本模块的正式公开入口；具体操作见共享 [inventory.json](../../test-data/backtest-benchmarks/inventory.json)。不产生 Product 准入或完成事实，不以组件计时替代 Web 验收。

## 输入与口径

使用受控 740-bar 回测派生的原始值及 64/129/326 前缀，配置/数据摘要见 provenance.json。Execution 为三种完整组件恢复与受控内存 Store 的同前缀 ADMIT 规划。Runtime/Backtest 为原始保留 runtime 的固定次数慢基准，不自动扩增迭代，不把小骨架解释为真实终态成本。

## 执行

`cargo bench --frozen --offline -p onlyalpha-runtime --bench retained`（Cargo bench 默认 release，不需要额外切换 profile）。慢基准需显式 OA_BENCH_RUNTIME 指向与 replay.json 绑定一致的保留目录，OA_BENCH_ROUNDS 默认3；缺输入明确失败。输入/元数据准备在计时外；各阶段含其内部复核、输出未使用的作用域末析构不计入阶段。当前完整引用样本不会冒充三个不同 runtime 历史规模；三档 Runtime 增长用例需要独立生成有效持久化样本后运行，不能截断 SQLite 冒造前缀。

## 参考基线

2026-11-13，固定 onlyalpha-dev，Linux aarch64，Rust 1.99.1，bench/release优化，单编译任务。源码冻结摘要 `95f65185431cd4be521fe8fff8ced2bf1eba3e528c00908b2b22bf325f5685d4`。首个target输入摘要 `8ef966afc9bcd945615432573457a9252967c92638822f6635f5248b11a005b2`；各target独立的输入、结果与二进制SHA256见原始identity.json，不把历史kernel绑定作为当前构建身份。

Criterion为每case至少10个原始样本；表中使用Criterion的median估计。固定慢样本使用3轮中位数，不据此推断可靠尾延迟。状态准备、缓存和析构边界以本页方法说明及case源码为准；没有清OS缓存，也没有硬件独占。原始结果：`test-results/backtest-observability/reference-01/runtime/`（本轮位于主工作区）；包含build、identity、reference.log、report及Criterion原始样本。

| 场景 | 每次工作量 | 中位耗时 ms | 吞吐 /秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| sqlite.runtime/apply_valuation_history/128 | 128 elements | 3776.13 | 33.8971 | 10 |
| sqlite.runtime/apply_valuation_history/32 | 32 elements | 646.409 | 49.5043 | 10 |
| sqlite.runtime/apply_valuation_history/8 | 8 elements | 136.453 | 58.6284 | 10 |
| sqlite.runtime/open_recover_close/128 | 131 elements | 3945.77 | 33.2001 | 10 |
| sqlite.runtime/open_recover_close/32 | 35 elements | 411.282 | 85.0998 | 10 |
| sqlite.runtime/open_recover_close/8 | 11 elements | 94.192 | 116.783 | 10 |
| source.read | 1482 replay_entries | 10253.9 | 144.531 | 3 |
| source.steps | 1482 replay_entries | 1417.08 | 1045.81 | 3 |
| source.verify_cut | 1482 replay_entries | 10011.5 | 148.029 | 3 |

增长观察（同一case的最大输入/最小输入总耗时比；仅说明这三档输入，不据此证明渐进复杂度）：

- `sqlite.runtime/apply_valuation_history`：27.67 倍（128/8）。
- `sqlite.runtime/open_recover_close`：41.89 倍（128/8）。

## 限制

原始样本与环境/构建身份外存；输入/结果不匹配或样本不完整禁止比较。历史工件值仅用于技术输入绑定，不赋予当前可执行文件历史读取 Authority。原 300/120 秒门槛不变，无新 CI 性能阈值。

## 可生成的三档持久化恢复

`cargo bench -p onlyalpha-runtime --bench recovery` 用公开 Runtime API 创建隔离临时数据库，原有集成输入完成开仓/成交后产生8/32/128次估值，保存实际checkpoint再测open/recover/close。准备与完整状态预检在外，计时包含打开、恢复和关闭；无需依赖保留目录。这是受控Execution存储恢复，不冒充含1482个native回放step的完整Source读取。只清理本次独占创建的pid/规模临时目录。

同组 apply_valuation_history 测8/32/128次完整 Runtime::apply（含组件执行与持久化日志追加）。每轮使用独占新数据库，建库及首3条开仓/成交准备在外，估值输入预生成并在原样本上验证；计时不含关闭和临时目录删除。它与 open_recover_close 分开报告。

## 同一原始 Source 的观测开销

`retained` harness 显式支持 `OA_BENCH_DIAGNOSTICS=off|detail`（默认 off）。计时仍只包含原 read、steps 和 verify_cut；Session 创建、线程启动及关闭/flush 在计时外，sink 使用标准库空 writer，队列容量65536，关闭时必须无丢失及 I/O 错误。每轮仍核对原 binding、326条执行记录、1482条 replay entry 和完整结果状态摘要。该对照测量 JSON 编码、关联与队列提交成本，不代表真实磁盘写入开销。

统一运行器可选择 `--crate runtime --target retained --diagnostics off` 或 `detail`；两种模式使用同一冻结源码和同一编译工件。身份文件与报告记录模式及关闭收据。普通代码回归比较拒绝跨模式；`compare_observation_overhead` 仅允许模式不同，并要求输入、结果、工作量、完整样本、环境、二进制和源码完全相同。上表历史 retained 基线来自增加此入口之前的 harness，不能与新 harness 绕过输入摘要检查直接比较。

2026-11-14 固定 onlyalpha-dev 实测（递增诊断ID修正后）：冻结源码 `e59f106730da49f3400106a56cb1657312e324da1b60a07b05661eb2776bb1f3`，Linux aarch64、Rust1.99.1、bench/release；同一二进制 SHA256 `5148af18e4168e5bce0b52846bbdb46d21c7146d13ed3ee1c5f9db37460300ec`，相同输入摘要 `132fac50f5cb442289fd7a3067e02dfe844ce97ad4f5c1e3275563192e133dff`。先 Off 后 Detail 各3轮，读取1482条 replay entry；没有清除缓存或硬件独占。结果相等，两个模式关闭收据均完整、无丢失和 I/O 错误。

| 场景 | Off 中位 ms | Detail 中位 ms | Detail/Off |
| --- | ---: | ---: | ---: |
| source.read | 11221.7628 | 11370.1672 | 1.0132 |
| source.steps | 1507.9781 | 1559.0274 | 1.0339 |
| source.verify_cut | 10279.6440 | 10649.4565 | 1.0360 |

原始报告在主工作区 `test-results/backtest-observability/reference-runtime-off-02/runtime/retained/`、`reference-runtime-detail-02/runtime/retained/`，配对检查为 `runtime-observation-overhead-02.json`。本表仅为当前工作量、环境及顺序下的观测开销，不推断真实 Web 的磁盘开销或代码优化收益。旧01数据保留，但不作为当前ID实现的开销结果。

用于后续比较的补证报告位于主工作区 `test-results/backtest-observability/storage-verified/` 对应参考目录；只从原 identity 的 mountinfo 和本轮原始命令路径导出 storage v1，保留原 report/identity SHA、命令日志与迁移记录，未改原样本、结果或构建身份。Runtime 配对结果为该目录下 `runtime-observation-overhead-02.json`。其余缺少可证明存储条件的历史报告只作原测量展示，拒绝用于同条件比较。
