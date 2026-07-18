# Cluster 运行配置

一个 YAML/JSON 文档只能定义一个 Cluster，顶层使用 `cluster`，禁止 `clusters[]`。正式类型为
`OnlyClusterRunConfig`，公共区段为：

```text
schema_version, cluster, runtime, reference_data, universes,
data_sources, accounts, brokers, strategy, factors, output
```

`cluster.runtime_type` 选择 Runtime；Strategy/Factor 使用 `python.module:OnlyClass` 导入描述。通用 Parser 只解析
公共字段并保留 `extensions`，组件专用参数由各自 Factory 解析。

文件入口只是适配层；核心入口是 `engine.add_cluster(config)`，因此 Web/Application 后续可以从 Mapping 创建强类型配置。
Engine 通过 `OnlyRuntimePlanner` 将配置转换为内部 `OnlyRuntimeAssemblyPlan`；不存在第二套产品配置文档。
DataSource 和 Broker 必须使用 `plugin`，`type` 不作为别名；输出配置只允许 `formats` 和 `overwrite`。
