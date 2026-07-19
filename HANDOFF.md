# OnlyAlpha 工程交接说明

> 更新时间：2026-07-19（Asia/Shanghai）  
> 当前任务：`prompts/cache_history_bar_data.md` Historical Bar Cache 纵切面

## 1. 修改前分析

- 原 MiniQMT Historical 链为 `Runtime Factory → MiniQMT DataSource.load_bars → download_history_data → get_market_data_ex → OnlyBar → Replay`，每次请求都下载完整范围，无持久缓存。
- 时间由 `utc_from_xt` 把 xtquant 毫秒值转换为 UTC；旧实现把该值同时作为 Bar start/event time，并用 `event.date()` 生成 trading_day。真实日线/分钟线供应商时间戳含义尚未在本机 MiniQMT 环境实测确认。
- `OnlyEngineConfig.user_data_root` 已是输出真值，但 DataSource SPI 原先未收到缓存服务；插件只能看到配置目录。
- 缺少 Coverage、Policy、Manifest、内容 Hash、Parquet、原子替换、quarantine 和离线二次回放。

## 2. OnlyAlpha 核心新增内容

- 公共接口：`onlyalpha.cache.historical` 中的 Provider/Store Protocol、`OnlyHistoricalCacheService`、`OnlyParquetHistoricalCacheStore`。
- `OnlyTimeRange`：严格 UTC、不可变、`[start,end)`，提供 contains/overlaps/intersection/subtract/merge/missing。
- Cache Policy：`CACHE_ONLY`、`PREFER_CACHE`、`FORCE_REFRESH`；未保留与 PREFER_CACHE 同义的 REFRESH_MISSING。
- Cache Key/Manifest/Inspection/Statistics/Fetch/Data Result 与结构化 Quality Issue/Report。
- Parquet Store：按事件年份分区，保存 schema version、event time 纳秒和无损确定性 `OnlyBar` JSON；不暴露 Arrow 给插件。
- Validation：身份、OHLC 正值、volume/turnover、排序和重复检查；非法数据不修复。
- Fingerprint：规范 Key + 排序 partition hashes，排除路径、审计时间、PID 和临时名。
- Atomic Write：同级 staging 目录完整写入、Parquet 回读、Manifest 生成、目录原子切换；失败恢复 backup。
- Quarantine：Manifest 缺失/损坏、Parquet 读取失败或 Hash 不符时隔离并返回结构化 Issue。
- user_data：Runtime Build 将 `OnlyEngineConfig.user_data_root` 传入 Backtest Factory，核心创建 `<user_data>/cache/market_data` Store 并通过公共 DataSource CreateRequest 注入服务。
- 文档：更新 `docs/storage.md`，新增 ADR `docs/adr/0016-historical-bar-parquet-cache.md`。

## 3. MiniQMT 插件修改

- 新增 `OnlyMiniQmtHistoricalDataProvider`，只负责供应商获取、标准化调用和 source metadata。
- `OnlyMiniQmtDataSource.load_bars` 在有核心服务时走 Cache Service，并把内容指纹写入标准更新 metadata；无服务时保留原兼容路径。
- 配置新增 `cache_policy`，默认 `prefer_cache`；`cache_only` 不调用 Provider/SDK。
- Entry Point 未变化：仍为 `onlyalpha.data_sources:miniqmt`。
- SDK Adapter 仍沿用现有 xtdata 注入边界；测试用 Fake XtData，没有 mock 深层全局函数。

## 4. 时间语义结论

- OnlyAlpha 绝对时间和查询边界：UTC aware datetime、半开 `[start,end)`；Replay 按标准 `ts_event` 排序。
- 当前 MiniQMT 实现把 SDK `time`（Unix ms）转为 UTC，并将其解释为 Bar open/event time；分钟 Bar end 为 open + period。
- 当前 trading_day 仍由转换后 event time 的 UTC date 生成，这不满足最终市场日历规则；必须在真实 SDK 语义确认后改成 Asia/Shanghai + TradingCalendar 推导。
- 日线 SDK 时间戳含义和查询 end 是否严格包含尚未实测，不能宣称已最终确认。

## 5. Cache 行为

- 命中要求：Manifest 版本/Key 匹配、所有 Parquet 可读、partition Hash 正确、Coverage 完整。
- Coverage 先合并重叠、相邻和重复区间，再计算左右/中间缺口。
- 首次运行：Provider fetch → 两层验证 → 原子 Parquet/Manifest → 重新 inspect/read → 返回 Replay 数据。
- 第二次：完整缓存直接读 Parquet；测试证明 `CACHE_ONLY` 不增加 Fake XtData download 次数。
- FORCE_REFRESH：获取整个请求范围，新记录按 event time 替换旧记录，并保留范围外记录；目录切换前旧缓存可用。
- 损坏数据不会进入 Replay；PREFER_CACHE 可在 quarantine 后重新获取，CACHE_ONLY 立即失败。
- 尚未实现任务要求的跨进程分区文件锁与 stale-lock 恢复。

## 6. Examples

- 新增 `OnlyAlpha-examples/examples/miniqmt_real_history_backtest/`，含 README、prefer-cache 配置和 cache-only 配置。
- 场景：600000.XSHG、1440 分钟（日线 SDK period）、2025-01-01 至 2025-04-01、MACD、Virtual Broker。
- 两份配置均通过正式 CLI `--dry-run`，Entry Point 解析为 MiniQMT DataSource + Virtual Broker。
- 当前正式配置解析器只支持 ETF reference 类型，因此配置临时使用 `asset_class: ETF` 承载 600000；README 已明确这不是正确资产分类。
- 未运行真实回测，故无真实 Bar 数、run 输出或 Data Fingerprint 可报告。

## 7. 测试结果

- 修改前核心基线：339 passed。
- 修改后 OnlyAlpha（Python 3.13.11）：341 passed；Ruff check 通过；format check 512 files 通过；Mypy 313 source files 通过。
- MiniQMT 插件：10 passed，1 skipped；skip 为需真实 xtquant/MiniQMT 的 opt-in integration。
- 插件独立 `uv run` 仍因 `onlyalpha` 不在 registry 无法解析；使用核心环境 + 插件 PYTHONPATH 完成上述测试。
- OnlyAlpha-examples：仓库无 pytest 测试；Ruff check/format 通过；两份示例 CLI dry-run 均 `valid=true`。
- Python 3.12.12 已检测到，但隔离 3.12 测试环境创建未获批准，未执行；Python 3.13 门禁如上。
- 真实 MiniQMT integration、首次真实下载、CACHE_ONLY 真实二次运行未执行（当前无可确认的 MiniQMT 服务/数据环境）。

## 8. 确定性结果

- Fake Provider/XtData 纵切面中，两次标准 Bar 序列一致、内容 Fingerprint 一致，第二次完全未调用供应商下载。
- 未取得真实 MiniQMT 两次回测结果，因此不能声明真实 Bar、Fingerprint 或收益结果一致。

## 9. 本任务未完成项与风险

- 实现跨进程分区锁、超时与 stale-lock 恢复测试。
- 在真实 MiniQMT 环境确认日线/分钟线时间戳、查询 start/end、无交易日/停牌空区间语义，并修正 trading_day。
- 真实运行示例两次，验证第二次 SDK 零调用及完整回测 Fingerprint，并写入 run data manifest/cache statistics。
- 增加 Parquet 分区过滤、写失败保留旧缓存、损坏文件 quarantine、FORCE_REFRESH、并发写等完整测试矩阵。
- 配置层支持 `OnlyEquity` 后把示例的 600000 从临时 ETF 类型改为真实资产类型。
- 完成 Python 3.12 门禁；为 plugins/examples 建立可独立解析本地 OnlyAlpha 的 workspace/uv 配置。
