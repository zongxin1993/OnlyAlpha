# OnlyAlpha 工作区工程结构

OnlyAlpha 工作区由三个并列、独立发布的项目组成。项目之间不得通过复制源码形成隐式耦合。

```text
workspace/
├── OnlyAlpha/          核心库、CLI、领域模型、Engine/Runtime/Cluster 容器和基础设施
├── OnlyAlpha-examples/ 官方示例的运行入口、教程、工作流与生成结果
└── OnlyAlpha-plugins/  官方 Strategy、Factor、扩展组件、Cluster 配置及基础设施适配器
```

## OnlyAlpha

只承载通用核心能力。不得加入具体官方策略、因子或产品 Cluster 配置。核心仓测试需要动态组件时，使用
独立测试 distribution 中明确命名的 Test Adapter；Test Adapter 不进入 wheel。

## OnlyAlpha-examples

承载官方示例入口、教程、工作流和生成结果。示例通过已安装的 `onlyalpha` 与 `OnlyAlpha-plugins` 公共接口运行，不得
复制 Engine、Runtime、Strategy、Factor 或基础设施适配器实现。

## OnlyAlpha-plugins

承载全部官方 Strategy、Factor、扩展组件、Cluster 配置，以及 DataSource、Broker 等基础设施适配器。基础设施插件只依赖
`onlyalpha.plugin.api` 和明确公开的领域/Port，不得导入 Engine/Runtime 私有实现、Manager 状态或测试模块。

## 依赖方向

```text
OnlyAlpha-examples -> OnlyAlpha-plugins -> OnlyAlpha
OnlyAlpha-examples ---------------------> OnlyAlpha
```

OnlyAlpha 不得反向依赖另外两个项目。三个项目使用各自的 `pyproject.toml`、测试、版本和发布流程。

## 当前迁移状态

三仓目录已经建立。OnlyAlpha 已完成 DataSource/Broker SPI；将官方 Strategy、Factor、Cluster 配置与真实适配器迁入
OnlyAlpha-plugins，以及完善 OnlyAlpha-examples 的生成工作流，仍是后续独立任务。测试用外部 distribution 仅位于核心
tests，不进入核心 wheel。
