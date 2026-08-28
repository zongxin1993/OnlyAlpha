# OnlyAlpha CLI

正式 Product CLI 是 `onlyalpha-client`，其所有 Product command/query 都只经 canonical OpenAPI → HTTPS/JSON → Product Control
Plane：

```bash
uv run onlyalpha-client research create specification.json \
  --idempotency-key 00000000-0000-4000-8000-000000000001
uv run onlyalpha-client research get <run-id>
uv run onlyalpha-client research list --limit 50
uv run onlyalpha-client research cancel <run-id> --idempotency-key <command-id>
```

Client 不隐式生成 command identity，也不对 mutation 做隐式 retry。响应丢失后，调用方必须显式复用同一个 idempotency key；
HTTP 不可用时返回 transport failure，绝不 fallback 到本地 Engine/Runtime。

历史 `onlyalpha run/snapshot` 是显式 `LEGACY_K8_TARGET`，不是正式外部 Product Control Plane。它们在 P9.K.8 hard seal 前只为
迁移期保留，不新增等价 HTTP endpoint，也不再作为正常 Product UX 文档：

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

默认成功输出是单行简洁 JSON，包含旧 Engine 字段及 bar/signal/order/execution/trade 数量、基础绩效、三层结果指纹和报告路径，不输出完整事实列表。`--console-report` 在 JSON 前增加人类可读摘要；机器调用不要启用该选项。

该 legacy CLI 只构造 `OnlyEngine`、逐个调用 `add_cluster_from_file()`，最后调用 `validate()` 或 `run()`；它不创建
Runtime、DataSource、Broker、Strategy、Factor 或 Indicator。

当前 SIM streaming CLI 在 Application 层统一处理 Windows Ctrl+C/CTRL_BREAK 和 POSIX SIGINT/SIGTERM。主线程以
0.25 秒有限预算调用 `OnlyEngine.wait()`，首次中断经唯一 `OnlyEngine.stop()` 关闭整个 Engine，SIGINT/控制台中断返回
130，SIGTERM 返回 143；关闭期间第二次中断执行进程级强制退出，不会重入 Runtime 或 Cluster stop。正常退出会输出
简短 shutdown 信息和 `runtime_shutdown` 诊断（Runtime/streaming 状态、订阅、worker、publisher）。

优雅关闭保证已提交 durable transaction 不被撤销，并有序释放当前资源。checkpoint-enabled SIM 可恢复 durable
authorities；未提交的 transport queue、partial live Bar、线程和 socket 从不 durable，强制退出后按 continuity evidence
向前修复。

工作区职责见 `workspace_structure.md`：CLI 属于 OnlyAlpha 核心，官方 Cluster 配置属于 `OnlyAlpha-plugins`，官方示例只在
`OnlyAlpha-examples` 组织和调用这些配置。

Research HTTP server 使用独立 operator/infrastructure console entry：

```bash
ONLYALPHA_POSTGRES_DSN='postgresql://...' onlyalpha-api --user-data-root /absolute/user-data
onlyalpha-artifact-api --artifact-root /absolute/research-artifacts
```

前者启动本地 full Research API，并只做 PostgreSQL schema compatibility check；后者是无需 PostgreSQL 的 portable Artifact
GET API。二者默认绑定 `127.0.0.1`，都不启动 Scheduler/Worker，也不自动执行 migration。DSN 只能通过环境变量注入，不通过命令行
明文参数传递。

`onlyalpha-artifact-api` 是 K6 明确保留的 `READ_ONLY_COMPATIBILITY_SURFACE`，mutation capability 固定为 0，清理 owner 为
P9.K.8。`onlyalpha scenario validate/run` 属于 `TEST / SCENARIO`；`onlyalpha operations status/run`、provider doctor 与 Research Worker
属于 `OPERATOR / INFRASTRUCTURE`。它们不是 Product API client，也不得被描述为 Product Control Plane。
