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

P9.K.8 已 hard seal 历史 `onlyalpha run/snapshot`；根 CLI 不再提供任何 Product mutation，也没有 compatibility alias、HTTP
forwarding 或本地 Engine fallback。内部 Engine/Runtime composition 继续由 Worker、Scenario、测试和明确 internal tooling 使用具体实现
模块，不属于外部 Product CLI。

工作区职责见 `workspace_structure.md`：CLI 属于 OnlyAlpha 核心，官方 Cluster 配置属于 `OnlyAlpha-plugins`，官方示例只在
`OnlyAlpha-examples` 组织和调用这些配置。

Research HTTP server 使用独立 operator/infrastructure console entry：

```bash
ONLYALPHA_POSTGRES_DSN='postgresql://...' onlyalpha-api --user-data-root /absolute/user-data
```

该入口启动本地 full Research API，并只做 PostgreSQL schema compatibility check；Artifact GET routes 与 Product command/query routes
由同一 Product API 提供。它默认绑定 `127.0.0.1`，不启动 Scheduler/Worker，也不自动执行 migration。DSN 只能通过环境变量注入，
不通过命令行明文参数传递。

K6 暂存的 `onlyalpha-artifact-api` compatibility debt 已由 K8 移除。`onlyalpha scenario validate/run` 属于 `TEST / SCENARIO`；
`onlyalpha operations status/run`、provider doctor 与 Research Worker 属于 `OPERATOR / INFRASTRUCTURE`。它们不是 Product API client，
也不得被描述为 Product Control Plane。
