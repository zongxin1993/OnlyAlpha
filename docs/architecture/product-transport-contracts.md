# 产品传输契约

产品 HTTP API 的版本化接口见 [OpenAPI v2](../../contracts/product-api/v2/openapi.json)。字段、状态码和兼容性按[兼容策略](../../contracts/product-api/v2/compatibility-policy.json)核对。行情 WebSocket 使用独立的[消息 Schema](../../contracts/product-api/v2/market-data-stream.schema.json)。前端继续消费这两份协议。

原 Backend 的 HTTP、WebSocket 服务与契约导出程序已经退役。接入新的服务实现时，需同时核对实际路由、请求和响应、错误体、消息帧及其与已提交协议的一致性，并按版本规则评估变更。

服务端必须严格校验字段、十进制值与时间戳表示，核对主体与 Source 授权，在实际发送时执行相应权限检查。行情事实及解析计划仍归各自的所有者。客户端类型、Schema 校验或静态契约检查均不能授予访问权。
