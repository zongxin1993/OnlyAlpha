# OnlyAlpha Backend

## 目的与职责

后端承接正式API、权限、业务生命周期、持久化和受控作业；不将浏览器或Agent变为交易Authority。

## 边界与依赖

进程和数据库接线归后端，纯计算和交易语义由crates所属库负责。实际依赖见[Cargo.toml](Cargo.toml)；架构见[仓库说明](../../docs/repository-product-architecture.md)。

## 公开接口

入口见[src/lib.rs](src/lib.rs)和[src/main.rs](src/main.rs)。[application::job_contract](src/application/job_contract.rs)提供FrozenJobBinding、FactorExecutionBinding、ResultPlan及状态一致谓词；输入是有界类型化记录，输出规范化值／身份或错误，不授予认证、准入、发布或LIVE权限。持久化原语见[persistence::job_publication](src/persistence/job_publication.rs)和[persistence::factor_build](src/persistence/factor_build.rs)，提供不可变构建内容、精确参数引用、原 Run／Attempt 原子发布、完整读取与未知结果观察。输入为所属 owner 的私有令牌，输出已验证存储内容或明确错误；不接受外部 DTO 作为完成许可。实际角色、事务、预算和阶段边界见[PostgreSQL 发布说明](../../docs/postgresql-job-publication.md)，真实执行 owner 尚未接线。正式HTTP接口由transport code-first声明及contracts管理。

## 状态与生命周期

Command、Run、Attempt及恢复各有唯一owner；新框架值／事实关系见[有限作业契约](../../docs/job-execution-contract.md)。不能用值解析、hash或日志代替真实执行与正式发布。当前实现状态与目标架构分别说明。

## 使用与验证

数据库／应用验证经固定onlyalpha-dev及scripts/dev_verification.py。第一阶段纯契约定向命令为`cargo test -p onlyalpha-backend --lib job_contract_tests`，使用现有compiler_environment／冻结源码执行；不要求访问数据库。完整回归范围按任务影响选择。

第二阶段真实数据库回归使用独立目标 `cargo test --frozen --offline -p onlyalpha-backend --test application_job_publication -- --test-threads=1`；仅允许固定开发环境中的 `onlyalpha_dev_validation_test`。合成发布性能矩阵须显式 release／ignored 执行，见[BENCHMARK.md](BENCHMARK.md)。它不证明完整回测性能。
