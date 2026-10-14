# user_data

`user_data` 是文件型运行数据的根目录，不是 Python 环境、缓存的统称或旧版本兼容层。复用 `OnlyUserDataLayout`；
PostgreSQL 中的配置、凭据密文和业务记录，以及 ClickHouse 中的行情事实仍由各自 Authority 拥有。

## 位置配置

源码运行的 HTTP API、Research Worker 和 Backtest Worker 使用显式 `--user-data-root /absolute/path`，共享同一个
已初始化的存储。根目录可以配置为项目中 gitignored 的 `user_data/`，也可以指定源码树以外的目录；自定义运行目录
不要放在会被打包或冻结复制的源码树内。该参数不初始化数据库、创建密钥或收养旧存储。

Docker 使用 canonical `deploy/docker-compose.dev.yml` 的 `user-data` 数据卷，挂载为 `/var/lib/onlyalpha`。
数据卷与容器生命周期分开，普通 dev 启动仅引用已有卷。路径不等于 namespace identity；不同本机路径可以暴露同一存储，
相同路径也可能指向不同存储，须按 ADR 0096 验证数据库与 semantic-store 的配对。

## 内容与生命周期

- `secrets/`：凭据解密密钥及受保护的访问材料；不能作为源码、构建输入或测试日志输出。
- `research/`：immutable Dataset/Result/Artifact、namespace identity、运行版本材料及明确可再建的 projections。
- `backtest/`、`runs/`、`state/`：回测证据、运行输出与恢复状态；行情 WAL 等也使用同一配置根目录。

普通启动、停机重启、工程升级、重建镜像和替换容器均保留数据。开发阶段可独立选择“清空 dev 数据并重新初始化”，
但必须明确本次范围，协调数据库、文件、密钥和 namespace，解决未决工作；不能只删目录再自动重绑已有数据库。
正式部署不继承开发清空许可，删除须有人工授权、配对备份、恢复验证与保留策略。准则 Authority 见 `AGENTS.md` §6.1–6.2。

升级/重启验证必须读取和使用既有历史，而非初始化空库。迁移、exact identity、immutable history、引用完整性与恢复能力
属于 correctness，不是要保留的旧版本兼容处理。fresh reader/process restart 测试不等同于真实数据库服务重启或部署升级。
配对备份与恢复见 `docs/operations/research-service.md`，缺失或损坏数据必须 fail closed。

正式运行写入 `user_data/runs/<engine_id>/<run_id>/`。缓存、状态、历史数据和临时能力后续也必须使用同一根布局，
不得写入 `src/`、`examples/` 或 `tests/`。绝对路径、run_id、PID 和墙钟耗时不得进入业务确定性指纹。
