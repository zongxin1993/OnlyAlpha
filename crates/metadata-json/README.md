# onlyalpha-metadata-json：元数据 JSON 身份

## 目的与职责

提供产品元数据 JSON 的规范化、字段读取和指纹计算，保留既有 Python binary64 字符串策略。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不负责业务 schema、运行授权或数据库；规范化不能改变已绑定历史语义，也不能把解析资源不足当作数据损坏。

没有直接依赖的仓内库。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

object_fields 接收 JSON 对象，返回字段到 RawValue 的映射并拒绝重复键；canonical_json / integral_float_json / python_json 接收字符串和 max_work，输出对应规范 JSON；fingerprint 输出规范身份摘要。Error::Invalid / Unavailable 区分确定非法与无法完成。

python_json 仅用于原来采用普通 Python `json.dumps(sort_keys=True,separators=(",",":"),ensure_ascii=False)` 的证据边界，浮点保留数字类型、整值浮点 `.0` 和负零；不改变 canonical_json 的浮点字符串策略或 integral_float_json 的整值归整数策略。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

库根直接声明：`Error`、`object_fields`、`canonical_json`、`integral_float_json`、`python_json`、`fingerprint`。

## 状态与生命周期

无可变持久状态，每次调用显式提供工作预算。预算耗尽返回不可用；上层应保留原始输入和预算失败语义，不得据此宣称历史不存在或已不匹配。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-metadata-json
cargo doc -p onlyalpha-metadata-json --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
