# Test Suite Performance Baseline

采集日期：2026-08-02；平台：Windows；Python 3.12；版本：0.3.2。数据均来自本机真实命令，未使用历史估值。

## 收集范围与结论

修改前根 `testpaths` 收集 Core `tests/`、Tushare 和 MiniQMT，但遗漏 Virtual Broker。`pytest tests` 只收集 Core，
实测 1182 项；Virtual Broker 独立收集 34 项，因此完整 Workspace 至少 1216 项。Tushare/MiniQMT 已被根配置收集，
但真实 MiniQMT 只有 `skipif`，缺少正式 External Marker；多数测试没有主层级 Marker。不同 distribution 的同名
`conftest` 不能安全放进同一 pytest 进程，统一 runner 因而按 distribution 隔离执行并汇总退出状态与 metrics。

修改前只声明 `unit/contract/integration/scenario/conformance/external` 等部分 Marker，缺少
`architecture/recovery/performance/miniqmt/requires_broker_account`；显式使用主要集中在参数化，层级 Marker 使用很少。
External 现在必须同时声明具体环境要求。Fake MiniQMT 是 `contract + miniqmt`；真实历史读取是
`external + miniqmt + requires_local_qmt + windows`。

## 修改前性能基线

| 命令 | 收集/结果 | Worker / dist | 实测总耗时 |
|---|---:|---|---:|
| `pytest tests -q --durations=100 --durations-min=0.2` | 1182 passed | 0 | 1479.04s |
| `pytest -n auto --dist=load tests -q ...` | 1182 passed | auto / load | 569.44s |

并行时间为串行的 38.5%，但最慢 Recovery 单项由 62.01s 上升到 76.17s，说明 `auto` 存在资源竞争，不能作为所有
层级的固定最优值。提示要求的 `-n 4/6/8 --dist=worksteal` 完整矩阵未在本轮重复执行：两条必需基线已消耗约
34 分钟，剩余矩阵应由 metrics 趋势继续实测，不能伪造。

最慢 11 项全部是 Engine Recovery/Checkpoint/Multi-Fill，串行 call 为 53.61–62.01s。其后主要是
multi-cluster close recovery（约 30s）、registration-order determinism（27.09s）、Virtual Broker multi-fill
（25.99–26.55s）和多阶段 continuation recovery（22–25s）。

## 重复成本审计

静态搜索覆盖 Core 与插件测试：51 个文件构造 `OnlyEngine`，10 个涉及 Parquet/pyarrow，43 个涉及 SQLite，63 个涉及
checkpoint，13 个涉及 artifact，80 个涉及 report，8 个涉及 analytics。主要重复路径如下。

| 测试/Fixture | 当前耗时 | 主要成本 | 重复来源 | 建议层级/改造 | 保留完整 Engine |
|---|---:|---|---|---|---|
| long-close recovery matrix | 53–62s/项 | 无故障、故障、恢复 Engine + SQLite | 每故障点重建 baseline | recovery；模块级不可变 baseline/只读 DB 模板 | 是（故障与恢复） |
| causal/tail recovery | 53–58s/项 | 多阶段 Engine + checkpoint | 相同业务前缀反复生成 | recovery；复用完整 result baseline | 是 |
| multi-cluster registration order | 27.09s | 两次完整 Engine | determinism 双运行 | integration/slow；仅专门测试双运行 | 是 |
| Virtual Broker multi-fill | 25.99–26.55s | 完整产品链、多 Bar | 同类 close 场景 | integration；保留最短产品纵切面 | 是 |
| Analytics tests | 最高 1.77s | 重跑 Engine | 下游重复证明产品入口 | unit；固定 Result fixture | 否（留一条纵切面） |
| Report tests | 最高 2.38s | Engine + Markdown | 每测试重新生成业务结果 | unit；固定 Result/Analysis + tmp_path | 否（留一条纵切面） |
| Artifact tests | 最高 4.59s | Engine + JSON/Parquet/manifest | 完整运行与文件 I/O 重复 | contract；固定 Result + tmp_path | 否（留一条纵切面） |
| Collector integration | 4.85s | Engine + result collection | 重复策略运行 | contract；正式 Snapshot/Fact fixture | 否（留一条纵切面） |

长 MACD/完整 equity timeline、注册顺序、multi-cluster、checkpoint/restart 和 result fingerprint 的专门确定性覆盖应保留；
下游确定性改为对同一不可变输入调用两次。当前 P0 基础设施未改变生产业务或经济语义；进一步 baseline fixture
复用需独立修改测试 fixture 并用完整 Recovery 对账验证，不应在没有充足验证窗口时仓促合并。

## 本轮通道实测

| Lane | 修改前 | 修改后 | Worker / dist | 测试数 | 结果 |
|---|---:|---:|---|---:|---|
| fast | 无正式通道 | 45.68s | auto / load | 886 | passed |
| integration | 无正式通道 | 78.44s | 6 / worksteal | 103 | passed |
| ashare | 无正式通道 | 7.11s | 4 / worksteal | 17 | passed；MiniQMT Golden 分片为 0 |
| recovery | 与全量混跑 | 378.51s | 4 / worksteal | 238 | passed |
| miniqmt-contract | 无正式通道 | pytest 6.81s | auto / worksteal | 10 | passed，完全离线 |
| full | 569.44s（仅根 `tests`） | 691.37s | auto / load | 1247 | passed，覆盖四个 distribution |

修改后数字为 lane metrics 插件测量的 pytest session 聚合值；修改前没有可对应的分层通道，不能杜撰对照数。
Full 增加了此前遗漏的 Virtual Broker、插件 distribution 和新增架构门禁，因此与修改前 1182 项不属于同一收集范围。

## 未完成与环境边界

MiniQMT Golden Dataset 与采集脚本尚未建立，故 ashare 的 MiniQMT 分片没有测试；真实 `miniqmt-local` 因未确认
`userdata_mini_path`/`xtquant` 环境而未执行，不能算作通过。Recovery baseline 仍在各故障测试中重复生成，本轮只完成
成本审计和独立分层，尚未实施安全的只读 SQLite 模板复用。`-n 4/6/8/auto --dist=worksteal` 全量 worker 矩阵也尚未
补齐。上述项目没有通过删除覆盖、`skip/xfail` 或生产测试开关隐藏。
