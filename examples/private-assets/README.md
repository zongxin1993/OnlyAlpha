# 私有资产公开示例

[factor/simple_momentum](factor/simple_momentum/asset.json)和[strategy/simple_momentum](strategy/simple_momentum/strategy.json)是可导入的非生产示例，不是已准入的策略或收益承诺。

[ADR 0151](../../docs/adr/0151-postgresql-business-publication-and-memory-work.md)要求因子编写降为 Rust typed 程序、精确参数分别认证。第三阶段示例 semantic_version=2：只输入 close，`delay(close, period)` 在每个实例内保存前值，输出相对收益，warmup 或分母为零时缺值；不把 bar.open 当作前收盘价。策略声明只消费同一因子版本和 period=1，不引入账户／风控输入。

公开示例与私有资产通过同一 Draft、不可变版本、构建队列、隔离编译、Rust 精确认证和 native batch/event 路径。回归位于 Backend `factor_build_tests::public_example_uses_the_same_revision_build_certificate_and_native_execution`。完整产品作业迁移尚按后续阶段推进，见[因子程序说明](../../docs/factor-program.md)。
