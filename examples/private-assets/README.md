# 私有资产公开示例

[factor/simple_momentum](factor/simple_momentum/asset.json)和[strategy/simple_momentum](strategy/simple_momentum/strategy.json)是可导入的非生产示例，不是已准入的策略或收益承诺。

[ADR 0151](../../docs/adr/0151-postgresql-business-publication-and-memory-work.md)要求因子编写降为Rust typed程序、精确参数分别认证；公开示例与私有资产必须走同一导入／校验／执行链路。第一阶段只补契约，不修改示例源码或承诺旧API兼容；示例源码和实际入口在第三阶段成套迁移与验证。
