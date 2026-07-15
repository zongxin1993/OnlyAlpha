# Historical Data Source

`OnlyHistoricalDataSource` 使用强类型 request 和流式 `OnlyHistoricalDataStream`，不把 DataFrame 固定为核心接口。查询范围统一为
UTC 半开区间 `[start, end)`，必须指定 Data Version、Instrument、DataType；Bar 还必须指定 BarType 和 Adjustment Mode。第一版
只完整支持 `RAW`。

- `OnlyInMemoryHistoricalDataSource`：测试、Integration 与确定性最小数据集；
- `OnlyCsvHistoricalDataSource`：严格小规模导入，schema 恰为一个无损 `update_json` envelope 列；
- `OnlyParquetHistoricalDataSource`：正式本地列式格式，使用 pyarrow Dataset 下推 Source、Instrument、DataType、UTC range、
  Version 和 BarType 条件并按 batch 扫描；
- `OnlyRemoteHistoricalDataSource`：探索 Port。正式回测必须先下载、标准化、校验、版本化并落本地快照。

CSV/Parquet 都保存完整 Update，因此 Decimal、UTC 纳秒、Source Sequence、Version、Quality 和 Domain schema 可无损恢复。在线源
需要标记 `NON_DETERMINISTIC_SOURCE`，不会成为正式回测主循环的隐式依赖。
