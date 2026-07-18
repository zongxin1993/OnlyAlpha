# Plugin Testing

插件仓库至少验证 Descriptor/API、Capability、extensions、生命周期幂等、失败回滚、标准事件转换和确定性。OnlyAlpha 的
`onlyalpha-test-plugin` 位于 `tests/fixtures/external_plugins`，作为独立 distribution 安装，并通过真实 Entry Point 发现；
测试不得手工注册它绕过 metadata。

核心门禁包括内建 Synthetic/Virtual 回测、外部插件正式 CLI、dry-run、Broker Queue/ExecutionProcessor、35 个 Vertical
Slice 场景、确定性重放、全仓 pytest、Ruff 与 strict Mypy。
