# 接口与架构唯一性

## 唯一入口原则

同一业务能力只能有一个正式入口。外部 Product 链路是
`OpenAPI-derived client → HTTPS/JSON → Product HTTP Adapter → Product Command/Query → Stateful Kernel`；
`OnlyEngine(OnlyEngineConfig) → add_cluster → validate/initialize/start/run/stop` 只描述 Kernel 内部执行组合，不是外部 Product contract。

## 禁止兼容层原则

当前项目不保留旧版本兼容层，不增加 deprecated wrapper、compatibility adapter、旧参数别名或双格式解析。

## 重构完成定义

重构只有在旧接口、旧实现、旧测试、旧配置、旧导出和现行文档全部删除或迁移后才完成。

## 配置唯一字段原则

同一语义只能存在一个配置字段。DataSource/Broker 使用 `plugin`；`runtime.type` 只表达 Runtime 类型。

## 生命周期唯一原则

同一组件只能有一套生命周期。Engine 实例运行一次，终止后不可重新初始化或运行。

## 工厂唯一原则

相同组件类型只能通过正式 Factory/Registry 路径创建，测试不得建立平行装配链。

## 输出唯一原则

产品输出只能通过 `OnlyUserDataLayout` 和 `OnlyEngineResultExporter` 写入
`<user_data_root>/runs/<engine_id>/<run_id>/`。

## Quantitative asset boundary

ADR 0110 replaces the old three-repository example placement. Public reusable L1 Operators and L2 Indicators are official
plugins; production L3 Factors and L4 Strategies are private assets. The main repository contains only the two local
non-production L3/L4 reference libraries named by ADR 0110. Dependency direction is
`L4 examples → L3 examples → public L1/L2 plugins → OnlyAlpha contracts`; Core and public plugins never depend on examples.
