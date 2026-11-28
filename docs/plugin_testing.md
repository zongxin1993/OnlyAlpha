# 插件验证

插件的功能测试按公开接口核对能力声明、生命周期幂等、失败回滚、标准事件转换和确定性。市场政策的精确数值对照由所属插件维护，例如[现货模拟政策测试](../plugs/onlyalpha-market-crypto/tests/spot_simulation.rs)。Gateway 的协议源与夹具归属见[网关协议](gateway_protocol.md)。

当前阶段按[工程指南](../AGENTS.md)仅运行 `crates/` 下 Rust 库的模块单测。插件功能测试保留在各插件目录，待恢复对应验证范围后执行。
