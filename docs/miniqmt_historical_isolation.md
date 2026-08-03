# MiniQMT Historical Warmup 进程隔离

## 边界

MiniQMT 的原生历史查询可能在 BSON/C++ 层调用 `abort()`。这种失败无法被 Python `try/except` 捕获，线程也不能保护主进程。因此正式 Paper Warmup 使用短生命周期独立解释器：

```text
OnlyEngine
→ Paper Runtime
→ OnlyHistoricalWarmupPort
→ MiniQMT Isolated Client
→ python -m onlyalpha_plugin_miniqmt.historical_worker.worker
→ XtQuant historical API
```

每个 Worker 只处理一个请求，不继承 Runtime、Clock、EventBus、Cluster 或 Callback。正式 Runtime 只使用一个显式 `historical_compatibility_profile`，不会在启动期间盲试可能导致多次 native abort 的参数组合；参数矩阵只由诊断工具执行，且每个 Case 使用独立进程。

## 协议

协议版本固定为 `1`。请求使用 `request.json`，Bar 使用 `bars.jsonl`，成功清单使用 `result.json`，可捕获失败使用 `failure.json`。金额与数量均以字符串传输，时间使用 UTC ISO-8601 或 Unix ns，不传递 pandas、NumPy、XtQuant、Runtime 或 Callback 对象。

Worker 先写 `.bars.jsonl.tmp`、`.result.json.tmp` 或 `.failure.json.tmp`，执行 flush/fsync 后原子替换。Parent 只有在 Worker 退出码为零、正式结果文件齐全、协议版本正确、Request Fingerprint、Content Fingerprint 和 Bars File Fingerprint 全部一致，并再次通过 Bar 校验时才接受成功。

稳定退出码为：`0 SUCCESS`、`10 INVALID_REQUEST`、`11 SDK_IMPORT_FAILED`、`12 CLIENT_NOT_READY`、`13 DOWNLOAD_FAILED`、`14 QUERY_FAILED`、`15 EMPTY_RESULT`、`16 DATA_VALIDATION_FAILED`、`17 RESULT_SERIALIZATION_FAILED`、`18 PROTOCOL_ERROR`、`21 TIMEOUT`、`22 PROTOCOL_VERSION_MISMATCH`。没有有效 Failure Manifest 的非零退出统一映射为 `WORKER_ABORTED`，不得伪装成普通查询异常。

## 校验与缓存

Worker 和 Parent 均检查数量、严格递增、唯一键、OHLC、正价格、非负成交量、周期、Instrument、BarType、Instrument 价格精度和闭合边界。Content Fingerprint 只依赖规范化 Transport Records，不包含 PID、工作目录或日志路径。

验证后的结果复用现有 Historical Cache。Cache Key 纳入 provider、data version、adjustment 和 compatibility profile；请求覆盖未达到当前闭合边界时必须启动新 Worker，失败后不会回退到过期 Cache。

## 失败语义

Warmup 是 `REQUIRED`。`IMPORT_FAILED`、`QUERY_FAILED`、`WORKER_ABORTED`、`TIMEOUT`、协议错误或数据错误都会使 Runtime 在实时订阅前进入 `FAILED`，随后关闭 DataSource、Worker、Clock 和 EventBus。进程隔离解决的是 OnlyAlpha 主进程安全性，不是修复 XtQuant 原生 Bug；Isolation 通过不等于 MiniQMT Compatibility 或 Paper 产品验收通过。

诊断命令：

```powershell
uv run python scripts/diagnose_miniqmt_historical.py `
  --userdata-mini "C:\国金证券QMT交易端\userdata_mini" `
  --symbol 600000.SH `
  --output C:\temp\onlyalpha-miniqmt-history
```

工具不会修改正式 Runtime 配置。
