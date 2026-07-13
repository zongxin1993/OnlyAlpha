# Time model scenarios

`run_demo.py` 构造 A 股、港股、美股、中国期货和 Crypto 五种 Calendar，演示同一套
UTC、IANA timezone、TradingDay 与 Session 规则。它不连接 Gateway，也不实现撮合或
完整 Backtest。

```bash
uv run --no-sync python examples/time_model/run_demo.py
```
