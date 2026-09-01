# OnlyAlpha Process Entrypoints

OnlyAlpha 不提供 Product CLI。Human 通过 Web 使用版本化 Product API；Agent、自动化和其他 machine consumer 直接消费同一
OpenAPI/HTTPS contract。HTTP 不可用时不得 fallback 到本地 Engine、Runtime 或数据库。

保留的命令行入口属于进程或 provider-local infrastructure tooling：

```text
onlyalpha-api              Product HTTP adapter process
onlyalpha-research-worker  fenced Research execution worker
onlyalpha-miniqmt          provider-local environment diagnostics
onlyalpha-tushare          provider-local environment diagnostics
```

`onlyalpha-api` 默认绑定本机地址，只验证 schema compatibility，不自动执行 migration。PostgreSQL DSN 通过 infrastructure
environment 注入，不属于 Trading semantic configuration。

以下入口不是支持的产品面，也没有兼容 alias：

```text
onlyalpha ...
onlyalpha-client ...
runtime YAML/JSON launch
direct Engine/Runtime construction
```

Scenario parser、runner 与 assertions 是 `tests`/CI 使用的工程验证能力，不暴露为 Product CLI 或 Product API。Research operational
diagnostic service 保留为唯一 application semantics；数据库运维通过受控 infrastructure tooling 使用，不通过 root CLI 建立第二入口。
