# ADR 0150: 工程目录与可编程因子、策略

- 状态：Accepted
- 日期：2026-11-04
- 决策人：仓库负责人
- Constitution Impact: NO

## 工程目录和 Agent

`packages/` 只保留 `backend`、`frontend` 两个运行工程。取消独立 `packages/agent` 工程及其发行线，也取消单独的部署、服务 API、存储和 LangGraph 选型要求。Agent 是通过 OnlyAlpha 正式 API 工作的研究客户端。人仍通过正式 Web 界面执行产品操作和授权。后端负责权限、预算、准入、执行、正式证据和恢复，Agent 不拥有实盘权限。已经绑定的事实、工件和未确认操作按各自契约保存及处理。

`crates/` 存放 Rust 库。交易内核保持与具体市场无关，并按功能测试。内置算子和指标分别放入 `crates/operators` 和 `crates/indicators`，采用纯 Rust，实现不提供 Python 接口。市场交易规则、券商接口实现和数据源接口实现放在 `plugs/`，优先采用 Rust，Python 是第二选择。命名沿用 ADR 0149 的三个类别。

Rust 交易内核库统一版本，后端和前端各自发行，独立交付的插件按各自发行包管理版本。

## 因子与策略

Rust 实现因子和策略的正式契约，两者共用行情事件接口，并提供受限的 Python 编写接口。因子处理 Bar 等行情输入并输出因子值。策略可使用因子值，读取只读仓位，提交买卖意图。Rust 可用 trait 表达共享接口。策略不必实现因子值输出。

事件顺序、时间及其他影响结果的输入必须显式记录或绑定。策略编写接口的买卖操作形成正式订单意图。权限、风险、订单身份、交易场所接入、仓位更新及恢复由各自的 OnlyAlpha 模块负责。相同策略版本用于回测、模拟和实盘时，其含义保持一致。Python 编写接口通过受限、隔离的执行边界使用。具体接口、隔离实现和准入流程另按相关公开契约设计。

私有因子和策略继续采用 PostgreSQL 中的可编辑草稿和不可变版本。冻结绑定实际执行的实现、参数、接口版本及所需精确工件。变更创建新版本。既有运行及历史证据保持原绑定。

NautilusTrader 的行情事件与策略权限分层提供了参考。OnlyAlpha 的因子输出、订单意图、准入和交易权限继续由 OnlyAlpha 的正式契约定义。[Actors](https://nautilustrader.io/docs/latest/concepts/actors/) · [Strategy trait](https://nautilustrader.io/docs/rust-api-latest/nautilus_trading/strategy/trait.Strategy.html)

## 生效范围

本决定替代 ADR 0146。调整 ADR 0149 中算子和指标的目录、发行包及 Python 接口安排，保留其市场规则、券商、数据源分类及其他独立决定。调整 ADR 0129、0131、0132 和 0141 对私有资产实现语言及策略仅为结构化定义的限制，保留数据库草稿、不可变版本、正式准入和历史绑定。ADR 0142 的后端、前端及库发行规则按本文执行。

本决定描述目标架构。目录迁移、API 与执行实现及正式验收由后续工程任务完成。
