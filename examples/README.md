# OnlyAlpha Cluster Configurations

`examples/` 只保存按 Cluster 分类的配置和说明。统一产品入口：

```bash
uv run onlyalpha run --config examples/clusters/macd/config.yaml
```

重复使用 `--config` 可在一个 Engine 中加载多个 Cluster。示例 Strategy/Factor 位于
`plugins/onlyalpha_examples`，运行产物统一写入 `user_data`。
