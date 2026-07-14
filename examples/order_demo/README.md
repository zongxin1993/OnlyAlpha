# Order Demo

这些示例只使用确定性本地输入和明确的 Placeholder，不连接真实券商，也不生成虚假成交。

```bash
uv run python -m examples.order_demo.create_and_submit_demo
uv run python -m examples.order_demo.partial_fill_demo
uv run python -m examples.order_demo.cancel_demo
uv run python -m examples.order_demo.duplicate_fill_demo
uv run python -m examples.order_demo.out_of_order_demo
uv run python -m examples.order_demo.context_order_demo
```

`create_and_submit_demo` 最终仅到 `SUBMITTED`；`cancel_demo` 的 `CANCELLED` 与所有成交均由示例显式注入。
