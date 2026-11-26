# onlyalpha-indicators：金融指标

## 目的与职责

在通用算子之上表达稳定金融含义，提供均线、波动率、动量、成交量及价格区间指标。

所有内置指标均通过 [`compose`] 模块仅由 [`onlyalpha-operators`](../operators/README.md) 的已认证双内核算子组合构建，不维护手写滚动状态；每个指标天然同时支持批量 `evaluate_vector` 与逐事件 `event_stream`（含 `capture_state` / `restore_state`），并共享 `DECIMAL28_HALF_EVEN_Q12_V1` 数值契约。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

纯 Rust 库，无 Python 接口；不负责因子假设、策略买卖、行情获取、图调度或运行准入。

直接依赖的仓内库：[`onlyalpha-operators`](../operators/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

`compose` 提供纯算子组合 DAG 及双形态执行接口：`ComposedIndicator`（`evaluate_vector`、`event_stream`、`input_count`、`output_count`、`minimum_observations`）、`ComposedStream`（`step`、`capture_state`、`restore_state`）、`IndicatorState`。

`builtin` 提供全部内置金融指标组合构造器：`sma`、`wma`、`roc`、`ema`、`rolling_volatility`、`zscore`、`bollinger`、`macd`（含 `MACDCross`）、`rsi`（含 `RSIZone`）、`atr`、`obv`、`vwap`、`stochastic`，以及按 UTC 交易日重置的会话指标 `UtcSessionVWAP`（含 `UtcSessionVwapState`，内部同样仅由已认证算子组合）。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod builtin;
pub mod compose;

pub use builtin::{
    MACDCross, RSIZone, UtcSessionVWAP, UtcSessionVwapState, atr, bollinger, ema, macd, obv, roc,
    rolling_volatility, rsi, sma, stochastic, vwap, wma, zscore,
};
pub use compose::{ComposedIndicator, ComposedStream, IndicatorState, Result};
pub use onlyalpha_operators::algebra::{Columns, Decimal, Error as IndicatorError};
```

## 状态与生命周期

`ComposedIndicator` 无可变状态，可反复执行向量批处理或派生独立的 `ComposedStream`。`ComposedStream` 与 `UtcSessionVWAP` 的状态仅来源于内部已认证算子流的检查点（加上 `UtcSessionVWAP` 的单调时间戳边界），非法输入或损坏检查点在提交前拒绝且不修改现有实例。无持久化服务，数值与预热语义以所组合的算子契约为准。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择构造器与执行形态；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
python3 scripts/dev_verification.py run -- python scripts/rust_kernel_check.py --package onlyalpha-indicators
cargo doc -p onlyalpha-indicators --no-deps
```

`tests/certification.rs` 为全部内置指标与 `UtcSessionVWAP` 独立推导 golden，并逐点认证 Vector == Event 等价、多前缀因果、warmup/null 边界、参数拒绝与检查点恢复。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
