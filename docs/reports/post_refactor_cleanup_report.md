# 重构后接口唯一性清理报告

## 变更结论

- 删除字符串 Engine 构造、双模式状态、旧 Runtime Registry 与外部 Runtime 注册入口。
- 删除 Runtime 级产品运行服务、默认运行服务和独立 Runtime 结果输出器。
- 删除旧多 Cluster 产品配置类型；Parser/Error 按单 Cluster 文档职责重命名。
- DataSource/Broker 只接受 `plugin`，`type` 明确以 `UNKNOWN_FIELD` 失败。
- `OnlyOutputConfig` 只保留 `formats`、`overwrite`；产品输出只经 `OnlyUserDataLayout`。
- Engine 实例终止后禁止再次 initialize/run，stop 保持幂等。

## 测试与文档迁移

历史 Runtime 测试改为直接通过 Planner、Assembler、Factory 测试 Runtime，不再保留第二产品入口。新增
`tests/architecture/test_interface_uniqueness.py`，保护构造、导出、配置字段和输出根目录唯一性。更新 Engine、Backtest、
Cluster/Plugin 配置、ADR 0021、AGENTS、工作区边界与 HANDOFF。

## Vertical Slice 与边界

变更位于 `CLI → OnlyEngine → Planner → RuntimeSession` 装配边界，不改变 MarketData→Risk→Execution→Position→Ledger 链。
OnlyAlpha 核心、OnlyAlpha-examples 示例资产、OnlyAlpha-plugins 可复用插件保持独立；本任务只在示例仓原位迁移两个配置字段，
未复制跨仓源码。使用的 Synthetic DataSource、Virtual Broker 与测试插件边界保持不变。

## 验证

- 全仓 Pytest：通过（335 tests）。
- `tests/integration`：通过。
- Integration Demo：35/35 PASS。
- 100 次确定性重放：通过（包含在全仓与集成门禁）。
- 单 Cluster CLI：COMPLETED。
- 多 Cluster CLI：COMPLETED。
- dry-run：valid=true，未创建运行结果。
- OnlyAlpha-examples 官方配置 dry-run：valid=true。
- Ruff check / format：通过。
- Mypy `src`：305 source files，无问题。
- 残留检查：生产源码无被删除接口、兼容分支、旧输出器或默认 `output/` 产品路径。

## 已知限制

Paper/Live/Research 的真实外部能力仍不在本任务范围。OnlyAlpha-plugins 当前尚未承载实际插件，后续不得把示例专用代码与
可复用插件边界混淆。

## 最终结论

ACCEPTED
