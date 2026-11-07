# onlyalpha-indicators：金融指标

## 目的与职责

在通用算子之上表达稳定金融含义，提供均线、波动率、动量、成交量及价格区间指标。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

纯 Rust 库，无 Python 接口；不负责因子假设、策略买卖、行情获取、图调度或运行准入。

直接依赖的仓内库：[`onlyalpha-operators`](../operators/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

SMA / EMA / WMA、MACD、RSI、ATR、Bollinger、Stochastic、ROC、OBV、VWAP / UtcSessionVWAP、ZScore / RollingVolatility 提供增量指标及相应 Point 类型。SimpleMovingAverage::new / push 接收同一固定小数位价格系数，输出 value 与 ready；FinancialValue 等类型约束金融输入。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use atr::{ATR, ATRPoint};
pub use bollinger::{Bollinger, BollingerPoint};
pub use ema::EMA;
pub use fixed_window::{FinancialInputError, FinancialValue};
pub use macd::{MACD, MACDCross, MACDPoint};
pub use obv::OBV;
pub use roc::{ROC, RateOfChangeError};
pub use rolling_statistics::StatisticalError;
pub use rolling_volatility::RollingVolatility;
pub use rsi::{RSI, RSIPoint, RSIZone};
pub use sma::{FixedScaleAveragePoint, InvalidFixedScaleInput, SMA};
pub use stochastic::{Stochastic, StochasticPoint};
pub use vwap::{UtcSessionVWAP, VWAP};
pub use wma::WMA;
pub use zscore::ZScore;
```

库根直接声明：`SimpleMovingAverage`、`SimpleMovingAveragePoint`。

## 状态与生命周期

指标实例持有窗口或递推状态，按调用顺序更新；预热、无值及输入错误以各指标返回类型表达。无持久化服务，重建需调用方重放同样输入；金融含义和舍入以实现契约为准。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-indicators
cargo doc -p onlyalpha-indicators --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
