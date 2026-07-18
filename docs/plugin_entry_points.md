# Plugin Entry Points

OnlyAlpha 使用 Python distribution metadata 发现：

```toml
[project.entry-points."onlyalpha.data_sources"]
vendor-data = "vendor_package.data:factory"

[project.entry-points."onlyalpha.brokers"]
vendor-broker = "vendor_package.broker:factory"
```

组合根先注册内建 Factory，再按 group/name/value 稳定排序加载 Entry Point。`fail_fast=true` 首错失败；false 记录结构化
失败并继续。加载后统一执行 Descriptor、Plugin Type、API Version、Factory 方法和 plugin_id 冲突校验。
