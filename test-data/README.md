# test-data

OnlyAlpha 测试数据根目录。放置规则见根目录 `AGENTS.md` 的 “Test placement standard”：
跨区域/golden/生成型数据在此，单区域场景数据放对应 `tests/<area>/fixtures/`。

| 目录 | 内容 | 再生/守卫 |
| --- | --- | --- |
| `binance/public_archive_certification/` | immutable Binance golden 数据清单 | 部署认证测试消费 |
| `clickhouse/` | ClickHouse 存储策略配置样例 | 当前无代码消费者，保留待集成 |
| `conformance/` | cn_a_share_production 冻结数据集 | `tests/conformance/cn_a_share_production` |
| `contracts/` | Research advisory bundle 合同样例 | `tests/application`、`tests/contracts` |
| `external_plugins/` | `onlyalpha-test-plugin` 可安装 distribution | uv workspace editable；`scripts/version_sync.py` |
| `legacy_macd/` | 跨区域共享 cluster 配置基线 | 多个引擎/恢复测试 |
| `miniqmt/` | MiniQMT 冻结历史数据 | `tests/conformance/cn_a_share_cash` |
| `recovery/` | Recovery golden baselines | `scripts/regenerate_recovery_baselines.py` + identity 守卫（fail closed） |
| `reference/` | A 股离线参考数据集 | `tests/reference`、`tests/scenario` |
| `remote_gateway/` | 远程网关 fake server | `tests/integration` |
| `results/` | 标准 Engine Result Fixture | `scripts/regenerate_result_fixtures.py` |
| `runtime/` | Runtime 装配测试 YAML | `tests/config`、`tests/integration` |
| `runtime_factor_provider/` | `onlyalpha-test-factor-provider` distribution | uv workspace editable |
| `scenarios/` | 场景 YAML | `tests/market`、`tests/scenario` |
| `web/` | Web E2E manifest | `scripts/prepare_web_e2e.py` |
| `test-durations.json` | pytest 时长权威缓存 | `scripts/test_suite.py` 读写 |
