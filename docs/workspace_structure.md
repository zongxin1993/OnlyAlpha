# OnlyAlpha 工作区工程结构

OnlyAlpha 工作区由三个并列、独立发布的项目组成。项目之间不得通过复制源码形成隐式耦合。

```text
workspace/
├── OnlyAlpha/          核心库、CLI、领域模型、Engine/Runtime/Cluster 容器和基础设施
├── OnlyAlpha-examples/ 官方示例、教程、可运行用例及其生成结果
└── OnlyAlpha-plugins/  官方 Strategy、Factor、扩展组件和 Cluster 配置
```

## OnlyAlpha

只承载通用核心能力。不得加入具体官方策略、因子或产品 Cluster 配置。核心仓测试需要动态组件时，使用
`tests/runtime_support/` 下明确命名的 Test Adapter；Test Adapter 不进入 wheel。

## OnlyAlpha-examples

承载所有官方示例的入口、教程、工作流和生成结果。示例通过已安装的 `onlyalpha` 与 `OnlyAlpha-plugins` 公共接口运行，
不得复制 Engine、Runtime、Strategy 或 Factor 实现。

## OnlyAlpha-plugins

承载全部官方 Strategy、Factor、数据/Broker/输出等扩展组件，以及官方 Cluster 单文件配置。一个 Cluster 配置文件只能
定义一个 `cluster`，不得使用 `clusters[]`。插件只依赖 OnlyAlpha 公共接口，不得导入核心内部状态或测试模块。

## 依赖方向

```text
OnlyAlpha-examples -> OnlyAlpha-plugins -> OnlyAlpha
OnlyAlpha-examples ---------------------> OnlyAlpha
```

OnlyAlpha 不得反向依赖另外两个项目。三个项目使用各自的 `pyproject.toml`、测试、版本和发布流程。

## 当前迁移状态

三仓目录已经建立，但 `OnlyAlpha-examples` 仍暂存上一阶段的 MACD Strategy/Factor 和 Cluster 配置，`OnlyAlpha-plugins`
尚未填充。本次运行架构收敛任务按 prompt 明确不执行外部插件仓库拆分或策略示例迁移；后续迁移必须在两个外部项目中
独立完成，并同步各自 CI，不能把这些资产复制回 OnlyAlpha 核心包。
