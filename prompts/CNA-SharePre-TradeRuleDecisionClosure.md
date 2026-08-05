# PR2：CN A-Share Pre-Trade Rule Decision Closure

请认真阅读并修改 OnlyAlpha 工程：

```text
https://github.com/zongxin1993/OnlyAlpha
```

任务名称：

```text
PR2：CN A-Share Pre-Trade Rule Decision Closure
A 股申报前规则决策权威闭环
```

---

# 一、最高实施原则

本任务必须从第一性原则出发。

需要先回答：

```text
系统真正需要解决的问题是什么？
哪一个组件应当拥有规则权威？
规则的输入、输出和生命周期边界是什么？
怎样保证结果唯一、确定、可解释、可恢复？
```

不得从以下角度反向设计：

```text
怎样让现有测试继续通过
怎样让旧示例不需要修改
怎样保留旧接口
怎样避免修改调用方
怎样最少改代码
怎样兼容过去的错误抽象
```

本任务的优先级顺序必须是：

```text
1. 业务语义正确
2. 唯一权威
3. 工程边界清晰
4. 状态与数据流可证明
5. 确定性与可恢复性
6. 测试证明
7. 示例与文档
8. 兼容性
```

其中兼容性在本 PR 中不作为约束。

如果旧接口、旧测试、旧 Fixture、旧配置或旧示例与正确架构冲突：

```text
删除旧接口
重写旧测试
更新旧 Fixture
修改旧配置
替换旧示例
```

禁止为了历史兼容保留第二套权威。

---

# 二、允许进行破坏性重构

本 PR 明确允许：

```text
删除旧类
删除旧方法
删除旧 DTO
删除旧错误码
删除旧测试
删除旧 Fixture
删除旧示例
修改公共接口
修改配置 Schema
修改 Checkpoint Schema
修改 Artifact Schema
修改文档声明
批量修改调用方
```

不要求：

```text
向后兼容
Legacy Adapter
Deprecated Wrapper
双接口并存
旧序列化格式兼容
旧 Checkpoint 可恢复
旧 Artifact 可读取
旧示例原样运行
```

如果 Checkpoint Schema 或 Artifact Schema 发生变化，应：

1. 提升 Schema Version；
2. 明确旧版本不兼容；
3. Fail Closed；
4. 更新测试基线；
5. 不增加无意义兼容代码。

不得采用：

```python
if old_format:
    use_old_path()
else:
    use_new_path()
```

除非该分支代表真实、长期存在的产品语义，而不是迁移负担。

---

# 三、任务目标

建立 OnlyAlpha 唯一、正式、确定性的 A 股申报前规则决策链。

最终链路必须是：

```text
Order Request
→ Instrument + Trading Day
→ Versioned A-Share Reference
→ Effective Market Profile
→ Compiled Market Policies
→ Ordered Rule Evaluations
→ Stable Market Order Decision
```

核心目标：

```text
对于任意一笔 A 股订单，
系统能够根据当日有效的参考数据和交易制度，
唯一地回答：

是否允许申报？
为什么允许？
为什么拒绝？
使用了哪个制度版本？
使用了哪份参考数据？
价格上下限是多少？
数量规则是什么？
当前处于哪个交易阶段？
规则结果能否稳定重放和恢复？
```

PR2 的截止边界是：

```text
Order Request
→ Pre-Trade Market Decision
```

PR2 不进入：

```text
Broker Matching
Fill
Durable Transaction
Position Settlement
Fee Projection
Account Projection
Strategy Ledger Projection
```

---

# 四、当前已知架构问题

修改前必须以最新 `master` 为准重新审计，不得假设提示词中的描述一定仍然准确。

当前已知至少存在以下问题。

## 4.1 双重 Pre-Trade 规则权威

当前可能同时存在：

```text
OnlyMarketRuleEngine.evaluate_pre_trade()
OnlyMarketOrderValidator.validate()
```

两者均可能执行：

```text
Session
Tradability
Quantity
Position
Tick
Daily Price Limit
```

这违反唯一权威原则。

PR2 完成后必须满足：

```text
OnlyMarketRuleEngine
= Runtime 唯一正式 Pre-Trade Market Rule Authority
```

不得再有第二个独立 Validator 实现同类业务规则。

## 4.2 A 股价格比例静态化

当前 `CN_A_SHARE_CASH` Profile 可能仍使用固定：

```text
daily_limit_rate = 10%
```

但真实规则依赖：

```text
Profile Version
Trading Day
Exchange
Board
ST Status
```

静态 Profile Rate 不能直接代表最终已解析价格政策。

## 4.3 现有 ST 判断可能错误

不得使用：

```python
if st_status:
    return Decimal("0.05")
```

作为通用规则。

它会错误覆盖：

```text
创业板 ST
科创板 ST
制度变更后的主板风险警示股票
```

规则必须通过版本化制度矩阵解析。

## 4.4 价格边界没有正式 Tick 舍入合同

不能只计算：

```python
previous_close * (1 ± rate)
```

必须生成正式、Tick-aligned 的上下限。

## 4.5 Session 模型过于简化

当前可能把：

```text
13:00–15:00
```

全部表示为连续竞价，未区分收盘集合竞价。

PR2 必须区分真实交易阶段，即使当前 Matching 尚不支持集合竞价。

## 4.6 数量规则过于通用

简单的：

```python
quantity % lot_size == 0
```

不能表达所有板块的申报数量合同。

例如科创板最低数量和递增单位不能仅由一个 `lot_size` 表达。

## 4.7 错误码过于模糊

以下错误码不够精确：

```text
INSTRUMENT_NOT_TRADABLE
OUTSIDE_DAILY_PRICE_LIMIT
INVALID_QUANTITY
```

无法用于正式诊断、Scenario、Artifact 和后续 Order 拒绝事实。

---

# 五、开始修改前的强制审计

必须先阅读：

```text
AGENTS.md
README.md
docs/roadmap.md
docs/a_share_market_profile.md
docs/reference_data_authority.md
相关 ADR

src/onlyalpha/reference/
src/onlyalpha/market/models.py
src/onlyalpha/market/profiles.py
src/onlyalpha/market/registry.py
src/onlyalpha/market/runtime_rules.py

src/onlyalpha/order/
src/onlyalpha/risk/
src/onlyalpha/runtime/
src/onlyalpha/config/
src/onlyalpha/scenario/
src/onlyalpha/output/

tests/market/
tests/conformance/cn_a_share_cash/
tests/scenario/
tests/recovery/
tests/architecture/
```

全仓库搜索：

```text
OnlyMarketOrderValidator
evaluate_pre_trade
OnlyMarketOrderDecision
OnlyMarketRuleDecision
OnlyPriceRule
OnlyQuantityRule
daily_limit_rate
price_limits
only_cn_a_share_price_limit_rate
INSTRUMENT_NOT_TRADABLE
OUTSIDE_DAILY_PRICE_LIMIT
INVALID_PRICE_TICK
BUY_LOT_REQUIRED
ODD_LOT
available_quantity
SESSION_
OPENING_AUCTION
CLOSING_AUCTION
```

实施前必须输出审计结论，回答：

1. 当前正式 Runtime 实际调用哪条 Pre-Trade 路径；
2. 是否存在多套 Validator；
3. Order Service 与 Risk 如何调用 Market Rule Engine；
4. 当前规则执行顺序是什么；
5. 当前 A 股价格比例如何解析；
6. 当前上下限如何舍入；
7. 当前 Session 如何表达；
8. 当前数量规则如何表达；
9. 当前 Decision 如何序列化和 Checkpoint；
10. 哪些旧接口、测试和示例必须删除或重写；
11. 哪些模块不应在 PR2 修改。

不要在审计前直接开始堆叠新类。

---

# 六、唯一权威设计

## 6.1 唯一正式入口

正式入口必须是：

```python
OnlyMarketRuleEngine.evaluate_pre_trade(context)
```

或经过审计后确定的同等唯一入口。

所有 Runtime、Order、Risk、Scenario 和产品测试必须调用同一入口。

禁止：

```text
OrderService 自己检查涨跌停
Risk 自己检查交易时间
Strategy 自己检查整手
Virtual Broker 自己检查订单是否合法
另建 OnlyAshareOrderValidator
另建 OnlyAsharePreTradeManager
旧 Validator 与新 Engine 同时保留
```

## 6.2 删除旧 Validator

如果 `OnlyMarketOrderValidator` 与正式 Engine 重复：

```text
直接删除
```

同时：

1. 删除其测试；
2. 将仍有价值的业务场景迁移到 Engine 测试；
3. 修改全部调用方；
4. 删除相关导出；
5. 删除兼容 Wrapper；
6. 增加架构测试，禁止再次出现独立 Pre-Trade 实现。

不要保留 Deprecated 类。

---

# 七、制度版本模型

A 股规则必须由有效制度版本决定。

建议至少建立：

```text
CN_A_SHARE_CASH@2025.1
CN_A_SHARE_CASH@2026.07
```

具体版本名可根据当前项目约定调整，但必须体现生效日期边界。

建议有效区间：

```text
2025.1:
[2025-01-01, 2026-07-06)

2026.07:
[2026-07-06, +∞)
```

第一阶段价格比例矩阵：

## 2025.1

| Board     |  普通 | 风险警示 |
| --------- | --: | ---: |
| SSE_MAIN  | 10% |   5% |
| SZSE_MAIN | 10% |   5% |
| CHINEXT   | 20% |  20% |
| STAR      | 20% |  20% |

## 2026.07

| Board     |  普通 | 风险警示 |
| --------- | --: | ---: |
| SSE_MAIN  | 10% |  10% |
| SZSE_MAIN | 10% |  10% |
| CHINEXT   | 20% |  20% |
| STAR      | 20% |  20% |

必须通过：

```text
Trading Day
+
Effective Profile Version
+
Resolved Reference
```

共同解析。

禁止：

```text
当前日期决定历史规则
硬编码 symbol prefix
st_status 优先覆盖 board
一个永久有效的 Profile 表达全部历史制度
```

---

# 八、编译模型必须真正“已解析”

业务执行阶段不应再次读取：

```text
board
st_status
profile raw rules
```

这些输入应在 Compiler 阶段被解析成最终 Policy。

建议增加明确的编译结果。

## 8.1 编译后价格政策

```python
@dataclass(frozen=True, slots=True)
class OnlyCompiledPriceBandPolicy:
    regime_id: str
    tick_size: Decimal
    previous_close: Decimal
    daily_limit_rate: Decimal | None
    lower_limit: Decimal | None
    upper_limit: Decimal | None
    rounding_mode: OnlyPriceBandRoundingMode
```

要求：

1. 不保存 Raw Profile；
2. 不保存 Provider 对象；
3. 上下限已完成 Tick 舍入；
4. 所有数值使用 Decimal；
5. 不在 evaluate 阶段重新计算 Board/ST Rate；
6. 编译结果参与指纹。

## 8.2 编译后数量政策

```python
@dataclass(frozen=True, slots=True)
class OnlyCompiledQuantityPolicy:
    minimum_buy_quantity: Decimal
    buy_quantity_increment: Decimal
    minimum_sell_quantity: Decimal
    sell_quantity_increment: Decimal
    odd_lot_liquidation_allowed: bool
    maximum_limit_order_quantity: Decimal | None
```

不要继续用一个模糊 `lot_size` 表达所有数量语义。

## 8.3 编译后 Session 政策

应能明确区分：

```text
OPENING_AUCTION
CONTINUOUS
MIDDAY_BREAK
CLOSING_AUCTION
CLOSED
```

当前 Matching 不支持集合竞价时：

```text
OPENING_AUCTION
CLOSING_AUCTION
```

应返回：

```text
TRADING_PHASE_NOT_SUPPORTED
```

不能伪装成 Continuous，也不能错误标记为 Closed。

---

# 九、价格边界算法

## 9.1 输入

价格边界必须仅使用：

```text
previous_close
daily_limit_rate
price_tick
rounding_mode
```

其中 `previous_close` 来自 PR1 的正式 RAW Reference Authority。

不得使用：

```text
上一根 Bar.close
复权 Bar.close
当前 Tick
Strategy 输入
DataSource 私有字段
```

## 9.2 精确计算

所有计算使用 `Decimal`。

禁止 Float。

建议算法：

```python
raw_upper = previous_close * (Decimal("1") + rate)
raw_lower = previous_close * (Decimal("1") - rate)

upper = round_to_tick(raw_upper, tick, ROUND_HALF_UP)
lower = round_to_tick(raw_lower, tick, ROUND_HALF_UP)
```

需要根据正式规则验证具体舍入合同。

如果交易制度要求限制价格与前收盘价之间至少相差一个 Tick，需要显式实现并测试：

```python
if upper - previous_close < tick:
    upper = previous_close + tick

if previous_close - lower < tick:
    lower = previous_close - tick
```

不得依赖 Decimal 默认 Context 的隐式行为。

## 9.3 验证顺序

价格规则顺序固定为：

```text
PRICE_POSITIVE
PRICE_TICK_ALIGNMENT
PRICE_UPPER_LIMIT
PRICE_LOWER_LIMIT
```

错误码：

```text
PRICE_NON_POSITIVE
PRICE_NOT_ALIGNED_TO_TICK
PRICE_ABOVE_DAILY_LIMIT
PRICE_BELOW_DAILY_LIMIT
```

---

# 十、数量规则

## 10.1 主板和创业板

第一阶段：

```text
minimum_buy_quantity = 100
buy_quantity_increment = 100
```

## 10.2 科创板

第一阶段按正式制度建模：

```text
minimum_buy_quantity = 200
buy_quantity_increment = 1
```

因此：

```text
BUY 199 → REJECT
BUY 200 → ACCEPT
BUY 201 → ACCEPT
```

不能用：

```text
quantity % 200 == 0
```

## 10.3 卖出和零股

Context 中必须使用语义明确的字段，例如：

```python
unreserved_sellable_quantity: Decimal
```

不得继续使用含义模糊的：

```python
available_quantity
```

除非全工程已经严格定义其含义，并且没有其他解释。

零股规则：

```text
如果卖出数量不是正常递增单位：
只有当订单数量等于全部未预留可卖数量时允许。
```

例如可卖 250：

```text
SELL 100 → ACCEPT
SELL 200 → ACCEPT
SELL 50  → REJECT
SELL 250 → ACCEPT
```

错误码：

```text
BUY_QUANTITY_BELOW_MINIMUM
BUY_QUANTITY_INCREMENT_INVALID
SELL_QUANTITY_INCREMENT_INVALID
ODD_LOT_SELL_REQUIRES_FULL_LIQUIDATION
SELL_QUANTITY_EXCEEDS_AVAILABLE
```

PR2 不负责生成真实 T+1 可卖数量，只定义它作为输入的语义。

---

# 十一、Session 规则

第一阶段 Session 至少表达：

```text
09:15–09:25  OPENING_AUCTION
09:25–09:30  PRE_OPEN 或 CLOSED
09:30–11:30  CONTINUOUS
11:30–13:00  MIDDAY_BREAK
13:00–14:57  CONTINUOUS
14:57–15:00  CLOSING_AUCTION
其他时间      CLOSED
```

决策结果：

```text
CONTINUOUS
→ 进入后续规则检查

OPENING_AUCTION
→ TRADING_PHASE_NOT_SUPPORTED

CLOSING_AUCTION
→ TRADING_PHASE_NOT_SUPPORTED

MIDDAY_BREAK
→ MIDDAY_BREAK

CLOSED
→ MARKET_CLOSED
```

如果工程已有统一 Calendar/Session Authority，应在正确层扩展，不要另建 A 股时间判断函数。

---

# 十二、Tradability 规则

必须拆分：

```text
INSTRUMENT_SUSPENDED
INSTRUMENT_INACTIVE
REFERENCE_NOT_EFFECTIVE
REFERENCE_NOT_FOUND
REFERENCE_CONFLICT
```

不能继续使用：

```text
INSTRUMENT_NOT_TRADABLE
```

吞并不同业务原因。

推荐顺序：

```text
Reference coverage
→ Reference effective range
→ Suspension
→ Instrument lifecycle status
```

---

# 十三、Decision 模型

当前单一 `accepted + reason_code + details` 不足以构成正式规则诊断。

建议建立结构化 Evaluation。

```python
class OnlyMarketRuleEvaluationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class OnlyMarketRuleEvaluation:
    rule_code: str
    status: OnlyMarketRuleEvaluationStatus
    reason_code: str | None
    inputs: tuple[tuple[str, str], ...]
```

正式 Decision 建议至少包含：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketOrderDecision:
    accepted: bool
    reason_code: str | None
    evaluations: tuple[OnlyMarketRuleEvaluation, ...]

    trading_day: OnlyTradingDay
    trading_phase: OnlyTradingPhase

    normalized_price: Decimal
    normalized_quantity: Decimal

    previous_close: Decimal
    tick_size: Decimal
    daily_limit_rate: Decimal | None
    lower_limit: Decimal | None
    upper_limit: Decimal | None

    minimum_buy_quantity: Decimal
    buy_quantity_increment: Decimal
    sell_quantity_increment: Decimal

    position_effect: OnlyPositionEffect
    required_cash: Decimal
    required_position: Decimal

    compiled_identity: OnlyCompiledMarketRuleIdentity
```

允许根据现有模型调整字段，但必须满足：

1. 决策可解释；
2. 决策无 Provider 对象；
3. 决策不可变；
4. 决策可无损序列化；
5. 决策可 Checkpoint；
6. 决策可确定性比较；
7. 主错误码来自第一个失败 Evaluation。

---

# 十四、固定规则执行顺序

必须冻结规则执行顺序：

```text
1. Reference Coverage
2. Reference Effective Range
3. Effective Profile Resolution
4. Trading Phase
5. Suspension
6. Instrument Lifecycle Status
7. Supported Order Type
8. Side / Position Effect
9. Quantity Positive
10. Buy/Sell Minimum
11. Quantity Increment
12. Odd-Lot Liquidation
13. Price Positive
14. Tick Alignment
15. Previous Close Semantics
16. Daily Upper Limit
17. Daily Lower Limit
18. Sellable Position
19. Available Cash
20. Optional Dynamic Rules
```

同一个订单同时违反多个规则时，主错误码必须稳定。

例：

```text
午休
价格超过涨停
现金不足
```

主错误码必须固定为：

```text
MIDDAY_BREAK
```

其他规则可标记：

```text
NOT_EVALUATED
```

或继续评估后记录，但必须形成统一、稳定策略。

不得让字典顺序、订阅顺序或 Handler 顺序决定错误码。

---

# 十五、动态价格笼子边界

A 股连续竞价可能还存在依赖：

```text
最佳买价
最佳卖价
最新成交价
动态基准价格
```

的动态价格范围。

当前 Bar Backtest 如果没有正式 Quote/OrderBook Authority：

```text
不得伪造动态价格笼子。
```

不能使用：

```text
previous_close
bar.close
next_bar.open
```

冒充实时动态基准。

Decision 中应明确：

```text
dynamic_price_cage_status = NOT_EVALUATED
reason = REALTIME_QUOTE_AUTHORITY_UNAVAILABLE
```

PR2 只承诺：

```text
静态日涨跌幅申报规则
```

---

# 十六、Compiled Fingerprint

`OnlyCompiledMarketRuleIdentity` 的指纹必须覆盖：

```text
Profile ID
Profile Version
Trading Day
Runtime Mode
Instrument ID
Reference Fingerprint
Regime ID
Session Policy
Price Band Policy
Quantity Policy
Position Policy
```

必须保证：

```text
同一输入 → 同一 Fingerprint
不同 Reference → 不同 Fingerprint
不同 Profile Version → 不同 Fingerprint
不同 Trading Day 制度 → 不同 Fingerprint
```

不能只对 Raw Profile 做指纹。

---

# 十七、Checkpoint 与恢复

Decision 和 Compiled Policies 发生 Schema 变化后：

```text
直接升级 Checkpoint Schema Version
```

不兼容旧 Checkpoint。

恢复时必须验证：

```text
Reference Registry Fingerprint
Resolved Profile Fingerprint
Compiled Rules Fingerprint
Checkpoint Schema Version
```

以下变化必须拒绝恢复：

```text
Reference 改变
Profile Version 改变
价格制度改变
数量制度改变
Session 制度改变
规则执行顺序改变
```

错误必须明确：

```text
REFERENCE_FINGERPRINT_MISMATCH
PROFILE_FINGERPRINT_MISMATCH
COMPILED_RULES_FINGERPRINT_MISMATCH
CHECKPOINT_SCHEMA_UNSUPPORTED
```

不要为旧 Checkpoint 增加迁移兼容逻辑。

---

# 十八、Artifact

Artifact 中应输出结构化规则决策，例如：

```text
runtimes/<runtime_id>/market_rule_decisions.json
```

至少包含：

```text
instrument_id
trading_day
timestamp
side
quantity
price
accepted
reason_code
trading_phase
previous_close
tick_size
limit_rate
lower_limit
upper_limit
quantity_policy
reference_fingerprint
profile_version
compiled_rules_fingerprint
evaluations
```

要求：

1. 字段顺序稳定；
2. Decimal 使用字符串；
3. 空结果有稳定 Schema；
4. Artifact 有内容指纹；
5. 不能把不可序列化对象放进 `details`；
6. 不使用任意 Mapping 作为长期正式 Schema。

---

# 十九、与 Order 和 Risk 的边界

PR2 必须明确调用关系：

```text
Order Intent
→ Market Rule Decision
→ Risk Decision
→ Order Submission
```

或根据当前架构确定的正式顺序。

但必须满足：

```text
Market Rule 只判断市场制度合法性
Risk 只判断策略/账户风险
Order Service 只负责订单提交和副作用
```

禁止：

```text
Risk 重复执行市场规则
OrderService 重复执行涨跌停检查
Market Rule Engine 修改 Position
Market Rule Engine 创建 Reservation
Market Rule Engine 写 Order State
```

PR2 不实现 T+1 Bucket，但可以消费调用方提供的：

```text
unreserved_sellable_quantity
```

---

# 二十、明确非目标

本 PR 不实现：

```text
Execution Capability Matrix 扩展
A 股 Durable Transaction
ExecutionProcessor A 股 Projection
T+1 Pending/Available Bucket
T+1 次日成熟
Position Reservation 生命周期
最低佣金
佣金
印花税
过户费
Virtual Broker 涨跌停流动性
一字涨停/跌停撮合
开盘集合竞价撮合
收盘集合竞价撮合
动态价格笼子真实评估
实时 Order Book
真实 Broker
真实订单
Streaming Checkpoint
Paper Broker
```

如果实现过程中发现这些能力缺失，只定义清晰 Port 或输入边界，不得扩大范围。

---

# 二十一、测试原则

测试服务于正确架构，不是架构服务于旧测试。

对于历史测试：

```text
正确 → 保留或迁移
重复 → 删除
验证旧错误行为 → 删除
依赖旧接口 → 重写
依赖模糊错误码 → 更新
只为覆盖率存在 → 删除
```

不得为了让旧测试通过保留错误接口。

---

# 二十二、测试矩阵

## 22.1 唯一权威架构测试

验证：

```text
Runtime 只调用 OnlyMarketRuleEngine
不存在第二个独立 Pre-Trade Validator
Order/Risk 不重复实现 Session/Price/Quantity 规则
Strategy 不能直接访问规则内部对象
```

## 22.2 Profile 版本边界

```text
SSE_MAIN ST / 2026-07-05 → 5%
SSE_MAIN ST / 2026-07-06 → 10%

SZSE_MAIN ST / 2026-07-05 → 5%
SZSE_MAIN ST / 2026-07-06 → 10%
```

## 22.3 板块价格比例

```text
SSE_MAIN 普通 → 10%
SZSE_MAIN 普通 → 10%
CHINEXT 普通/ST → 20%
STAR 普通/ST → 20%
```

## 22.4 Tick 和价格边界

```text
正好涨停 → ACCEPT
高一个 Tick → PRICE_ABOVE_DAILY_LIMIT
正好跌停 → ACCEPT
低一个 Tick → PRICE_BELOW_DAILY_LIMIT
非 Tick 对齐 → PRICE_NOT_ALIGNED_TO_TICK
```

使用能够产生多位小数的 `previous_close` 验证舍入。

## 22.5 Session

```text
09:14:59 → MARKET_CLOSED
09:15:00 → TRADING_PHASE_NOT_SUPPORTED
09:30:00 → 继续检查
11:30:00 → MIDDAY_BREAK
13:00:00 → 继续检查
14:57:00 → TRADING_PHASE_NOT_SUPPORTED
15:00:00 → MARKET_CLOSED
```

## 22.6 停牌和状态

```text
suspended=true → INSTRUMENT_SUSPENDED
status!=ACTIVE → INSTRUMENT_INACTIVE
```

## 22.7 主板数量

```text
BUY 100 → ACCEPT
BUY 200 → ACCEPT
BUY 150 → BUY_QUANTITY_INCREMENT_INVALID
```

## 22.8 创业板数量

```text
BUY 100 → ACCEPT
BUY 200 → ACCEPT
BUY 150 → BUY_QUANTITY_INCREMENT_INVALID
```

## 22.9 科创板数量

```text
BUY 199 → BUY_QUANTITY_BELOW_MINIMUM
BUY 200 → ACCEPT
BUY 201 → ACCEPT
```

## 22.10 零股

可卖 250：

```text
SELL 100 → ACCEPT
SELL 200 → ACCEPT
SELL 50 → ODD_LOT_SELL_REQUIRES_FULL_LIQUIDATION
SELL 250 → ACCEPT
```

## 22.11 决策顺序

构造同时违反多个条件的订单，验证主错误码稳定。

## 22.12 Checkpoint

```text
capture
→ restore
→ Decision 完全一致
```

变更 Reference/Profile/Regime 后恢复必须失败。

## 22.13 确定性

同一输入运行至少 100 次，比较：

```text
Decision Payload
Evaluation 顺序
Reason Code
Compiled Fingerprint
Checkpoint Payload
Artifact Fingerprint
```

必须完全一致。

## 22.14 Generic Profile 回归

Generic T0 必须继续使用自身规则模型，但不要求保留旧接口。

如果统一模型发生改变，应迁移 Generic T0 到新模型，而不是增加 Legacy 分支。

---

# 二十三、配置与示例处理

所有现有配置和示例必须适配正确模型。

如果旧示例：

```text
依赖固定 10%
依赖简化 Session
依赖旧错误码
依赖旧 Decision DTO
```

直接更新或删除。

不得增加：

```text
legacy_mode: true
compatibility_mode: true
use_old_validator: true
```

测试 Fixture 也必须按新制度重建。

---

# 二十四、建议代码组织

具体组织以审计结果为准，建议职责如下：

```text
src/onlyalpha/market/models.py
    市场中立 DTO、Policy、Decision

src/onlyalpha/market/profiles.py
    版本化 Profile 定义

src/onlyalpha/market/ashare_rules.py
    A 股制度矩阵和纯编译逻辑

src/onlyalpha/market/runtime_rules.py
    唯一 Runtime Rule Engine

src/onlyalpha/reference/
    证券事实权威，不放交易制度逻辑

src/onlyalpha/order/
    消费 Decision，不复制规则

src/onlyalpha/risk/
    消费市场决策后的风险上下文，不复制市场规则
```

不要新增职责含糊的：

```text
manager.py
helper.py
utils.py
common.py
legacy.py
compat.py
```

新增组件名称必须能准确表达业务职责。

---

# 二十五、建议实施步骤

## Step 1：删除双重权威

```text
确认正式调用链
删除旧 Validator
迁移调用方
迁移或删除旧测试
增加架构门禁
```

## Step 2：重构编译模型

```text
新增 Compiled Price Policy
新增 Compiled Quantity Policy
新增结构化 Rule Evaluation
更新 Compiled Fingerprint
```

## Step 3：版本化制度

```text
截断旧 Profile
新增新 Profile Version
建立 A 股 Regime Matrix
```

## Step 4：价格规则

```text
Rate Resolution
Tick Rounding
Upper/Lower Limit
稳定错误码
```

## Step 5：数量规则

```text
主板
创业板
科创板
最低数量
递增单位
零股清仓
```

## Step 6：Session 和状态

```text
Opening Auction
Continuous
Midday
Closing Auction
Closed
Suspended
Inactive
```

## Step 7：Decision、Checkpoint、Artifact

```text
结构化序列化
Schema Version
恢复验证
Artifact 输出
```

## Step 8：全量测试和文档

```text
Conformance
Scenario
Recovery
Determinism
Architecture
```

---

# 二十六、文档要求

更新：

```text
README.md
AGENTS.md
docs/roadmap.md
docs/a_share_market_profile.md
docs/reference_data_authority.md
docs/market*.md
docs/testing.md
相关 ADR
```

建议新增 ADR：

```text
A-Share Pre-Trade Rule Decision Authority
```

ADR 必须说明：

1. 为什么只能有一个 Pre-Trade Authority；
2. 为什么 Reference 与交易制度分离；
3. 为什么 Profile 必须有生效版本；
4. 为什么最终 Policy 必须在 Compiler 阶段解析；
5. 为什么旧 Validator 被删除；
6. 为什么不兼容旧 Checkpoint；
7. 为什么动态价格笼子暂不评估；
8. 为什么集合竞价阶段被识别但不撮合。

---

# 二十七、质量门禁

至少运行：

```text
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha

uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py full
```

如涉及插件，运行对应 strict mypy。

最终运行：

```text
uv run python scripts/test_suite.py release
```

没有执行的外部测试必须标记：

```text
NOT EXECUTED
```

不能伪造 PASS。

---

# 二十八、验收标准

只有全部满足才算完成：

```text
[ ] OnlyMarketRuleEngine 是唯一正式 Pre-Trade 权威
[ ] 旧 Validator 和兼容 Wrapper 已删除
[ ] 不存在第二套 Session/Price/Quantity 业务规则
[ ] Profile 按生效日期版本化
[ ] 主板 ST 比例按制度日期正确变化
[ ] 创业板/科创板 ST 不被错误解析为 5%
[ ] 上下限完成正式 Tick 舍入
[ ] 上下限和 Tick 错误码明确区分
[ ] Session 区分 Opening/Continuous/Midday/Closing/Closed
[ ] 未支持集合竞价时返回明确 Unsupported
[ ] 停牌和 Inactive 错误码分离
[ ] 主板数量规则正确
[ ] 创业板数量规则正确
[ ] 科创板最低数量和递增单位正确
[ ] 零股只在合法全量清仓时允许
[ ] Context 中可卖数量语义明确
[ ] Decision 使用结构化 Evaluation
[ ] 规则执行顺序固定
[ ] Compiled Fingerprint 覆盖最终 Policy
[ ] Checkpoint Schema 已升级
[ ] 旧 Checkpoint 明确不兼容
[ ] Reference/Profile/Regime 变化后恢复 Fail Closed
[ ] Artifact 可完整解释拒绝原因
[ ] 100 次重放结果完全一致
[ ] Generic T0 已迁移到正确统一模型
[ ] 没有 Compatibility Mode
[ ] 没有 Legacy Adapter
[ ] 没有为了旧测试保留错误接口
[ ] 没有提前实现 PR3、PR4、PR5、PR6
```

---

# 二十九、最终结果现象

完成后，用户应观察到以下行为。

## 29.1 历史制度自动切换

同一只主板风险警示股票：

```text
2026-07-05
→ 使用旧制度
→ 价格比例 5%

2026-07-06
→ 使用新制度
→ 价格比例 10%
```

Strategy 无需包含日期判断。

## 29.2 决策可解释

提交高于涨停价的订单时，结果类似：

```text
accepted                  = false
reason_code               = PRICE_ABOVE_DAILY_LIMIT
profile_version           = 2026.07
previous_close            = 10.00
daily_limit_rate          = 0.10
upper_limit               = 11.00
submitted_price           = 11.01
tick_size                 = 0.01
reference_fingerprint     = ...
compiled_rules_fingerprint= ...
```

## 29.3 科创板数量正确

```text
BUY 199 → REJECT
BUY 200 → ACCEPT
BUY 201 → ACCEPT
```

不再被简单 `lot_size` 取模错误拒绝。

## 29.4 交易阶段准确

```text
14:58
→ CLOSING_AUCTION
→ TRADING_PHASE_NOT_SUPPORTED
```

而不是错误标为 Continuous 或 Closed。

## 29.5 停牌原因明确

```text
suspended=true
→ INSTRUMENT_SUSPENDED
```

不会再返回模糊的：

```text
INSTRUMENT_NOT_TRADABLE
```

## 29.6 恢复严格

相同 Reference 和 Profile：

```text
Checkpoint Restore → PASS
```

制度或 Reference 改变：

```text
Restore → FAIL CLOSED
```

不会使用不同规则继续运行。

---

# 三十、最终交付内容

完成后输出：

## 1. 原始问题审计

说明：

```text
双重权威
错误静态规则
错误 ST 规则
错误数量抽象
Session 缺口
Decision 缺口
```

## 2. 第一性原则决策

说明：

```text
唯一权威是谁
Reference 负责什么
Profile 负责什么
Compiler 负责什么
Rule Engine 负责什么
Order/Risk 不负责什么
```

## 3. 删除内容

明确列出：

```text
删除的类
删除的方法
删除的测试
删除的 Fixture
删除的兼容路径
```

## 4. 修改文件

逐文件说明职责和修改内容。

## 5. 完整数据流

```text
Order Request
→ Reference Resolution
→ Profile Resolution
→ Policy Compilation
→ Ordered Evaluation
→ Stable Decision
```

## 6. 制度矩阵

列出：

```text
Profile Version
Effective Range
Board
ST
Price Rate
Quantity Policy
Session Policy
```

## 7. 测试结果

分别列出：

```text
Static
Unit
Architecture
Integration
Conformance
Scenario
Recovery
Determinism
Full
Release
```

## 8. 未完成范围

明确列出：

```text
PR3：T+1 Settlement
PR4：Fee Closure
PR5：Durable Capability Integration
PR6：Virtual Broker and Matching
PR7：Recovery and Product Acceptance
```

---

# 三十一、最终原则

本任务不追求：

```text
少改代码
保留旧接口
让旧测试原样通过
让所有旧示例不变
```

本任务追求：

```text
只有一个权威
只有一条数据流
只有一套规则语义
每个边界职责明确
每个结果都能被解释
每次重放都完全一致
错误制度无法静默运行
```

当“历史兼容”和“正确架构”发生冲突时：

```text
选择正确架构。
```
