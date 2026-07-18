# OnlyAlpha CLI

唯一产品入口是 `onlyalpha run`：

```bash
uv run onlyalpha run \
  --config ../OnlyAlpha-plugins/clusters/<cluster-a>/config.yaml \
  --config ../OnlyAlpha-plugins/clusters/<cluster-b>/config.yaml
```

`--config` 可重复；`--config-dir` 递归收集 YAML/JSON，`--config-glob` 处理 Glob。显式路径保持输入顺序，目录和
Glob 结果稳定排序，最后按绝对路径去重。至少必须得到一个配置。

`--user-data` 覆盖 `ONLYALPHA_USER_DATA`，后者覆盖 `cwd/user_data`。`--engine-id` 默认 `onlyalpha`；
`--fail-fast/--no-fail-fast` 控制 Cluster 失败策略。`--dry-run` 完成 Schema、动态类、引用、资源冲突、Runtime
分组和输出计划校验，不运行历史回放，也不创建正式 run 目录。

CLI 只构造 `OnlyEngine`、逐个调用 `add_cluster_from_file()`，最后调用 `validate()` 或 `run()`；它不创建
Runtime、DataSource、Broker、Strategy、Factor 或 Indicator。

工作区职责见 `workspace_structure.md`：CLI 属于 OnlyAlpha 核心，官方 Cluster 配置属于 `OnlyAlpha-plugins`，官方示例只在
`OnlyAlpha-examples` 组织和调用这些配置。
