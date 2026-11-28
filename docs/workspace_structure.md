# OnlyAlpha 工作区结构

| 目录 | 职责 |
|---|---|
| [crates](../crates/) | Rust 基础库。`runtime` 装配研究、回测、模拟和实盘任务，`broker-virtual` 提供模拟场所，其他库各自负责所属交易语义。 |
| [packages/frontend](../packages/frontend/) | 正式 Web 客户端。原 Backend 已退役，依赖服务的产品流程暂停。 |
| [plugs](../plugs/) | 市场规则、券商和数据源插件。 |
| [contracts](../contracts/) | 版本化产品接口与跨进程协议。 |
| [test-data](../test-data/) | 多个组件使用的参考数据。各库专用测试与基准位于库内。 |
| [deploy](../deploy/) | PostgreSQL、ClickHouse 的开发环境配置。 |
| [scripts](../scripts/) | 仓库工程工具，库单元测试入口为 [unit_tests.py](../scripts/unit_tests.py)。 |

产品权限、准入、数据库访问及子进程生命周期属于产品宿主。Rust 库通过公开端口接收装配，仓内依赖仅指向其他基础库。Rust 基础库统一版本，前端和独立交付的插件按各自元数据发行。详见[仓库与产品架构](repository-product-architecture.md)和[发行规则](release-versioning.md)。
