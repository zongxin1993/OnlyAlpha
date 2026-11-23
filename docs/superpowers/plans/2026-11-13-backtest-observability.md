# 回测基准与后端可观测性实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 每个任务完成定向验证后再进入下一项；高风险接入由非实现者独立审查。

**Goal:** 让当前回测链路拥有逐库可信基准、统一日志/追踪和可复核的实际性能归因，先分析现有慢问题，不进行速度优化。

**Architecture:** 业务库拥有各自 benches/ 与 BENCHMARK.md，工程脚本统一基准报告；onlyalpha-observability 作为基础设施库统一诊断协议和采集。后端初始化并管理订阅器，基础设施边界发 span，纯内核生产代码保持确定性。

**Tech Stack:** Rust stable、Cargo bench、tracing/tracing-subscriber、Criterion 短基准、固定样本慢基准、JSONL、既有 Python 汇总与 onlyalpha-dev 验证入口。新增依赖以设计批准和依赖检查通过为前提。

**Spec:** [设计草案](../specs/2026-11-13-backtest-observability-design.md)

## Global Constraints

- 方案确认后才开始实现；当前计划不是实施或新增依赖的授权。
- 不进入原 Account/估值优化第二阶段；不改变业务输出、正式事实、身份、存储/恢复格式、权限或租约。
- Web 300/120 秒、退出 20 秒、三次尝试停止规则和资源异常停止规则保持。
- 依赖数据库/运行应用的本地验证使用既有 onlyalpha-dev 固定拓扑及冻结源码，不新起第二套服务。
- 性能数据是诊断副本，不得进入正式 checkpoint、正式摘要或被用作 CompletionProof。
- 不为收集指标扩大纯内核接口、放宽纯性检查、将整库豁免门禁或在正式路径做额外全量编码。
- 不新增全仓日志迁移、日志服务、性能 CI 阈值或调优；只迁移当前回测及支撑它的启动/请求/错误边界。

## Review Focus

1. 多请求/任务跨 await、spawn_blocking、后台任务接续时关联不能串线；任务 C/D 有明确并发关联测试。
2. 父子并发重叠、异常缺 end、SIGKILL、日志丢失不能产生虚假独占时间或成功结论；任务 C/E 覆盖。
3. 锁身份/持锁者/争用 command 缺失时必须标记未知，不能靠时间邻近冒充直接身份；任务 D 测已知及未知归属。
4. 新开关、日志字段、输出故障和性能采样不能改变原业务结果或泄露凭据；任务 C/D 做模式一致性与泄露测试。
5. 基准状态累积、输入规模变化、构建身份混淆和不完整样本会使比较失真；任务 A/B/E 设拒绝用例。

## A. 冻结覆盖矩阵与依赖选型

**文件**
- 新增 docs/engineering/backtest-performance-coverage.md：长期场景清单与代码/基准/span 导航，不存本轮进度或验收快照。
- 核对 Cargo.toml、Cargo.lock、各实际模块 Cargo.toml、docs/repository-product-architecture.md、scripts/rust_kernel_check.py。
- 实施证据保存 test-results/backtest-observability/<operation>/，不提交临时报告作规范。

**输入/输出接口**
- 输入：当前正式回测源代码、既有实测、依赖图。
- 输出：每行包含 crate、实际入口、操作/分支、work unit、三档输入、fixture 归属、bench target、span 对应、预期结果、测量限制的完整矩阵。
- 输出：批准后的精确依赖版本/features/许可/MSRV/离线镜像变化清单。

- [ ] A1. 从设计中的 21 个依赖候选及后端补充候选核对真实调用方；区分注册、校验、执行，未使用模块注明依据，不创建占位基准。
- [ ] A2. 对每个实际操作明确小/中/大规模，选择可重复正常与失败输入；恢复场景包含历史长度/checkpoint 数；准入包含成功/拒绝、原始输入/复算、冷/复用。
- [ ] A3. 核对 tracing 已有版本、subscriber/可选 appender/Criterion 正式发布版本及依赖闭包；使用最小 features，版本锁定，记录 MIT/Apache 等许可及 MSRV 的实际发布包依据。
- [ ] A4. 按批准设计明确基础设施依赖归属：pure 内核只允许 bench/dev 依赖，Runtime/Backtest 观测只进入已分类的基础设施组合边界。更新架构导航；若需要新的架构决定则先走相应审批，不自行改 Constitution。
- [ ] A5. 集中完成 Cargo/锁文件/固定工具镜像需要的依赖登记，按既有入口构建并验证离线解析。不得因镜像缺包而偷偷使用宿主 Cargo 或在线下载运行依赖。

**验收：** 矩阵的每个“已覆盖”条目都有实际调用与可执行入口；新依赖清单经负责人确认；Kernel 生产依赖方向未改变。后续工作严格按矩阵，不将 Cargo 可达性等同于实际执行覆盖。

## B. 逐库 Cargo benches 与 BENCHMARK.md

**文件**
- 为任务 A 每个确认涉及的 crate 新建 benches/<操作>.rs、BENCHMARK.md，更新 Cargo.toml [[bench]] harness=false、README 使用入口及必要 dev-dependencies。
- 共享数据置 test-data/backtest-benchmarks/，单库数据置所属 benches/。
- 将 crates/backtest/tests/checkpoint_restore_profile.rs 的基准职责迁入 benches/；保留必要功能断言，验证调用方迁移后再删除旧基准入口。
- 将 backend/tests/workers/backtest_profile.rs 迁为后端组合基准，避免拿它代替库自己的功能吞吐量。
- 扩展 scripts/backtest_benchmark.py，新增 scripts/tests/test_backtest_benchmark.py 的场景/schema 用例。

**接口**
- 快基准：Criterion 分组使用稳定 case_id 与 Throughput::Elements/Bytes，公开接口及功能期望来自任务 A 矩阵。
- 慢基准：Cargo bench 自有 main，固定轮数/预算，用本任务的报告格式；准备/被测/析构范围单独声明，旧 OA_BENCH_* 输入可在迁移期映射。
- 统一运行器输出每 case 的原始样本、来源、统计和完整性；不自行重写 Criterion 的统计推断。

统一基准 v1 报告沿用现有脚本并版本化：scope/case、输入/配置/结果摘要、当前 binary/source/compiler/features/target、硬件/存储/缓存、工作量/单位、原始样本、计时范围和完整性。先以既有 restore/chain 原始日志作 schema 回归，测试缺轮次、重复阶段、不同输入/环境/结果、历史工件冒充当前二进制身份均被拒绝。此任务不依赖新观测库。

- [ ] B1. 先建 account/position/order/strategy-ledger、execution/runtime/backtest 的恢复与核验基准，直接服务当前热点；对照当前真实样本及确定性小样本，校验结果和错误分支后再计时。
- [ ] B2. 补 domain/clock/predicates/operators/indicators/calculation/strategy 等计算类的实际调用基准；窗口/历史/图规模三档，状态准备不混入更新吞吐量，不把单机合成 skeleton 称作产品吞吐量。
- [ ] B3. 补 risk/fee/margin/settlement/broker、market-data/construction、calculation-bridge 及确认使用的元数据库；插件与后端组合另表记录，进程/存储/IPC 边界明确。
- [ ] B4. 每个 case 都跑功能预检、smoke 规模和正式参考规模；外部服务场景全部串行走 onlyalpha-dev，纯库可在有工具链的宿主执行并记录平台。不要重复运行全部慢场景来掩盖失败。
- [ ] B5. BENCHMARK.md 使用统一模板：目的/入口、输入规模、计时边界、运行方法、带证据链接的参考基线、增长曲线、限制与比较条件。写入实际数字，不预填预估吞吐量。
- [ ] B6. 校验矩阵每个实际操作都有 bench 与文档导航；重复旧 harness 在迁移验证后收敛，不能保留两套相互冲突的统计口径。

**验收：** 每库 reference 基线可复跑，输入与结果正确，跨版本同条件可比较。既有真实输入至少三轮完整记录；不完整样本禁止输出“性能提升”。没有公开入口的内部算法只报告所属操作总成本，不为跑分扩 API。

## C. 建立 onlyalpha-observability 最小库

**文件**
- 新增 crates/observability/Cargo.toml、README.md、BENCHMARK.md。
- 新增 src/lib.rs、context.rs、layer.rs、output.rs、schema.rs。
- 新增 tests/context.rs、tests/output.rs、tests/schema.rs，benches/overhead.rs。
- 修改根 Cargo.toml；按实际分类精确维护 scripts/rust_kernel_check.py 及其对应测试，禁止 broad ignore。

**建议公开接口（仅基础设施）**
```rust
pub enum Mode { Off, Basic, Detail }
pub struct Config { /* 显式模式、过滤、输出和有界容量；不自行读取 env */ }
pub struct Session { /* 输出线程/guard 生命周期及 loss 统计 */ }
pub fn install(config: Config) -> Result<Session, InitError>;
pub struct Correlation { /* request/command/run/attempt，显式传递 */ }
```
协议带 process_instance 单调原点及 start/end_mono_ns、duration_ns、wall_time_unix_ns；operation 明确结束，第一版不测 poll-active/CPU。

tracing 的 Span/Instrument 直接复用，不另造 span 调度/线程局部栈。Config 具体字段以批准设计定义，后端 bootstrap 负责从现有启动配置构造。Session 的关闭/刷新必须有界，重复初始化返回明确诊断错误；库调用方不能安装第二套全局订阅器。

观测协议与基准报告分别版本化。观测库不兼任基准运行器；它产生的 operation/module 与任务 B 的 case 通过报告关联，不能直接把不同场景的耗时相除。

- [ ] C1. 先写失败测试：并发两条 trace 跨 await 后仍归属各自父 span；spawn_blocking 显式传播；HTTP 与后台任务通过 link 关联；单进程重启使用新的 process_instance 而保持原 command/run 关联。
- [ ] C2. 实现 tracing Layer 的事件字段白名单、span 关联与 JSONL；future 使用 Instrument，禁止跨 await 持有 enter guard。stdout 保留给既有算法协议，诊断写 stderr/独立文件。
- [ ] C3. 写并实现时间归因测试：父 100 单位、两个重叠子区间 [10,60] / [40,80]，子并集 70、父未覆盖 30；不能简单用 50+40 扣减。缺 end/父关系缺失/日志丢失标不完整，不给完整独占结论。单调时间用于同进程，跨进程不虚构纳秒同步。
- [ ] C4. 使用成熟有界非阻塞 writer；测试队列溢出、磁盘错误、关闭超时、重复初始化。业务返回值保持，日志丢失/输出异常可见；不承诺所有诊断事件永不丢失。
- [ ] C5. 建立观测 schema 及旧 BACKTEST_PROFILE 日志读取适配；版本不支持、关联缺失、缺结束和字段泄露均有测试。旧日志缺失的字段保持未知，不能补成完整证据。
- [ ] C6. 测 Mode Off/Basic/Detail 的 no-op/span/event/跨任务成本，单独记录 BENCHMARK.md；新库 README 五个章节及链接检查通过。

**验证：** cargo test -p onlyalpha-observability；该库 Clippy；生产依赖边界/纯性检查；定向 writer 与异步协议测试。检查结果必须绑定实际冻结源码及环境。具体 Cargo 指令通过项目已有 compiler_environment 准备，不引入另一套工具链。

## D. 接入后端完整回测链路

**文件**
- packages/backend/src/main.rs、bootstrap/workstation_startup.rs 及实际配置装配文件。
- transport/host_backtest_preparation.rs、host_backtest_environment.rs、host_backtest.rs。
- workers/backtest_worker.rs、backtest_service.rs、backtest_result.rs。
- persistence/backtest_evidence/context.rs、store.rs、backtest_run.rs、research_runtime.rs。
- crates/runtime/src/readonly.rs、store.rs 及 Backtest 实际基础设施边界。
- 测试新增 packages/backend/tests/transport/observability.rs、tests/application/observability.rs（在 Cargo.toml 声明对应目标），更新受影响现有测试。

**接口**
C 的 Correlation 随命令/任务监督上下文显式传递，不能加入正式请求 DTO、checkpoint 或身份摘要。同步边界使用 tracing span，async/线程按设计传播，锁观测记录原锁身份；任何 span 都不拥有业务状态。

- [ ] D1. 后端启动仅初始化一套配置/Session，子角色按既有启动边界继承诊断关联。纯 OpenAPI/契约导出及算法协议命令不得被额外日志 stdout、文件或线程副作用污染。
- [ ] D2. 先测现有场景的 Off/Basic/Detail 结果一致：状态、checkpoint、业务错误码、事实身份不依赖诊断开关；测试凭据/正文不会进入日志。
- [ ] D3. 从 HTTP 准备到后台认领、Work 恢复、回放、结果和 commit 逐段接入；实际记录排队和工作量，替换 backtest_profile.rs 同步私有实现，避免双计时/双计数。
- [ ] D4. 在 Runtime 基础设施层拆 Source::read：元数据/schema、records、checkpoint 解码、组件 restore、prefix compare、最终源比较；记录序号与原已有数量，禁止为了日志再读/编码一遍源。pure native_read 内不隐式引入时钟。
- [ ] D5. 覆盖 publish 后 from_proof、writer wait/hold、finalize 三次 proof、SQL 事务/提交、terminal 清理、终态 GET read_context/read_verified/序列化/响应。释放/错误路径必须关联原任务，不能提前释放原有安全 guard。
- [ ] D6. 锁事件关联对象设备/inode、原操作、持锁 scope/Run、争用 command、wait/hold/errno。用受控共享/独占竞争测试验证准确归属；找不到持锁者要输出 unknown，不按时间猜一个身份。诊断表只读既有生命周期，不替代 OS 锁或权限判定。
- [ ] D7. 运行直接影响的库回归、OpenAPI/响应场景与普通 Web 入口场景，独立审查事实归属、drop 顺序、异步传播和错误处理。Source guards 不能整库豁免。

**验收：** 一个 Run 可以从请求追到发布、SQL、清理和终态响应；取消准备可以从 command 追到具体锁争用，未结束路径明确截断。旧同步线程栈不再参与异步归因。

## E. 统一报告与当前回测实战

**文件**
- 扩展 scripts/backtest_benchmark.py 的 v1 事件解析、因果关联、并发区间与比较输出。
- 更新 scripts/native_web_e2e.py：独立诊断运行选择、固定原拓扑生命周期、单次采集与预算截止。
- 新增 packages/frontend/e2e/backtest-diagnostics.spec.ts，提取/复用 backtest.spec.ts 的普通 UI 操作辅助代码，保留原 300/120 秒断言。独立诊断最多 20 分钟，不将它计为原功能测试通过。
- 更新 docs/engineering/backtest-benchmarks.md 的长期使用说明；实战结果位于 test-results/。

- [ ] E1. 先用受控小场景验证整条关联、并发区间、writer 等待、锁争用、强杀缺 end、丢日志和敏感字段；有采集缺口时修采集，不假定业务慢已定位。
- [ ] E2. 串行运行固定 740-bar 当前场景，保留构建/数据身份、首次缓存状态与全部原始日志。明确编译/初始化不属于运行耗时，记录同机并发负载。
- [ ] E3. 实现设计中的单次独立诊断：20 分钟整体观测预算、隔离命名空间、当前真实工件，通过普通 Web 明确创建一次 740-bar 诊断 Run，保持该 run_id 不变。记录原300/120性能预算是否越界而不修改原测试。观察全发布/SQL/清理，期间用普通UI发起一次争用准备命令；终态GET只触发一次，客户端超时照旧，停止重复请求但保留原handler服务端结束/失败证据。协助代码只协调观测，不写业务数据库、不伪造proof；完整条件、停止与清理严格按设计执行。
- [ ] E4. 报告完整与截断两类数据，分别列明实测、静态计数、推断及未知。输出按 Run 的阶段树、关键路径、模块调用次数/工作量/成本、锁关联、发布前后边界、终态响应和未归因差额。
- [ ] E5. 对模块基准做同条件 Off/Detail 观测开销对照；首轮完整正式链路仅做一次，任何重复完整取证先依据数据与预算确认必要性，不把重复故障当作采样。连续异常、资源压力或三次失败触发既有停止/商议规则。
- [ ] E6. 对照设计五个实战问题逐项作答；完整尾段和一次终态handler的实测是硬交付；客户端超时是可报告结果，不是服务端链路测量缺失的替代。未完成时保留“未测得”，首轮实战验收保持未完成，停止并与负责人商议，不能自行延长20分钟或重跑。

**首个业务结果：** 给出当前慢问题的成本构成和直接证据，区分单次操作慢、重复验证、等待/锁、请求响应和观测本身。原先24/41/11次静态假设必须用本轮真实调用验证或明确仍被截断，不能简单乘以基准耗时作结论。

## F. 独立审查与交付

- [ ] 独立审查者按 Constitution/架构重新推导无第二事实 Authority，检查 pure Kernel 依赖、原结果一致、日志丢失/错误、身份关联、锁与 guard 生命周期。
- [ ] 核对覆盖矩阵、逐库 BENCHMARK.md 与实际完整基线；核对新 crate 自身开销基准和运行说明。
- [ ] 核对原始实战日志、构建/输入、完整/截断状态及清理收据，确认没有把“日志已落盘”当成“正式回测完成”。
- [ ] 交付可重复命令和报告链接；未完成项具体列出，原 Web 未通过则产品验收保持未完成。
- [ ] 仅在证据支持时提出后续性能修复方案，等待新的授权；本计划不自动授权优化、放宽超时、全仓日志替换、提交合并或推送。

## 推荐执行顺序与里程碑

A → B（先恢复热点组，再其余实际模块）→ C → D → E → F。先建立逐库基线，再建立最小日志库并统一接入真实链路，最终在当前回测上实战。

本次方案的完成物：实际使用模块的 benches 与 BENCHMARK.md、一个最小统一观测 crate、当前回测的完整/明确截断归因报告、功能不变与观测开销证据、独立审查。不会用“新建了日志库”代替实战结果，也不承诺未优化的回测已经满足 300/120 秒。
