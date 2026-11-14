# onlyalpha-predicates：确定性谓词

## 目的与职责

定义布尔组合、整数与十进制比较，以及布尔和字符串相等性判断，统一类型版本和缺值语义。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不执行策略，不授予运行准入或正式写入权限，不处理网络或持久化。

没有直接依赖的仓内库。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

predicate::Predicate、integer_predicate::IntegerPredicate、decimal_predicate::DecimalPredicate 通过 resolve 解析 type_id 与版本，再由 evaluate 返回 Option<bool>。boolean_equality / string_equality 提供相等及字面量谓词；Operand 类型校验输入表示，PredicateError 报告非法类型、版本或输入。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod boolean_equality;
pub mod decimal_predicate;
pub mod integer_predicate;
pub mod predicate;
pub mod string_equality;
```

## 状态与生命周期

无持久状态。缺值通过 Option 表达而不自动当成 false；比较使用规范数值和明确输入，重复调用的结果由相同版本与输入决定。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-predicates
cargo doc -p onlyalpha-predicates --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
