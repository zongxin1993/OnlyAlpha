# P0 Fixture Reuse Audit

审计日期：2026-08-02。范围为 Core 与 Workspace 插件的当前源码、正式测试、ADR 0023、0035、0044、0045、
0047、0049—0054，以及统一测试 Runner。本文冻结 P0.2/P0.3 本轮改造范围；`prompts/` 只用于说明目标，
实现以当前公共接口和测试为准。

## 当前重复执行

静态审计发现 51 个测试文件构造 `OnlyEngine`，46 个测试文件调用 `.run()`，32 个测试文件涉及 SQLite，
6 个测试文件直接涉及 Parquet。Result 下游中，Report、Artifact 和 Collector 分别重复运行同一 720-Bar MACD
场景；Artifact 确定性测试运行两次完整 Engine 并重复写入整套 JSON、Markdown 和 Parquet。

| 区域 | 重复路径 | 当前实测 | 本轮处理 | 保留的正式纵切面 |
|---|---|---:|---|---|
| Analytics / Report | 相同 MACD Engine 生成 Result 后再渲染 | 最慢约 2.38s | 标准不可变 Result Fixture；纯渲染读取固定输入 | Report 产品集成保留一条 |
| Artifact | 两次 Engine + 两套 Parquet/JSON/Markdown | 最慢约 4.59s | 固定 Result + `tmp_path`；只保留必要 I/O 合同 | Engine Artifact 保留一条 |
| Collector | 两次相同 Engine 证明确定性 | 约 4.85s | 固定正式 Result Projection | Collector 产品集成保留一条 |
| Long-close multi-fill Recovery | 每个故障点执行 Fault + Restart + Baseline | 53–62s/项 | 提交只读 Canonical Baseline，恢复结果统一对账 | Fault 与 Restart 均保留 |
| Multi-cluster close Recovery | 每个故障点重建无故障结果 | 约 30s/项 | 复用提交的无故障业务 Projection | Multi-cluster Engine 纵切面保留 |
| Causal/tail Recovery | 多阶段重启后再次运行 baseline Engine | 53–58s/项 | 先迁移最慢且场景稳定的 baseline 候选 | A→B→C 故障点不删减 |

修改前正式 Lane 基线为：fast 45.68s / 886，integration 78.44s / 103，ashare 7.11s / 17，
recovery 378.51s / 238，miniqmt-contract 6.81s / 10，full 691.37s / 1247。完整原始说明见
`docs/reports/test_suite_performance_baseline.md`。

本轮冻结的下游目录在基线提交中有 3 个 `OnlyEngine` 构造调用点；其中测试实际执行 5 次 `Engine.run()`：Report
1 次、Artifact 2 次、Collector 2 次。迁移后保留 Report 和 Artifact 各 1 条产品纵切面，共 2 次；Collector 改为读取
正式 Engine 生成的固定 Result。Artifact 的整套 8 个 Parquet 输出由重复写两套降为必要的一套，即 16 次降为 8 次。
Result Fixture 维护脚本的 Engine 执行不进入默认测试。

## Fixture 与 Baseline 候选

Result Fixture 固定为 `minimal_round_trip`、`multi_fill_round_trip`、`multi_cluster_close`。Fixture 必须由
正式 `OnlyEngine` 维护脚本生成，生成时间不参与业务指纹；测试默认只读，不在收集或执行阶段自动更新。

Recovery Baseline 固定为 `long_close_whole_baseline`、`long_close_multi_fill_baseline`、
`multi_cluster_close_baseline`、`terminal_after_partial_fill_baseline`。每个测试仍使用独立 `tmp_path` 和独立
SQLite；不会共享打开连接或可写数据库。只读模板复制通过内容指纹命名，并在复制前执行 SQLite integrity check。

MiniQMT Golden Dataset 只保存通过本机 MiniQMT 只读历史接口采集的冻结 Bar 与 Manifest。Golden Reader 位于
测试辅助目录，通过标准 DataSource SPI 和 MarketData Pipeline 进入 `OnlyEngine`；默认离线 Lane 不导入
`xtquant`、不访问网络，也不连接交易账户。

## 不在本轮改变的边界

不改变交易经济语义、YAML schema、Engine/Runtime 公共入口、Durable Transaction、Projection 或 Recovery
Authority。真实 Golden 验收暴露并修正了 MiniQMT 日线“本地交易日零点”被误当成 Bar 时刻的问题，修正仅位于 Provider
时间映射边界并有 Contract 覆盖。不删除 Recovery 故障点，不增加生产测试开关，不把真实 MiniQMT 或真实账户加入离线
通道。Worker 默认值只依据同机三次实测中位数更新；没有数据的组合不会伪造结论。
