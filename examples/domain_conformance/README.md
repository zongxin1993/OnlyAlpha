# OnlyAlpha Domain Conformance Demo

## 当前审计结果（2026-07-13）

- Conformance tests：16 passed，0 failed，0 skipped
- 全量 tests：31 passed
- Domain score：97/100
- 一票否决项：无
- 结论：`ACCEPTED`

未实现能力：实时/离线共用的完整 Bar 聚合算法、quanto PnL 显式换算模型、完整事件溯源订单对账。这些不妨碍进入“最小 Runtime 与 Backtest 数据驱动”阶段，但在进入 Live 交易前必须继续补齐相关执行与恢复测试。

评分刻意不是 100：MarketRule 扣 1 分，原因是尚未覆盖所有交易所级动态规则组合；Bar/time 扣 2 分，原因是本阶段只验证完整数据语义，没有实现实时与离线共用的聚合算法。

## 1. 目的

本 Demo 用于验证 OnlyAlpha 当前 Domain 是否具备多市场、多资产和完整基础数据描述能力。

它不是完整交易系统，也不是完整回测框架。

它只回答一个问题：

> 当前 Domain 是否已经足够稳定，可以继续构建 Runtime、EventBus、Backtest 和 Gateway？

---

## 2. 验证范围

覆盖：

- Domain 依赖纯净性；
- Price、Quantity、Money、Currency；
- Instrument；
- MarketRule；
- Precision 与 Increment；
- Tick；
- Bar；
- Order；
- Trade；
- Position；
- Account；
- Fee；
- Margin；
- PnL；
- 序列化；
- 历史版本；
- 多市场扩展；
- 确定性。

市场场景：

- A 股；
- A 股 ETF；
- 港股；
- 美股碎股；
- 中国期货；
- 期权；
- 外汇；
- Crypto Spot；
- Linear Perpetual；
- Inverse Perpetual。

---

## 3. 目录建议

```text
examples/domain_conformance/
├── README.md
├── run_demo.py
├── scenarios/
├── fixtures/
└── reports/

tests/domain_conformance/
├── test_00_domain_boundaries.py
├── test_01_financial_value_types.py
├── test_02_instrument_model.py
├── test_03_precision_and_increment.py
├── test_04_market_rules.py
├── test_05_bar_model.py
├── test_06_tick_model.py
├── test_07_order_trade_position.py
├── test_08_account_money_pnl.py
├── test_09_serialization_roundtrip.py
├── test_10_historical_versions.py
├── test_11_multi_market_scenarios.py
├── test_12_extensibility.py
├── test_13_determinism.py
└── test_14_domain_score.py
```

---

## 4. 运行方式

安装开发依赖：

```bash
python -m pip install -e ".[dev]"
```

运行全部测试：

```bash
pytest -q tests/domain_conformance
```

查看详细结果：

```bash
pytest -vv tests/domain_conformance
```

运行单项：

```bash
pytest -vv tests/domain_conformance/test_05_bar_model.py
```

运行场景 Demo：

```bash
python examples/domain_conformance/run_demo.py
```

---

## 5. 推荐验收顺序

### Step 0：Domain 边界

```bash
pytest -vv tests/domain_conformance/test_00_domain_boundaries.py
```

通过标准：

- Domain 不依赖 Engine、Runtime、Gateway；
- Domain 可以独立导入；
- 创建核心对象不需要外层模块。

### Step 1：金融值对象

```bash
pytest -vv tests/domain_conformance/test_01_financial_value_types.py
```

通过标准：

- Money 绑定 Currency；
- 不同币种不能直接相加；
- Price、Money、Quantity 不混用；
- 核心真值不使用 float；
- Decimal 精度不丢失。

### Step 2：Instrument

```bash
pytest -vv tests/domain_conformance/test_02_instrument_model.py
```

通过标准：

- 可创建全部目标资产类型；
- 字段语义明确；
- 子类型序列化后不丢失；
- 不适用字段不填伪造默认值。

### Step 3：Precision 与 Increment

```bash
pytest -vv tests/domain_conformance/test_03_precision_and_increment.py
```

通过标准：

- Precision 与 Increment 分离；
- Tick 与 Step 校验正确；
- 舍入策略显式；
- 核心代码不散落 `round()`。

### Step 4：MarketRule

```bash
pytest -vv tests/domain_conformance/test_04_market_rules.py
```

通过标准：

- T+1、涨跌停、Lot、Price Ladder、Session 等不写死在通用 Instrument；
- 同一资产抽象可应用不同规则。

### Step 5：Bar

```bash
pytest -vv tests/domain_conformance/test_05_bar_model.py
```

通过标准：

- Bar 有 InstrumentId；
- Bar 有 Specification；
- 开始、结束、事件、接收时间明确；
- 区间边界明确；
- 成交量语义明确；
- 午休、夜盘、时区和 revision 行为明确。

### Step 6：Tick

```bash
pytest -vv tests/domain_conformance/test_06_tick_model.py
```

通过标准：

- Trade Tick 与 Quote Tick 不混淆；
- 时间、顺序、来源和精度明确。

### Step 7：Order、Trade、Position

```bash
pytest -vv tests/domain_conformance/test_07_order_trade_position.py
```

通过标准：

- 订单状态机正确；
- 支持部分成交；
- Position 能表达不同市场约束；
- 重复和乱序事件有明确行为。

### Step 8：Account、Money、PnL

```bash
pytest -vv tests/domain_conformance/test_08_account_money_pnl.py
```

通过标准：

- 多币种明确；
- Account Equity 与股票资产类型不混淆；
- Fee、Margin、PnL 精度正确；
- 汇率转换显式。

### Step 9：序列化

```bash
pytest -vv tests/domain_conformance/test_09_serialization_roundtrip.py
```

通过标准：

```python
deserialize(serialize(value)) == value
```

并且不丢失 Decimal、时区、Currency、Enum、Instrument 子类型、Bar Specification 和版本。

### Step 10：历史版本

```bash
pytest -vv tests/domain_conformance/test_10_historical_versions.py
```

通过标准：

- 可查询历史时点有效 Instrument；
- Tick Size、Lot Size、Fee 可随时间变化；
- 历史回测不强制使用当前规则。

### Step 11：多市场场景

```bash
pytest -vv tests/domain_conformance/test_11_multi_market_scenarios.py
```

每个市场必须完成：

```text
Instrument
MarketRule
Order Validation
Tick
Bar
Order
Trade
Position
Fee
PnL
Serialization
```

### Step 12：扩展能力

```bash
pytest -vv tests/domain_conformance/test_12_extensibility.py
```

通过标准：新增 `OnlyBond` 不需要修改 Engine、Runtime、Cluster、EventBus、Bar 和 Order。

### Step 13：确定性

```bash
pytest -vv tests/domain_conformance/test_13_determinism.py
```

通过标准：相同输入多次运行结果一致。

### Step 14：评分

```bash
pytest -vv tests/domain_conformance/test_14_domain_score.py
```

输出最终评分、阻塞项和下一步建议。

---

## 6. 评分标准

| 维度 | 分数 |
|---|---:|
| Domain 依赖纯净 | 10 |
| 金融值对象与精度 | 15 |
| Instrument 描述能力 | 15 |
| Precision 与 Increment | 10 |
| MarketRule 分离 | 10 |
| Bar 与时间语义 | 15 |
| Order/Trade/Position | 8 |
| 序列化无损 | 5 |
| 历史版本能力 | 4 |
| 可扩展性 | 3 |
| 确定性与基础一致性 | 5 |
| 总分 | 100 |

结论：

| 分数 | 结论 |
|---:|---|
| 90-100 | 可以进入 Runtime 与 Backtest |
| 80-89 | 基本可用，但必须修复高风险项 |
| 70-79 | 仅适合作为原型 |
| < 70 | 不建议继续建设上层架构 |

---

## 7. 一票否决

以下任一情况存在，即使总分达到 90，也不能通过：

- Money、Price、Quantity 使用裸 float；
- Price、Money、Quantity 可以错误混用；
- 不同币种 Money 可以直接相加；
- Bar 没有 InstrumentId；
- Bar 没有明确时间语义；
- Instrument 与 MarketRule 严重混合；
- Domain 依赖 Engine、Runtime 或 Gateway；
- Decimal 序列化后变成 float；
- 期货没有 Contract Multiplier；
- Crypto 不能区分 Linear 与 Inverse；
- Instrument 没有历史版本和生效时间；
- 回测与实盘使用两套不同 Domain 类型；
- 新增市场需要修改 Engine 核心。

---

## 8. Demo 输出示例

```text
[PASS] DOMAIN_BOUNDARY
[PASS] VALUE_TYPES
[PASS] A_SHARE
[PASS] A_SHARE_ETF
[PASS] HK_EQUITY
[FAIL] US_FRACTIONAL
       reason: quantity_increment does not support decimal shares
[PASS] CHINA_FUTURE
[PASS] OPTION
[PASS] FX
[PASS] CRYPTO_SPOT
[PASS] CRYPTO_LINEAR_PERPETUAL
[FAIL] CRYPTO_INVERSE_PERPETUAL
       reason: inverse pnl model missing

Domain Conformance Score: 87/100
Status: CONDITIONALLY_ACCEPTED
```

---

## 9. 报告文件

Demo 应生成：

```text
examples/domain_conformance/reports/domain_conformance.json
examples/domain_conformance/reports/domain_conformance.md
```

报告至少包含：

- Git commit；
- Python 版本；
- 测试总数；
- 通过数；
- 失败数；
- 跳过数；
- 各维度得分；
- 一票否决项；
- 未支持能力；
- 推荐下一步。

---

## 10. CI 建议

```yaml
- name: Domain conformance
  run: pytest -q tests/domain_conformance
```

修改以下模块时必须执行：

```text
domain
instrument
market_rule
bar
tick
order
trade
position
account
serialization
```

---

## 11. 通过后的下一步

只有同时满足以下条件才进入 Runtime 与 Backtest：

- 总分至少 90；
- 无一票否决；
- 所有目标市场 Instrument 可创建；
- Bar 时间语义测试全部通过；
- 序列化无损；
- 历史 Instrument 版本可查询；
- 多市场 Demo 无阻塞失败。

通过后建议按顺序继续：

1. `OnlyClock`；
2. 同步 FIFO `OnlyEventBus`；
3. `OnlyRuntimeContext`；
4. `OnlyBacktestRuntime`；
5. 使用固定 Tick/Bar 驱动 `OnlyDemoCluster`；
6. 再实现撮合和账户状态更新。

未通过时，不要急着写 Engine 或 Gateway，应先修复 Domain。
