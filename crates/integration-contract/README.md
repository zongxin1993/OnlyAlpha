# onlyalpha-integration-contract：集成公开契约

## 目的与职责

定义与服务商无关的集成类型、配置字段、探测声明、插件注册投影及行情数据源接口。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有运行准入、凭据存储或具体服务商协议；声明与指纹不等于已安装、已授权或可用。

直接依赖的仓内库：[`onlyalpha-metadata-json`](../metadata-json/README.md)、[`onlyalpha-domain`](../domain/README.md)、[`onlyalpha-market-data-construction`](../market-data-construction/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

Descriptor::from_json 接收原始 JSON 和工作预算，返回经过校验的类型、配置与指纹；IntegrationTypeId / Category / Field / ValueKind / Probe 描述声明。authoring::Registration / PluginProjection 校验插件投影；source::Factory / Resource / Stream / Recorder / Clock 定义显式数据源端口、输入输出和预算。

[`HistoricalDays`](src/source.rs) 接受证券 ID、日线语义、范围与可选复权基准。Host 按 `inputs` 枚举的公开 Query 读取并封存来源响应，`replay` 输出冻结日历、证券单位、因子证据和闭合 Bar。只读证券资料不授予交易或实时能力。`Factory::create_with_credentials` 接收 Host 已按完整 Slot 与代际解密的临时借用。传统分钟资源仍提供自己的固定日历。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod authoring;
pub mod source;
```

库根直接声明：`Error`、`IntegrationTypeId`、`Category`、`valid_field_id`、`ValueKind`、`Field`、`Probe`、`Descriptor`。

## 状态与生命周期

库本身不持久化；source 资源生命周期由实现与调用方管理。Error 与 SourceError 区分无效、不可用等情况；缺少证据或预算耗尽不能转成历史数据确定不匹配。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-integration-contract
cargo doc -p onlyalpha-integration-contract --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

历史输入 `HistoricalObservation` 随规范 Query 和原始响应提供原 producer attempt 开始时间、实际接收时间。缓存传递同一组原时间，供历史插件在封存重放中校验收盘。
