# 产品接口与命令行

人通过 Web 使用版本化 Product API，Agent 与自动化客户端通过正式 HTTPS API 操作。HTTP 接入服务退役期间，依赖后端的流程暂停。产品没有可替代这些流程的本地 CLI，客户端不得绕过身份、风控和持久化边界直接调用交易内核或访问数据库。

正式请求与响应见 [OpenAPI v2](../contracts/product-api/v2/openapi.json)。Rust 库调用入口见 [Runtime](../crates/runtime/README.md)。库接口供宿主装配，开发和验证入口见[工程指南](../AGENTS.md)。
