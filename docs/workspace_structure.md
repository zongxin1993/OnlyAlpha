# OnlyAlpha 工作区结构

本仓库承载 Stateful Trading Kernel、版本化 Product API adapter、Web、官方 Plugin packages、协议、测试和部署资产。

```text
OnlyAlpha/
├── src/onlyalpha/          Kernel、domain、application、runtime 与 ports
├── packages/api/           Product HTTP process
├── packages/provider/      Provider adapters
├── packages/market/        Market Product plugins
├── packages/protocol/      Versioned infrastructure protocols
├── apps/onlyalpha-web/     Human interaction surface
├── tests/                  Fixtures、Scenario、conformance 与 correctness proof
├── contracts/              Generated/versioned public protocol projections
├── deploy/                 Infrastructure configuration
└── scripts/                Engineering and operator tooling
```

`examples/`、`prompts/`、root Product CLI 和仓内 Python Product client 不属于当前产品结构。测试专用配置必须位于
`tests/fixtures/` 并明确标记；正式 Runtime semantic input 不能从这些文件进入 Product admission。

依赖方向固定为：外部世界通过 Plugin/SPI 进入 Kernel；Web 与 machine consumers 通过 Product API 使用 Kernel；测试 harness
可以显式组合内部 Engine/Runtime，但该能力不构成外部产品合同。
