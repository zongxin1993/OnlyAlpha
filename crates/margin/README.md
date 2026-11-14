# onlyalpha-margin：保证金与抵押状态

## 目的与职责

按显式指令维护市场无关的保证金和抵押状态，生成关联组件可以应用的 Effect。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不内置市场费率、券商政策或外部副作用；不负责真实账户资金操作或 Runtime 准入。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

配置显式选择 `entry_profile=LINEAR_LONG_NETTING_CROSS_OPEN` 时，仅支持 BACKTEST、schema2 的正向线性 LONG/NETTING/CROSS 开仓。OCCUPY 在保留数量、原订单、版本、来源和预留上限检查后，以同一 owner、cluster、revision、instrument、mode、isolation、side 的累计入场维护额不超过累计初始占用为证明；request/order 不拆分 CROSS 池。该 profile 的 `release_quote` 和 RELEASE_OCCUPIED 明确拒绝未实现的平仓。未选 profile 的 schema1/schema2 沿用原单笔增量约束和关闭路径。

BACKTEST 的线性全仓开仓使用 schema 2 MARK_MAINTENANCE，输入绑定原 reservation、全部未平仓量、原 Mark 来源、前状态和要求金额。apply 返回类型化抵押效果，restore 重放原命令验证前置版本与投影。

Manager::new 接收配置和容量；apply 接收规范指令并返回 Effect，Effect::replay_input / record 暴露重放与结果记录。snapshot / snapshots 查询状态，release_quote 计算指定数量的释放结果。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use manager::{Effect, Manager};
pub use model::{Error, digest};
```

## 状态与生命周期

新 profile 的 reservation schema2 独立保存 `entry_maintenance`，仅从有序 OCCUPY 历史累计，Mark 不改该值。检查点重建必须重放原指令再比较全部状态和结果，修改状态后重算摘要不能替代原历史。当前 Mark 维护额可以高于入场占用，不用于阻断已准入的真实成交；原正值 RESERVE、守恒、幂等和预算保护继续适用。

Manager 保存内存状态，checkpoint / restore 通过期望摘要核对候选恢复。调用方持久化并协调跨组件提交，拒绝无效指令或错误关联。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

现有示例：[`margin_reference`](examples/margin_reference.rs)；可在仓库根目录用 `cargo run -p onlyalpha-margin --example <示例名>` 运行。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-margin
cargo doc -p onlyalpha-margin --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

Manager::new 的显式 BACKTEST 配置可含正整数 observation_capacity，不能超过传入的生命周期容量。该格式生成 schema 2 检查点，observation_capacity_reached 读取历史计算额度。尖峰时 MARK_MAINTENANCE 不占用预留的成交、释放槽；额度用尽后新风险被拒绝，首次无法更新已开仓维护额使用 MARK_UNAVAILABLE 保留原始证据。一次连续缺证仅记录一个起点。带 model_notional_limit 的生产配置使用 covers_open_notional 按真实已开仓量核对最新单位合约名义，有限模型以外的欠证记录为 MARK_OUTSIDE_MODEL。新事实回到已知档、还有观测额度时才能确认新的完整维护额；反复退出并恢复模型的次数受同一额度约束。未选择此配置的原现金历史使用 schema 1。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
