# Web Market Profile Query Models

未来 Application Service 应返回带 `schema_version` 的不可变 Profile、Version、Capability、Scenario、Assertion、Decision、Settlement 和 Margin DTO，支持分页、过滤及稳定排序，不暴露 Registry 或 Runtime 内部可变对象。

本任务未实现 FastAPI、数据库、WebSocket/SSE 或权限；Query DTO/Port 也尚未交付，当前稳定读取边界仅为 Resolved Profile/Rule Manifest domain projection。

