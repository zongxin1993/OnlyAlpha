# DataSource/Broker Plugin SPI 重构报告

## 本次新增组件

- `onlyalpha.plugin.api`：Plugin API 1.0、Descriptor、Capability、Lifecycle、Health、CreateRequest、Factory Protocol 与结构化错误；
- DataSource/Broker 统一 Factory Registry、确定性 Entry Point Discovery 与发现报告；
- 安装型 `onlyalpha-test-plugin` 独立测试 distribution；
- 外部插件场景 035、插件单元/集成测试和 CLI/dry-run 验收。

## 修改前创建链

DataSource/Broker 配置使用 `type`，内建 Synthetic/Virtual 的 Descriptor、Capability 与生命周期边界不完整，外部插件没有稳定
API Version 或真实 metadata 发现路径。Runtime 装配无法在创建前统一完成扩展配置解析和能力校验。

## 修改后创建链

```text
Cluster Config -> Descriptor -> Factory Registry -> parse_config()
-> Capability Validation -> Factory.create() -> Runtime lifecycle
```

组合根先注册内建 Factory，再按 group/name/value 稳定排序扫描 Entry Point。RuntimeAssembler 不识别具体插件 ID，也不解析
供应商字段。Broker 回报保持 `BrokerInboundQueue -> ExecutionProcessor -> Order/Position/Ledger/Account`，没有新增旁路。

## 公共插件 API

外部基础设施插件只依赖 `onlyalpha.plugin.api`、明确公开的 Domain/Port；测试适配器可使用明确隔离的
`onlyalpha.plugin.testing`。禁止依赖 Engine、Runtime、Assembler 私有实现或 Manager 内部状态。

## Plugin API Version 与 Descriptor

核心版本为 `1.0`。major 不同或插件 minor 高于核心时以 `PLUGIN_API_VERSION_INCOMPATIBLE` 拒绝；缺失版本、Descriptor
无效、类型不符分别使用结构化错误。Descriptor 固定包含 plugin_id、type、plugin version、API version、显示名、provider 与
capabilities，plugin_id 与 Python 包名解耦。

## DataSource SPI 与 Broker SPI

两类 Factory 均实现 `descriptor`、`parse_config`、`validate_request` 和 `create`。CreateRequest 只提供 Runtime 类型、Clock、
EventBus、Instrument/Calendar Registry、Logger，以及 Broker 所需的有界 inbound queue 等最小依赖，不传入 Engine 或服务容器。
Backtest DataSource 返回正式 Historical Source；Broker 返回现有 Gateway Port 的实现并产出标准化 inbound update。

## Capabilities

DataSource 覆盖 historical/live bars/ticks、instrument/calendar；Broker 覆盖 submit/cancel/replace、查询、live/simulated
execution。Backtest 在资源创建前要求 historical bars 和 simulated execution，缺失项返回
`PLUGIN_CAPABILITY_NOT_SUPPORTED`。dry-run 执行相同解析与能力校验，但不创建资源。

## Lifecycle 与 Health

统一生命周期为 CREATED、INITIALIZED、CONNECTING、CONNECTED、RUNNING、STOPPING、STOPPED、FAILED；健康状态为 UNKNOWN、
HEALTHY、DEGRADED、UNHEALTHY、STOPPED。启动按 DataSource/Broker initialize、connect、start 后进入 Runtime/Cluster；停止按
Broker、DataSource 逆序 stop 后 close。创建、连接、启动失败均逆序回滚全部已连接资源；单个 stop/close 失败不会跳过其余
资源，并返回包含 plugin_id/resource_id 的结构化错误。Engine Snapshot 展示状态、Health、Capability 和引用计数。

## Factory Registry 与 Entry Point Discovery

现有 DataSource/Broker Registry 已统一提供 `register(origin=...)`、`resolve`、`descriptors` 和 `records`。注册校验空 ID、API
兼容性、插件类型、Factory 形状与冲突；相同实现/Descriptor 可幂等注册，不同实现拒绝。Discovery 使用真实
`importlib.metadata.entry_points()`，支持 `onlyalpha.data_sources` 与 `onlyalpha.brokers`，并覆盖 fail-fast/continue 策略。

## 配置模型变化

公共 YAML/JSON 字段统一为 `plugin`，内部规范化为 `plugin_id`；`enabled` 控制资源是否参与规划。旧 `type` 仅兼容到 0.2，
该阶段曾短期兼容旧字段；后续接口唯一性清理已删除兼容分支，DataSource/Broker 的 `type` 现在作为未知字段失败。

## Synthetic 与 Virtual 迁移结果

内建 `synthetic@1.0.0` 和 `virtual@1.0.0` 已提供完整 Descriptor、API、Capability、Factory、Lifecycle 与 Health，并与外部插件
经过同一 Registry/Factory 创建链。修复了空 Broker queue 因布尔求值被替换的问题，Gateway 与 ExecutionProcessor 现在始终
持有同一个显式传入的有界 queue。

## 外部测试插件

`tests/fixtures/external_plugins/onlyalpha_test_plugin` 是独立安装包，提供 `test-external-data`、`test-external-broker` 两个真实
Entry Point。它使用固定 seed 生成历史 Bar，通过标准 queue 发出订单/成交更新，并提供完整生命周期和 Health。MACD
Strategy/Factor 仅作为该测试 distribution 的产品链 fixture，不进入 OnlyAlpha wheel。

## 接入的 Vertical Slice 位置

场景 035 接入 `Plugin Discovery -> Registry -> Capability -> RuntimeSession -> MarketData -> Indicator -> Factor -> Strategy ->
Order -> External Broker -> BrokerInboundQueue -> ExecutionProcessor -> Position/Allocation/Ledger/Account -> user_data`。场景复用
统一 `OnlyIntegrationEnvironment`，没有直接修改 Manager 内部状态。

## 新增与修改场景

新增插件 API、兼容性、Descriptor、冲突、发现策略、Registry、Capability、Lifecycle 单元测试，以及内建/外部回测、dry-run、
执行链、关闭顺序和 create/connect/start/stop 失败回滚集成测试。新增场景 035；场景 001-034 的业务断言未删除、未跳过、未
放宽，仅将完整场景数量断言从 34 同步为 35。

## CLI 回测与 dry-run 结果

- 外部正式 CLI：COMPLETED，指纹 `aee26e6764b5ce4b32e29163d6385d1b7679a2d97d2ab14aacf13da3b626f56a`；
- 内建正式 CLI：COMPLETED，指纹 `3750c259ff26b5144c87ae8f8824138799c3a07b175a7cb63b104f38024a5c43`；
- dry-run：发现内建/外部共四个插件，输出 origin/version/API/capabilities 和两个配置绑定，校验 `valid=true`；
- dry-run 输出目录未创建 `runs/`，未启动回放、资源生命周期或订单链。

## 失败回滚测试

create 失败释放 Engine 引用；connect/start 失败逆序 stop/close 所有已连接资源；stop 失败继续执行其余 stop/close，并在 Engine
结果中记录 `PLUGIN_STOP_FAILED`、plugin_id 与 resource_id。正常 stop/close 幂等与 Broker-before-DataSource 顺序均通过。

## 验证结果

- 组件单元与插件直接集成：19/19 PASS；
- Vertical Slice 自动化：36/36 PASS（35 个递增场景测试加一个完整环境测试）；
- Vertical Slice CLI：35/35 PASS；
- 全仓历史回归：330/330 PASS，耗时 128.66 秒；
- Ruff lint：PASS；Ruff format check：497 files formatted；
- strict Mypy：307 source files，0 issues；
- manifest、Order/Trade 数量、Scope、queue、ExecutionProcessor、Position/Allocation/Ledger/Account 与确定性指纹检查通过。

## 使用的 Placeholder/Fake

外部测试 DataSource/Broker 是明确命名、独立安装的确定性 Test Adapter；Synthetic/Virtual 是核心正式内建回测实现。没有真实
QMT/CTP/IBKR SDK、真实网络连接或真实账户，未启动实盘。

## 已知限制

- 当前产品装配完整支持 Backtest；Paper/Live 的真实 Adapter、自动重连与账户/仓位同步仍待后续实现；
- 不支持插件热加载/卸载；API 1.0 只承诺当前公开 SPI；
- `type` 兼容字段将在 0.2 删除；
- 本任务不处理 Strategy/Factor 的通用 Entry Point SPI，也不迁移真实官方适配器。

## 后续 OnlyAlpha-plugins 实施建议

工作区边界固定为：OnlyAlpha 维护核心 SPI；OnlyAlpha-plugins 承载全部官方 Strategy、Factor、扩展组件、Cluster 配置及
DataSource/Broker 适配器；OnlyAlpha-examples 只维护官方示例入口、教程、工作流和生成结果。真实插件应独立发布、固定 API
版本范围、只使用公共 Port，并为 Descriptor、Capability、配置脱敏、生命周期、标准事件转换和断线恢复建立契约测试。

## 是否允许进入下一组件

结论：**ACCEPTED**。
