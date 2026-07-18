# Plugin Configuration

公共配置字段使用 `plugin`：

```yaml
data_sources:
  - source_id: historical-main
    plugin: vendor-data
    enabled: true
    data_version: snapshot-v1
    coverage: {instrument_ids: [TEST.XSHG]}
    extensions: {vendor_specific: value}

brokers:
  - gateway_id: broker-main
    plugin: vendor-broker
    enabled: true
    extensions: {environment: paper}
```

核心只解析公共字段并原样传递 extensions。DataSource/Broker 的 `type` 是未知字段并立即失败；唯一字段是 `plugin`。
内部只保留 `plugin_id`，不得通过任意 `class_path` 创建 DataSource/Broker。`runtime.type` 仍只表示 Runtime 类型。
