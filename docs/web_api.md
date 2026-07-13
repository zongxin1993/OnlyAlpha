# Web API 设计

## 1. Application Service

Web 仅调用：

```text
OnlyEngineService
OnlyClusterService
OnlyBacktestService
OnlyResearchService
OnlyQueryService
OnlyCommand
OnlyCommandResult
```

## 2. API 草案

```text
GET    /engine/status
POST   /engine/start
POST   /engine/stop

GET    /clusters
POST   /clusters/load
POST   /clusters/{id}/start
POST   /clusters/{id}/stop
DELETE /clusters/{id}

POST   /backtests
GET    /backtests/{id}
POST   /backtests/{id}/stop
GET    /backtests/{id}/result

POST   /research/factors/run
GET    /research/tasks/{id}
GET    /research/results/{id}

GET    /accounts
GET    /positions
GET    /orders
GET    /trades
```

## 3. 推送

实时状态可使用：

- WebSocket；
- SSE。

推送对象必须是稳定 DTO，不直接暴露内部对象。

## 4. 禁止

Web 层不得：

- 直接访问数据库；
- 直接调用 Gateway；
- 直接控制线程；
- 直接修改 Cluster；
- 包含交易策略；
- 包含撮合。
