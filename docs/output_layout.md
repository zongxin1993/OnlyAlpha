# Engine Output Layout

`OnlyUserDataLayout` 是路径生成的唯一入口，`OnlyEngineResultExporter` 是 Engine 产品结果写入者：

```text
runs/<engine_id>/<run_id>/
├── manifest.json
├── artifact_manifest.json
├── {summary,diagnostics,data_manifest}.json
├── {orders,executions,trades,positions,accounts,equity,signals}.parquet
├── report.md
├── engine/{config,summary}.json
├── clusters/<cluster_id>/{source_config,normalized_config,fingerprint,summary,report}
├── runtimes/
├── shared/
└── logs/
```

每个 run_id 唯一；Manifest 记录所有 Cluster、Runtime 与配置指纹。Cluster 是结果的一级业务隔离边界。
当一个 Engine Run 包含多个 Backtest Runtime 时，各 Runtime 的标准 Artifact 位于 `runtimes/<runtime_id>/artifacts/`，避免账户和事实重复加总。文件 Schema、行数、SHA-256 与内容指纹记录在对应 `artifact_manifest.json`。
