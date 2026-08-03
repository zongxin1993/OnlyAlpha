# Paper Real Product Acceptance

该验收只覆盖：

```text
Paper Read-Only Market Observation
+
Shadow Order Safety
```

它不表示 Production Paper Runtime 已完成。断线重连、实时 Gap Recovery、Streaming Recovery、广泛 MiniQMT 兼容性和 Live Runtime 仍不在当前范围。

## 冻结 Profile

```text
Windows + PAPER + SHADOW
MiniQMT isolated historical worker v2
000001.XSHE / 000001.SZ
external 1m / internal 3m
MACD + required Factor
MEMORY persistence
real Broker disabled
```

计划文件为 `examples/acceptance/miniqmt_paper_v2.yaml`，Runtime 配置为 `examples/configs/miniqmt_paper_acceptance.yaml`。真实历史验收固定使用 `force_refresh`，不得自动回退旧缓存或切换证券。

## 命令

```powershell
uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case automated `
  --output user_data/acceptance/paper

uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case historical-snapshot `
  --output user_data/acceptance/paper

uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case live-handoff `
  --target-live-bars 6 `
  --output user_data/acceptance/paper
```

Live Handoff 只在 A 股 `OPEN` 且当前 Session 剩余窗口足够时执行。休市或窗口不足返回 `NOT_EXECUTED`，不得重试、改 Bar 或改证券制造 PASS。

## 判定

Required Evidence 的严格优先级为：

```text
FAIL > BLOCKED > NOT_EXECUTED > PASS
```

Optional Evidence 不参与总体 PASS。真实环境结果与 Automated Contract 必须分开记录，Fake SDK 通过不能升级真实产品状态。

Runner 只调用 `OnlyEngine.initialize/start/wait/stop/close`，并通过 `OnlyEngineInspectionService` 读取不可变聚合快照。它不直接调用 Runtime、Strategy、Finalizer、Indicator 或 Manager。
