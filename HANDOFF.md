# OnlyAlpha 工程交接说明

> 更新时间：2026-07-19（Asia/Shanghai）  
> 当前任务：`prompts/tushare_plugins_data_source.md` Tushare Historical DataSource 与日线回测纵切面

## 1. 修改前分析

- Historical Cache 已有 Provider/Store/Service、Parquet、Manifest、Hash、Fingerprint 和三种 Policy；首次写入后会 re-inspect 并从 Parquet 回读。
- 原 `OnlyHistoricalFetchResult.actual_coverage` 同时承担供应商成功查询范围与实际 Bar 范围。MiniQMT 以首尾 Bar 推导 Coverage，周末、节假日或合法空区间会造成 `cache remains incomplete after fetch`。
- 原 Cache Key 只有自由字符串 adjustment，不能以通用类型表达复权，也不能区分不同 QFQ 查询终点。
- MiniQMT 通过 `OnlyDataSourceCreateRequest.historical_cache_service` 接入核心 Cache，但 Factory 会立即加载 XtQuant；本任务未在核心加入 MiniQMT/Tushare 兼容逻辑。
- Domain 已有 `OnlyAdjustmentType`、`OnlyEquity`、`OnlyETF`、`OnlyTradingCalendar`；运行配置解析器此前只接受 ETF，600000 示例被迫错误声明为 ETF。
- Examples 正式入口为 `onlyalpha run --config ... --user-data ...`，由 Entry Point、OnlyEngine、Backtest Runtime 和 Virtual Broker 装配。

## 2. API 调用

- 参考 `vnpy_tushare` 稳定实现的 `set_token → pro_api → pro_bar`、SSE/SZSE/BSE 后缀、E/FD asset、`freq="D"`、返回倒序不可假定等行为；未复制 VeighNa 的 BaseDatafeed/HistoryRequest/BarData 等模型。
- Adapter 是唯一接触 SDK 全局模块的位置：`set_token(token)`、`pro_api()`，再严格按官方 doc_id=109 示例调用 `pro_bar(ts_code,start_date,end_date,asset,freq,adj)`。官方说明先 `set_token` 后内部 API 参数不是必需的，因此不额外传入 SDK 私有/版本相关参数。
- Provider 的 Fake Client 测试严格断言六个供应商参数。原始必需字段为 `ts_code/trade_date/open/high/low/close/vol`，`amount` 可选。
- 官方 A 股日线文档确认：价格单位为元，`vol` 为手，`amount` 为千元。

## 3. 插件实现

- 新增独立包 `OnlyAlpha-plugins/packages/onlyalpha-plugin-tushare/`，Entry Point 为 `onlyalpha.data_sources:tushare`，无 Broker Entry Point。
- Config 支持 `token_env` 与直接 token，环境变量优先；token 字段 `repr=False`，错误、Metadata、Manifest、Key、Fingerprint 均不含凭据。
- Loader 延迟导入 SDK；Factory/DataSource 构造不读 Token、不创建 Client。只有 Cache Service 发现缺口并调用 Provider.fetch 时才解析 Secret 与构建 SDK Client。
- Mapping 支持 XSHG→SH、XSHE→SZ、XBSE→BJ；资产按真实 Domain 类型 `OnlyEquity→E`、`OnlyETF→FD`，不按代码首位猜资产。
- Provider 负责范围转换、`pro_bar`、Raw Validation、Session 时间归一化、OnlyBar、resolved/observed 与质量报告；不实现 Parquet、Manifest、Lock、Missing Range 或 Atomic Write。
- DataSource 只调用核心 `OnlyHistoricalCacheService`；Doctor 为最小只读查询，不写 Cache、不打印 Token。
- 已安装分发实际发现 `tushare` Entry Point；两个示例 dry-run 均 `valid=true`。

## 4. 时间语义

- OnlyAlpha 请求始终为 UTC aware 半开 `[start,end)`；转换到 Asia/Shanghai 后，start 取当地自然日，end 减一微秒后取最后包含日，再生成 Tushare `YYYYMMDD` 包含式边界。
- `trade_date` 直接构造 `OnlyTradingDay`，禁止从 UTC date 推导。
- 通过请求 Instrument 的 `OnlyTradingCalendar.session_intervals_for_trading_day()` 得到 session_open/session_close；日 Bar 使用 `bar_start=session_open`、`bar_end=ts_event=session_close`，全部为 UTC aware。
- 示例业务区间是 Asia/Shanghai `[2025-01-01,2025-04-01)`，配置保存为等价 UTC `[2024-12-31T16:00Z,2025-03-31T16:00Z)`。

## 5. 数值单位

- OHLC：`Decimal(str(value))`，单位元，进入 `OnlyPrice`，不使用二进制 float 直接构造 Domain 值。
- Volume：官方单位手，显式 `Decimal(str(vol)) * 100` 转为股，再规范 Decimal exponent 后构造 `OnlyQuantity`。
- Amount：官方单位千元，显式 `Decimal(str(amount)) * 1000` 转为元，再构造 instrument quote currency 的 `OnlyMoney`；缺失时为 `None`。
- 严格拒绝 None/NaN/Inf/非正价格、OHLC 不变量、负 volume/amount、symbol 不一致和冲突重复；完全相同重复去重并产生 Warning。

## 6. 复权

- 核心直接复用通用 `OnlyAdjustmentType.RAW/FORWARD/BACKWARD`；核心没有 Tushare 专用 none/qfq/hfq 字符串逻辑。
- 插件映射为 RAW→`adj=None`、FORWARD→qfq、BACKWARD→hfq。
- Cache Key 新增通用 `price_adjustment` 与 `adjustment_reference`。FORWARD 使用请求结束包含日作为 anchor，不同 adjustment 和不同 anchor 均形成不同身份与 Fingerprint。

## 7. Cache

- `OnlyHistoricalFetchResult`、Manifest、Inspection 现分开保存 `resolved_ranges` 和 `observed_ranges`。
- Cache 完整性只看 resolved：供应商成功确认的请求区间可包含周末、节假日、停牌或合法空区间；observed 只记录实际 Bar Session。
- Tushare 成功响应返回 `resolved_ranges=(requested_range,)`；异常、鉴权/权限/限流、格式错误或无法确认的交易日空响应不会 resolved。
- Fake 纵切面证明首次 fetch→validate→Parquet/Manifest→re-inspect→Parquet read；第二次 CACHE_ONLY 无 Token、Client 创建次数和 SDK 调用次数均不增加，Bar 与 Fingerprint 一致。
- MiniQMT Provider 同步改为返回 requested resolved range 与实际 observed range，修复原 Coverage 根因；未增加任何 Tushare 兼容代码。

## 8. 测试与质量门禁

- OnlyAlpha：全量 `341 passed`；Ruff check 通过；512 files format check 通过；Mypy 313 source files 通过。
- Tushare + MiniQMT 联合插件测试：`26 passed, 2 skipped`；skip 为无环境变量的真实 Tushare integration 和无真实 XtQuant 环境。新增 Adapter 测试确认 `set_token → pro_api → pro_bar` 且 `pro_bar` 只接收官方六项 Provider 参数。
- OnlyAlpha-plugins 原生 workspace：`26 passed, 2 skipped`，Ruff check 通过，55 files format check 通过。Tushare 插件单独 Mypy 15 source files 通过；全插件 Mypy 仍被既有 MiniQMT 87 个 object typing 错误阻塞。
- OnlyAlpha-examples：Ruff check 通过，11 files format check 通过；无 pytest 测试。
- Entry Point 实际安装发现测试通过；两个 Tushare 配置 CLI dry-run 均 `valid=true`。
- Token 字面量全 Workspace 扫描无匹配；三个仓库 `git diff --check` 通过。
- 当前实际环境 Python 3.13.11 / Windows；未实际运行 Python 3.12、Linux、macOS 门禁。

## 9. 真实回测验收

- 安装并使用 Tushare 1.4.29。只读 Doctor 成功完成 SDK import、Token 解析和 Client 创建，但 `pro_bar` 对 600000.SH 的 2025-01-02 查询在 SDK 内因返回无 `close` 字段而重试三次并抛出 `OSError("ERROR.")`。
- 用户提供的可用对照 `pro.daily(000001.SZ, 20260101..20260107)` 已原样复测，并与直接 `ts.pro_bar`、OnlyAlpha Adapter 比较：三者在本机均失败。HTTP tracing 证明 Tushare 1.4.29 实际访问 `http://api.waditu.com/dataapi/daily` 时收到 **HTTP 503、空 body**；SDK 对非 2xx 响应静默返回空 DataFrame，`pro_bar` 随后才因缺少 `close` 报错。1.4.21 使用相同端点与 `pro_bar(..., api=...)` 签名，隔离检查证明降级不能修复该服务端状态。Token 未打印或落盘。
- 根据官方 doc_id=109 再次修正 Adapter：保持 `set_token`、`pro_api` 初始化，但 `pro_bar` 不再显式传 `api`，只传文档公开的 ts_code/start_date/end_date/asset/freq/adj；以 000001.SZ、20260101..20260107 重跑 Doctor，服务端仍返回同一空响应并最终失败，证明额外 `api` 参数不是失败根因。
- 首次正式 CLI 已实际执行：status=FAILED，run_id=`run-d38fe542d3744bccaae389b556976330`，cluster_count=1，determinism_fingerprint=`58f4cd6b939e39bc6fefbadd1a656bd7ddf99b3058bc79b1e99158b7e44ac4c5`，失败为结构化 `TUSHARE_REQUEST_FAILED`；manifest 路径记录在该 run 输出中。无成功 fetch，因此无 rows_fetched/content_fingerprint/cache manifest 可记录。
- 删除 Token 后已实际执行 CACHE_ONLY：status=FAILED，run_id=`run-30b9bd3f4f5c47ddb04292dc7447975f`，同一 determinism_fingerprint；因首次未生成完整 Cache，明确失败为 `valid cache does not fully cover the requested range`。该路径在读取 Token/创建 Client/访问 SDK 前失败。
- 因供应商返回空响应，本次不能诚实声明真实两次回测、Bar、Content Fingerprint 或收益结果一致。

## 10. 本任务未完成项

- Tushare `dataapi` 端点恢复非 503 响应后，重新执行用户的 000001.SZ 对照、Doctor、首次正式回测与无 Token CACHE_ONLY，记录 rows_fetched/rows_read/cache_hit/resolved/observed/content fingerprint 和两次回测一致性。
- 为 Tushare SDK 异常进一步验证并稳定分类 AUTH/PERMISSION/RATE_LIMIT（当前 SDK 对该空响应只暴露 `OSError("ERROR.")`，不能可靠反推错误类别）。
- 完成 Python 3.12、Linux、macOS 门禁。
- 清理插件仓既有 MiniQMT Mypy 87 个 object typing 错误，使全插件 `uv run mypy packages` 通过；这不是 Tushare/MiniQMT 兼容逻辑。
