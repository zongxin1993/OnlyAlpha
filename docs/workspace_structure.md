# OnlyAlpha 工作区结构

仓库 taxonomy 是稳定的物理边界：

```text
OnlyAlpha/
├── src/onlyalpha/                  OnlyAlpha 稳定 Kernel、domain、application、runtime、ports 与 Plugin SPI
├── plugs/                          通过 Plugin SPI discovery/registry 装配的官方 concrete plugins
│   └── onlyalpha-plugin-<NAME>/
├── packages/                       非 Plugin 的独立构建、版本、部署或复用组件
│   ├── onlyalpha-web-console/
│   ├── onlyalpha-http-server/
│   └── onlyalpha-gateway-protocol/
├── contracts/                      版本化 Product / infrastructure contracts
├── tests/                          fixtures、scenario、conformance 与 correctness proof
├── deploy/                         infrastructure configuration
└── scripts/                        engineering and operator tooling
```

唯一归属判定流程：

1. 通过 OnlyAlpha Plugin SPI 被 discovery + registry + capability 动态装配？是 → `plugs/onlyalpha-plugin-<NAME>/`。
2. 否则，是否需要独立构建、版本、部署或作为独立工程组件复用？是 → `packages/onlyalpha-<FUNC>-<NAME>/`。
3. 否则，是否属于稳定、市场无关的 canonical semantics 或 application/runtime infrastructure？是 → `src/onlyalpha/`。
4. 否或不确定时，先作 architecture decision，不凭目录感觉归类。

Plugin 使用 lower-kebab-case 的 `onlyalpha-plugin-<NAME>`；组件使用
`onlyalpha-<FUNC>-<NAME>`。`apps/` 与 `packages/provider|market|api|protocol|factor|indicator|target|fake`
等 category-first wrapper 不属于当前结构。Web 是 Product API 的人机交互组件，HTTP server 是可替换 transport component，
Gateway protocol 是 infrastructure contract；它们都不是 Kernel Plugin。OpenAPI Product Contract 始终由根目录
`contracts/` 治理。
