# user_data

运行文件、凭据和密钥由产品部署显式管理。PostgreSQL 保存业务、配置和凭据密文，ClickHouse 保存行情正文。

## 位置配置

原产品服务与其专用数据卷接线已退役。当前[开发 Compose 配置](../deploy/docker-compose.dev.yml)分别保留 PostgreSQL 和 ClickHouse 数据卷。运行数据必须独立于源码、构建和容器生命周期；存储与数据库按原命名空间身份配对，不能从路径相同推定身份相同。

## 内容与生命周期

- `secrets/`：凭据解密密钥及受保护的访问材料；不能作为源码、构建输入或测试日志输出。
- 保留工件与外部资源按原身份保存和读取。有限作业的未发布过程在内存，正式结果与成员按[发布契约](postgresql-job-publication.md)写入 PostgreSQL。

普通启动、停机重启、工程升级、重建镜像和替换容器均保留数据。开发阶段可独立选择“清空 dev 数据并重新初始化”，
但必须明确本次范围，协调数据库、文件、密钥和 namespace，解决未决工作；不能只删目录再自动重绑已有数据库。
正式部署不继承开发清空许可，删除须有人工授权、配对备份、恢复验证与保留策略。准则 Authority 见 `AGENTS.md` §4.1–4.2。

升级/重启验证必须读取和使用既有历史，而非初始化空库。迁移、exact identity、immutable history、引用完整性与恢复能力
属于 correctness，不是要保留的旧版本兼容处理。fresh reader/process restart 测试不等同于真实数据库服务重启或部署升级。
配对备份与恢复见 `docs/operations/research-service.md`，缺失或损坏数据必须 fail closed。

绝对路径、Run ID、PID 和墙钟耗时不得进入业务确定性指纹。运行文件不得写入源码、示例或测试目录。
