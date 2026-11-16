# onlyalpha-backtest：回测执行

## 目的与职责

用冻结行情输入驱动有限回放，复用交易组件并产生进度、轨迹、终态和回测结果。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不负责产品任务准入、权限、队列或 LIVE 授权；不创建第二套交易语义。

直接依赖的仓内库：[`onlyalpha-runtime`](../runtime/README.md)、[`onlyalpha-calculation-bridge`](../calculation-bridge/README.md)、[`onlyalpha-clock`](../clock/README.md)、[`onlyalpha-domain`](../domain/README.md)、[`onlyalpha-execution`](../execution/README.md)、[`onlyalpha-strategy`](../strategy/README.md)、[`onlyalpha-market-data`](../market-data/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`BacktestRun`、`MemoryRunSpec`、`CompletedBacktest`](src/memory.rs)提供有限内存执行入口。`new` 核对行情、程序、配置、样本窗口和输入身份，只接受原 Strategy owner 已核对的 genesis Executor；`step` 先 OPEN 执行上一根信号，再处理闭合 BAR，共用原 `NativeReplay` 的准入、费用、成交与结算。`cancel` 后和输入未耗尽时不能 `finish`。成功收尾包含实际事件 drain、信号 owner 最终核对、Account／Ledger 对账、完整经济结果、逐 sample 收盘曲线及同数量买入持有费用报价；字段私有的 `CompletedBacktest` 保留完整 `ExecutionBinding`：实际配置、时间边界、日历、resolver 绑定与初始信号状态；`RunBinding::with_execution_fingerprint` 声明的摘要必须与实际内容完全相同。它不是 PG 发布回执。Backend 仍须证明原冻结绑定、全部结果计划、实际任务退出和发布权限。新路径不创建文件或逐 Bar 全组件 checkpoint，过程丢失后从冻结输入重算。`retained_counts`、`retained_payload_bytes` 只供技术观测，后者不等于分配器内存或 RSS。

`NextOpenPolicy::analytical_entry_quote` 必须由原市场／费用 owner 返回同数量的分析报价，结果标明 `ANALYTICAL_ESTIMATE`，不证明真实场所接受。当前内存驱动复用现有现金、单商品、下一 OPEN 整笔成交模型；永续原始凭据不能通过普通 Session 输入绕过。旧文件运行入口尚由现有消费者使用，不能将其描述为已经退役。

Inputs / Source / MarketInput 校验输入及其身份；RunSpec、Participants、NextOpenPolicy 配置运行；RunLoop::create / open / step / run 执行或恢复；TerminalSnapshot::read 读取校验后的终态。Trading 适配 Strategy 节点，validate_configuration 只验证配置。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use inputs::{Inputs, MarketInput, OpeningInput, Source};
pub use next_open::NextOpenPolicy;
pub use onlyalpha_execution::Error;
pub use run::{Candidate, Participants, RunLoop, RunSpec, StepAndDeliverError};
pub use terminal::TerminalSnapshot;
pub use trading::Trading;
```

库根直接声明：`validate_configuration`。

## 状态与生命周期

RunLoop 管理输入关闭、取消、暂停、恢复和终止；Runtime 保存执行事实与回放绑定。读取终态仍校验配置、工件及精确切片，不能用缺证推断成功。

终态的单次原生验证在 `native_read` 的私有 `OriginalExecution` 中持有一个准入复算上下文。
它只消费本次 `VerifiedReplaySnapshot` 的原始投影；每次拒绝检查重新构造原 cursor 的完整 checkpoint，
完整内容不同即重新冷恢复，实际原始输入推进 cursor 时释放旧上下文。新 Run、新验证或进程重启均从空上下文开始。
复用的是已恢复的数据，不是历史完整性、当前来源或拒绝结论；缺失/错误的原始记录仍报错。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-backtest
cargo doc -p onlyalpha-backtest --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

真实保留输入的技术性能对照位于 [`tests/admission_preview_profile.rs`](tests/admission_preview_profile.rs)，默认忽略。
在固定开发容器设置 `OA_PROFILE_RUNTIME_ROOT` 为完整 runtime 目录、`OA_PROFILE_IDENTITY` 为该库 meta.payload
身份 JSON，再运行 `cargo test -p onlyalpha-backtest --release --test admission_preview_profile -- --ignored --nocapture`。
它在终态 checkpoint 上对更新身份的原始 ADMIT 做三轮冷恢复/复用对照，每轮 67 个输入逐项核对结果；
仅量化纯复算开销和观察进程 RSS，不将技术输入解释为可提交意图，也不代替正式 Web 验收。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
