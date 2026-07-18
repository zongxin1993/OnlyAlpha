# OnlyAlpha 工作区工程结构

OnlyAlpha 工作区由三个并列、独立发布的项目组成。项目之间不得通过复制源码形成隐式耦合。

```text
workspace/
├── OnlyAlpha/          核心库、CLI、领域模型、Engine/Runtime/Cluster 容器和基础设施
├── OnlyAlpha-examples/ 官方示例包、示例 Cluster 配置、教程与工作流
└── OnlyAlpha-plugins/  可复用的官方扩展组件与基础设施适配器
```

## OnlyAlpha

只承载通用核心能力。不得加入具体官方策略、因子或产品 Cluster 配置。核心仓测试需要动态组件时，使用
独立测试 distribution 中明确命名的 Test Adapter；Test Adapter 不进入 wheel。

## OnlyAlpha-examples

承载官方示例专用 Strategy/Factor、示例 Cluster 配置、教程和工作流。示例通过已安装的 `onlyalpha` 公共接口运行；若使用
`OnlyAlpha-plugins`，也只能使用其公开插件 API。不得复制 Engine、Runtime 或通用基础设施实现。

## OnlyAlpha-plugins

承载可跨示例复用或面向产品的官方 Strategy、Factor、扩展组件，以及 DataSource、Broker 等基础设施适配器。基础设施插件只依赖
`onlyalpha.plugin.api` 和明确公开的领域/Port，不得导入 Engine/Runtime 私有实现、Manager 状态或测试模块。

## 依赖方向

```text
OnlyAlpha-examples -> OnlyAlpha-plugins -> OnlyAlpha
OnlyAlpha-examples ---------------------> OnlyAlpha
```

OnlyAlpha 不得反向依赖另外两个项目。三个项目使用各自的 `pyproject.toml`、测试、版本和发布流程。

## 当前迁移状态

三仓目录已经建立。OnlyAlpha 已完成 DataSource/Broker SPI；OnlyAlpha-examples 已包含 MACD 示例包与 Cluster 配置；
OnlyAlpha-plugins 当前尚无实际插件实现。后续迁移必须按“示例专用留 examples、通用可复用进 plugins”判断，不得在核心仓
复制实现。测试用外部 distribution 仅位于核心 tests，不进入核心 wheel。
