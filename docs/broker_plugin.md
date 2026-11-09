# Broker 插件契约

Broker 插件以 Rust 库提供场所协议实现，由负责该运行流程的宿主显式构造和装配，复用
[`crates/broker`](../crates/broker/README.md) 的标准端口。Cargo 库存在或描述符可读取，均不等于产品已安装该券商，
也不授予 SIM、LIVE 或实盘变更权限。当前产品接线见[插件职责与能力](plugin-capabilities.md)。

## 职责与接口

插件拥有服务商 endpoint、签名、请求编码、错误分类、用户流和场所订单、成交、余额等观测的规范化。
连接、交易、订单查询、成交查询、账户与仓位快照、费用证据和发现能力分别遵守 Broker 的对应端口契约。
不具备完整证据的能力必须明确拒绝，不能用空集合、零余额或单币估值伪造完整账户状态。

模拟场所使用显式 Bar、Clock 和配置驱动确定性撮合。现行产品回测仍使用其已绑定的执行政策；
使用 Virtual Broker 库需要另行显式装配，不因语言迁移自动替换回测语义。

宿主提供当前 Scope、不可变工件绑定、命令 Journal、原始观测存储及 Runtime 读取端口。
凭据由宿主按 integration、field、generation 核对后解密并显式注入，不进入插件检查点、日志或源码。
插件不得从环境变量猜测凭据，不得直接修改 Order、Position、Ledger、Account 或策略状态。

```text
Runtime Ready intent → Broker Journal → 场所请求
场所观测 → 原始证据与 Broker Journal → Runtime 验证和应用 → 精确应用回执
```

## 命令与恢复

首次发送前，Broker 必须从拥有该意图的 Runtime 读取确切 Ready 证据，并持久化命令及发送标记。
ACK 只表示请求已接收，不等于订单已接受或成交。可能已发送而结果不确定时，保留原命令、原 client 和原场所关联，
继续查询、观察和对账；禁止盲目重发下单或用新命令替代未知结果。

发现结果必须区分缺证、无法读取、不匹配和确定匹配。`PRESENT` 需要确切原订单视图和完整缺失事实，
再由 Runtime 提供逐事实匹配的应用回执，并与重新读取的场所及本地订单视图比较。
布尔成功、有值的回执、自算摘要或旧订单已完成对账，都不能证明新成交已被应用。
只有完整证据支持的 `ABSENT_PROVEN` 才能解释原 SUBMIT；CANCEL 的缺席仍不确定，两者均不授权重发。

检查点绑定 Scope、配置、接口和实际原工件；读取时验证原始证据、顺序、关联及完整性。
断流、订阅终止或证据冲突应撤销相应信任；重新连接不等于恢复风险增加权限。
只读绑定可以执行获准查询，不能提交交易意图、下单或撤单；交易绑定仍须满足全部 Runtime 和风控门槛。

## 发行与历史

当前 Rust 插件的发行版本以自身 Cargo manifest 为单一来源，依[发行规则](release-versioning.md)管理。
历史 Python Factory、`onlyalpha.brokers` entry-point、wheel 和检查点属于其原发行及 Generation，
不再是当前生产装配的强制机制。历史任务仍需确切原工件及原恢复协议；不得用当前 Rust 库、相同版本号或源码归档冒充旧 wheel。

[ADR 0139](adr/0139-linux-first-rust-trading-kernel-migration.md)与
[Broker 设计](superpowers/specs/2026-10-19-rust-broker-design.md)记录共同协议及当时的迁移决策。
库测试只证明其相应性质；应用安装、持久化驱动、实际进程恢复、Web 流程及真实账户验证仍须分别取证。
