# Market Data Source Demo

这些示例只使用正式 `DataSource/Gateway → Replay/Queue → Processor → Pipeline` 入口。运行方式：

```bash
uv run python -m examples.data_source_demo.in_memory_history_demo
uv run python -m examples.data_source_demo.parquet_history_demo
uv run python -m examples.data_source_demo.csv_import_demo
uv run python -m examples.data_source_demo.multi_instrument_replay_demo
uv run python -m examples.data_source_demo.gap_detection_demo
uv run python -m examples.data_source_demo.live_in_memory_gateway_demo
uv run python -m examples.data_source_demo.full_vertical_slice_demo
```
