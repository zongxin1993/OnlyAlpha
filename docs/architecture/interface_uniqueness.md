# 接口与架构唯一性

## 唯一入口原则

同一业务能力只能有一个正式入口。OnlyAlpha 产品运行唯一链路是
`OnlyEngine(OnlyEngineConfig) → add_cluster → validate/initialize/start/run/stop`。

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

## 三仓边界

- OnlyAlpha：核心库、CLI、领域模型、Engine/Runtime/Cluster 容器与通用基础设施。
- OnlyAlpha-plugins：可复用或面向产品的官方 Strategy、Factor、扩展与基础设施适配器。
- OnlyAlpha-examples：示例专用 Strategy/Factor、示例 Cluster 配置、教程与工作流，只消费公开接口。

依赖方向固定为 `OnlyAlpha-examples → OnlyAlpha-plugins → OnlyAlpha`，核心不得反向依赖。
