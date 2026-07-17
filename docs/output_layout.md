# Engine Output Layout

`OnlyUserDataLayout` 是路径生成的唯一入口，`OnlyEngineResultExporter` 是 Engine 产品结果写入者：

```text
runs/<engine_id>/<run_id>/
├── manifest.json
├── engine/{config,summary}.json
├── clusters/<cluster_id>/{source_config,normalized_config,fingerprint,summary,report}
├── runtimes/
├── shared/
└── logs/
```

每个 run_id 唯一；Manifest 记录所有 Cluster、Runtime 与配置指纹。Cluster 是结果的一级业务隔离边界。
