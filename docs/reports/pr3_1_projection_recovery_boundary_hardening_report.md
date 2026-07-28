# PR3.1 Projection Recovery Boundary Hardening Report

Date: 2026-07-28

## 1. 修改前审计

基线为 `d9bfc7e322adbbf6e5d5938a2383faa287023824`。详细审计及十二项回答见
`pr3_1_recovery_boundary_audit.md`。审计确认 Fee/Settlement current state 曾由 projection result 代替真实 Manager query，Applied
Ledger 丢失会把已安装 Result 误报为冲突，restore 与 ledger record 之间存在可恢复窗口，且当前恢复依赖正确 Bootstrap/Before
Authority，并非 Empty Runtime Full Replay。

## 2. Apply 状态机

正式 Target 统一执行 Component、Applied Ledger、真实 Current Authority、Expected/Result version/hash 检查。Expected path 返回
`APPLIED`；Result authority 且 ledger 缺失时修复 replay index、重建 record 并返回 `RECOVERED`。Batch 把 `RECOVERED` 视为成功，
并在结果中单独汇总 recovered components。冲突继续精确区分 `VERSION_CONFLICT`、`STATE_CONFLICT`、`PAYLOAD_CONFLICT` 和
`INVALID_COMPONENT`。

## 3. Fee Authority

`OnlyFeeManager` 保存 instruction、instrument、records、per-instruction version 和 global record sequence head，并提供正式
`get_execution_authority()`。相同 idempotency key 对应不同 instruction 会明确失败。Target 通过正式 converter 从 Manager snapshot
构建 current execution state，不再读取 `projection.after` 冒充 current。

## 4. Settlement Authority

`OnlySettlementManager` 保存 instruction、cash currency、四项 release flag、per-instruction version、records 和 global sequence
head，并提供正式 authority query/converter。注册版本为 1；release state 实际变化时版本递增。Planner、legacy parity harness 与
Manager 使用同一真实版本语义。

## 5. Applied Ledger

ADR 0039 明确 Transaction Store 是唯一持久事务权威。Applied Ledger 只是可丢弃、可重建的 Runtime application acceleration
index/checkpoint，不是第二套交易、费用、结算或账户真相。当前仍只提供内存实现。

## 6. Lost-ledger Recovery

十二个 Generic T0 Target 均覆盖 Manager 已安装、Applied Ledger record 缺失的重试。恢复结果为 `RECOVERED`，不会再次推进业务
version/event sequence，不会重复 record、timeline、reservation consumption、Event、outbox、journal 或 broker queue 副作用。
Manager install 成功而 ledger record 注入失败的窗口也由下一次重试关闭。

## 7. Target Atomicity

Restore 在 mutation 前完成 scope、version、record、sequence、timeline 和 identity 验证。Position、Allocation、Account 与 Strategy
Ledger 使用 copy-on-write install plan 和 repository authority replace，验证失败或 repository replace 失败时 Manager authority
保持不变；最终 container swap 不再包含可能失败的业务验证。Target 不实施跨 Manager rollback。

## 8. Bootstrap Boundary

ADR 0040 将当前能力限定为：`Correct Bootstrap / Before Authority + Ordered Committed Transaction Tail -> Runtime Authority
Recovery`。未来启动恢复需要 Durable Bootstrap Snapshot，并覆盖 account/ledger creation、order lifecycle、reservation creation、
external cash flow、broker snapshot、valuation、trading-day settlement、fee adjustment 等非 Trade authority。PR4 不承担 Runtime
startup recovery。

## 9. CI 和文档

Projection schema 文档已统一为 v4，旧 schema 不隐式迁移；ADR 0038、总体架构和 execution contract/target/prepared transaction
文档已同步。CI 删除重复 `uv lock --check`，恢复 Windows MiniQMT strict mypy 门禁。最新远端 CI 是基线提交 `d9bfc7e` 的
[CI #41](https://github.com/zongxin1993/OnlyAlpha/actions/runs/30328595273)，状态 Success，耗时 6m42s；当前工作区改动尚未提交，
因此没有对应的 GitHub Actions run，不能把基线 CI 充当本变更的远端验收。

## 10. 测试结果

- Prompt 八组定向测试合并执行：39 passed。
- Execution：205 passed；Architecture：32 passed；Integration：74 passed；Scenario：10 passed。
- Prompt 指定的 `tests/conformance` 不存在，原命令如实失败；真实目录 `tests/domain_conformance`：16 passed，另有 market
  conformance：1 passed。
- Core 非 external 总回归：645 passed。
- Virtual Broker：11 passed；Tushare：16 passed、1 deselected；MiniQMT：10 passed、1 个既有 skip。
- Ruff check/format：738 files passed；Core mypy：383 files；Tushare：15 files；MiniQMT：25 files；Virtual Broker：11 files，
  均为 0 errors。
- `uv lock --check`、frozen workspace sync、version sync、`git diff --check` 均通过。
- 四个正式 distribution 的 wheel/sdist 构建与 Twine check 通过。Tushare/MiniQMT 保留既有的空 long-description warning。
- 全新 Python 3.12.12 环境完成 Core-only smoke，以及四 wheel 联合安装、四模块导入和七个 Entry Point 加载。
- 干净安装环境运行 Generic T0 Scenario：`FILLED`、`PROFILE_RECORDED` 均为 `PASSED`。
- 35 项 integration demo 全部 PASS。未执行 external/network/Tushare Token/local QMT 测试；按用户要求未执行 pre-commit。

构建、干净环境和 Scenario 制品位于 `user_data/pr3_1_distribution/`。

## 11. PR4 Readiness

核心 Recovery Contract、Fee/Settlement Current Authority、lost-ledger recovery 和单 Target atomic restore 已达到本地验收标准，
PR4 无需重新设计这些契约。但当前变更尚无对应的 GitHub Actions run，未满足“本 PR 最终 workflow run”这一远端验收项。

**NO-GO：提交当前变更并取得完整 GitHub Actions Success 后，才可将 PR4 readiness 改为 GO。**
