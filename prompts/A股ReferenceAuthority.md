# PR1：CN A-Share Versioned Reference Authority

请认真阅读并修改 OnlyAlpha 工程：

```text
https://github.com/zongxin1993/OnlyAlpha
```

本任务名称：

```text
PR1：A 股 Reference Authority
CN A-Share Versioned Reference Data Authority
```

---

## 一、任务目标

为 OnlyAlpha 建立正式、版本化、可审计、可恢复、Fail Closed 的 A 股参考数据权威，为后续：

```text
A 股价格限制
停牌规则
交易单位
零股清仓
T+1
费用
Durable Execution
```

提供唯一、稳定的输入来源。

本任务只解决：

```text
某只证券在某个交易日应使用哪一份参考数据
```

不解决：

```text
订单是否最终成交
成交如何记账
T+1 如何结算
费用如何累计
```

最终应形成：

```text
Instrument
+
Trading Day
+
Reference Data Version
        ↓
Resolved A-Share Reference Snapshot
        ↓
Market Rule Compiler / Rule Engine
```

任何 A 股规则不得再依赖：

* 证券代码前缀猜测；
* 当前时刻的 ST 状态；
* 未版本化的自由字典；
* 缺失字段的隐式默认值；
* DataSource 私有对象；
* Strategy 自定义判断。

---

## 二、当前背景

OnlyAlpha 当前已经存在：

```text
CN_A_SHARE_CASH@2025.1
OnlyMarketRuleEngine
OnlyMarketRuleCompiler
Instrument Reference
board
st_status
交易日历
A 股 Golden Dataset
Tushare / MiniQMT DataSource
```

但当前 Reference Data 仍没有形成完整产品权威：

1. `board`、`st_status` 等字段可能来自配置中的普通 Mapping；
2. 缺少统一的版本化生效区间模型；
3. 缺少正式的停牌状态权威；
4. 缺少昨日收盘价或价格限制基准的正式来源；
5. 缺少冲突版本检测；
6. 缺少“某交易日到底使用哪一条记录”的唯一解析服务；
7. 缺少跨 DataSource 的统一标准化结果；
8. 缺少完整 Artifact、Fingerprint、Checkpoint 和 Scenario 诊断；
9. 当前规则如果参考数据不完整，部分路径可能使用默认值继续运行。

本 PR 必须把这些问题收口，但不能顺带改造整个市场规则、成交或账务系统。

---

## 三、开始修改前必须完成的审计

修改前必须阅读当前 `master` 的实际代码和测试，不得仅按本提示词机械实施。

至少阅读：

```text
AGENTS.md
README.md
docs/roadmap.md
相关 Market / Reference Data ADR

src/onlyalpha/domain/instrument.py
src/onlyalpha/domain/time.py
src/onlyalpha/domain/identifiers.py

src/onlyalpha/market/profiles.py
src/onlyalpha/market/registry.py
src/onlyalpha/market/runtime_rules.py
src/onlyalpha/market/models.py
src/onlyalpha/market/session_clock.py

src/onlyalpha/config/
src/onlyalpha/runtime/backtest/factory.py
src/onlyalpha/runtime/paper/factory.py

src/onlyalpha/data/
src/onlyalpha/cache/historical/
src/onlyalpha/scenario/

packages/provider/onlyalpha-plugin-tushare/
packages/provider/onlyalpha-plugin-miniqmt/

tests/market/
tests/config/
tests/scenario/
tests/conformance/
tests/fixtures/miniqmt/
```

全仓库搜索：

```text
board
st_status
suspended
suspension
previous_close
pre_close
reference
reference_data
instrument_attributes
price_limit
lot_size
effective_from
effective_to
data_version
```

实施前先输出简短审计结论，明确回答：

1. 当前 A 股参考字段分别从哪里进入系统；
2. 当前真正的数据权威是谁；
3. 哪些地方直接读取普通 Mapping；
4. 哪些地方根据代码或默认值推断规则；
5. 当前是否存在重复的 Reference Model；
6. 配置、DataSource、Runtime Factory 和 Rule Engine 之间的数据流；
7. 当前 Golden Dataset 能提供哪些字段，缺少哪些字段；
8. 是否涉及现有序列化或持久化 Schema；
9. 最小兼容改造范围是什么。

---

## 四、范围冻结

### 4.1 本 PR 必须支持的字段

第一阶段的正式 A 股 Reference Snapshot 至少包含：

```text
instrument_id
exchange
security_type
board
lot_size
price_tick
st_status
suspended
previous_close
effective_from
effective_to
source
source_version
data_version
record_fingerprint
```

字段语义：

### `instrument_id`

使用 OnlyAlpha 强类型 `OnlyInstrumentId`。

### `exchange`

至少支持当前 A 股验收范围内的：

```text
SSE
SZSE
```

不能根据证券代码自动猜测后再把猜测当作正式权威。

### `security_type`

第一阶段至少区分：

```text
COMMON_STOCK
```

其他证券类型必须显式 Unsupported 或 Fail Closed。

### `board`

第一阶段至少支持：

```text
SSE_MAIN
SZSE_MAIN
CHINEXT
STAR
```

可以兼容现有 `MAIN` 等别名，但进入权威模型前必须标准化为一个 canonical value。

### `lot_size`

第一阶段普通股票通常为 100，但不能把 100 写死在 Order 或 Risk 中。

### `price_tick`

第一阶段通常为 `0.01`，但仍必须来自版本化 Reference 或正式 Profile Resolution。

### `st_status`

必须是该生效区间内的历史状态，不能使用当前状态回填过去。

### `suspended`

表示该证券在对应生效区间是否停牌。

如果只能获得按交易日停牌信息，则允许一条记录只覆盖一个交易日。

### `previous_close`

表示当前交易日用于价格限制计算的正式基准价格。

必须使用精确 Decimal 或 OnlyAlpha 现有价格值对象。

不得使用浮点数。

### `effective_from` / `effective_to`

必须明确记录生效边界。

建议使用：

```text
effective_from：包含
effective_to  ：不包含，或明确为包含
```

选择哪种语义必须写入模型文档和测试，并全项目一致。

### `source`

例如：

```text
CONFIG
MINIQMT
TUSHARE
GOLDEN_DATASET
SCENARIO
```

建议使用稳定枚举或受控字符串。

### `source_version` / `data_version`

必须可以证明数据来源版本。

### `record_fingerprint`

对 canonical 序列化内容计算稳定哈希，用于审计和结果指纹。

---

## 五、明确非目标

本 PR 不实现：

```text
A 股 Durable Execution 接线
修改 Execution Capability Matrix
T+1 Settlement
可卖数量 Bucket
现金或持仓 Reservation 改造
佣金、最低佣金、印花税、过户费
涨跌停订单拒绝
涨跌停流动性撮合
Virtual Broker A 股成交限制
实时 Gap Recovery
Streaming Checkpoint
Paper Broker
真实订单
完整公司行为处理
复权价格计算
集合竞价
北交所
可转债
ETF 特殊申赎
新股特殊阶段
退市整理
融资融券
```

可以增加 Reference 字段和解析能力，但不能在本 PR 中改变正式交易产品支持范围。

---

## 六、领域模型设计

建议建立清晰的不可变领域模型，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyAshareInstrumentReference:
    instrument_id: OnlyInstrumentId
    exchange: OnlyExchange
    security_type: OnlyAshareSecurityType
    board: OnlyAshareBoard
    lot_size: OnlyQuantity
    price_tick: OnlyPriceIncrement
    st_status: bool
    suspended: bool
    previous_close: OnlyPrice
    effective_from: OnlyTradingDay
    effective_to: OnlyTradingDay | None
    source: OnlyReferenceDataSource
    source_version: str
    data_version: OnlyDataVersion
    record_fingerprint: str
```

具体命名必须服从当前工程风格。

所有新增正式类使用 `Only` 前缀。

模型要求：

1. 不可变；
2. 可无损序列化；
3. 不接受 naive datetime；
4. 不接受 float；
5. 构造时完成字段校验；
6. `lot_size > 0`；
7. `price_tick > 0`；
8. `previous_close > 0`；
9. 生效区间合法；
10. Fingerprint 可重复；
11. 字段顺序和 JSON 表达稳定；
12. 不保存 DataSource SDK 原始对象。

---

## 七、Registry 与 Query Authority

需要建立唯一 Reference Authority。

建议职责拆分为：

```text
OnlyAshareReferenceRegistry
OnlyAshareReferenceQuery
OnlyAshareReferenceSnapshot
OnlyAshareReferenceResolution
```

或符合当前架构的等价实现。

### 7.1 Registry

负责：

```text
注册版本化 Reference Record
校验重复
校验区间重叠
校验冲突
按 Instrument 建立索引
生成 Registry Fingerprint
```

必须拒绝：

```text
同一 Instrument 生效区间重叠
同一日期存在两条不同内容记录
相同 Source Version 对应不同内容
相同 Fingerprint 对应不一致 Payload
effective_to 早于 effective_from
```

完全相同的幂等重复可以允许，但行为必须明确并测试。

### 7.2 Query

正式查询接口建议为：

```python
resolve(
    instrument_id: OnlyInstrumentId,
    trading_day: OnlyTradingDay,
) -> OnlyAshareReferenceResolution
```

解析结果必须明确区分：

```text
RESOLVED
NOT_FOUND
AMBIGUOUS
UNSUPPORTED_SECURITY_TYPE
UNSUPPORTED_EXCHANGE
INVALID_REFERENCE
```

不要用裸 `None` 表达所有失败原因。

### 7.3 唯一性

Market Rule Compiler 和 Runtime 不得各自重复解析 Reference。

正式链路必须为：

```text
Reference Registry
→ Reference Query
→ Resolved Snapshot
→ Market Rule Engine
```

---

## 八、Fail Closed 规则

以下情况必须 Fail Closed：

```text
Instrument 没有 Reference Record
交易日无生效记录
生效区间冲突
board 缺失或未知
exchange 不支持
security_type 不支持
lot_size 缺失
price_tick 缺失
st_status 未知
suspended 未知
previous_close 缺失
previous_close 非正数
data_version 缺失
source_version 缺失
Fingerprint 校验失败
```

禁止以下默认行为：

```python
board = raw.get("board", "MAIN")
st_status = bool(raw.get("st_status", False))
suspended = bool(raw.get("suspended", False))
lot_size = raw.get("lot_size", 100)
price_tick = raw.get("price_tick", "0.01")
```

如果为了旧配置兼容暂时允许部分默认值，必须满足：

1. 默认值只在明确 Legacy Adapter 中出现；
2. 输出显式兼容性诊断；
3. 不允许进入正式 `CN_A_SHARE_CASH` 产品验收；
4. 有明确移除计划；
5. 不允许 Runtime Rule Engine 静默使用。

优先选择直接 Fail Closed。

---

## 九、配置模型改造

当前配置中的 `reference_data.instrument_attributes` 如果仍是普通 Mapping，需要逐步替换或增加正式 Schema。

建议支持显式配置：

```yaml
reference_data:
  ashare_instruments:
    - instrument_id: 600000.XSHG
      exchange: SSE
      security_type: COMMON_STOCK
      board: SSE_MAIN
      lot_size: 100
      price_tick: "0.01"
      st_status: false
      suspended: false
      previous_close: "10.00"
      effective_from: "2025-01-02"
      effective_to: "2025-01-03"
      source: CONFIG
      source_version: "scenario-v1"
      data_version: "cn-a-share-reference-v1"
```

要求：

1. Decimal 字段使用字符串；
2. 日期采用稳定 ISO 格式；
3. 未知字段根据当前配置策略处理；
4. 配置归一化后顺序稳定；
5. Configuration Fingerprint 包含 Reference 内容；
6. 多 Cluster 共享相同 Reference 时不能产生不同 Fingerprint；
7. 同一 Runtime 的冲突 Reference 必须在 `validate()` 阶段失败；
8. `--dry-run` 能发现 Reference 缺失或冲突。

不要让错误推迟到第一笔订单提交时才发现。

---

## 十、DataSource 与 Adapter 边界

Tushare、MiniQMT、Scenario 和 Config 可以提供原始 Reference，但必须转换为统一领域模型。

正式边界建议为：

```text
Provider Raw Shape
→ Provider Adapter
→ Canonical Reference Record
→ Registry
```

不得：

```text
Market Rule Engine 直接读取 xtquant 字典
Runtime 直接读取 Tushare DataFrame
Strategy 直接读取 DataSource Reference
```

### 10.1 MiniQMT

审计真实 MiniQMT 当前能稳定提供哪些字段。

不能确认的字段不得伪造。

如果当前真实 API 无法提供历史 `board/st_status/suspended/previous_close` 的完整版本，则：

* 离线 Golden Dataset 可以提供冻结 Reference；
* 真实 MiniQMT Gate 明确标记能力缺口；
* 不得用当前状态回填历史；
* 不得扩大真实验收声明。

### 10.2 Tushare

审计当前插件是否能获得：

```text
基础证券信息
ST 状态
停牌状态
前收盘价
生效日期
```

网络数据采集不进入普通离线测试。

Provider 测试使用冻结 Fixture。

### 10.3 Scenario

Scenario DataSource 必须能够精确提供 Reference Record，用于离线产品验收。

---

## 十一、Previous Close 权威

`previous_close` 是本 PR 中最容易设计错误的字段，需要明确以下语义。

### 11.1 Reference Previous Close

表示当前交易日正式规则计算使用的前收盘基准。

不能简单取：

```text
上一条 Bar.close
```

因为：

* 上一条数据可能缺失；
* 可能存在停牌；
* 可能存在公司行为；
* 数据源 Bar 与正式前收盘字段可能不同；
* 回测区间可能从中间日期开始。

### 11.2 数据一致性

如果行情数据和 Reference `previous_close` 同时存在，可增加一致性校验：

```text
一致
可接受误差
冲突
```

冲突时应 Fail Closed 或形成明确数据质量错误。

本 PR 不负责公司行为和复权，但必须避免把复权 Bar 的 close 当成未复权涨跌停基准。

### 11.3 Adjustment Type

对于 A 股正式 Rule Reference：

```text
previous_close
```

必须与 `RAW` 价格语义兼容。

如果 Runtime 使用复权 Bar，而规则仍需要未复权价格，必须在配置或校验阶段拒绝，除非已有明确双价格域设计。

---

## 十二、Artifact 与审计

需要把 Reference Authority 纳入正式审计输出。

至少提供：

```text
reference_registry_fingerprint
resolved_reference_count
reference_source_versions
instrument_id
trading_day
record_fingerprint
board
st_status
suspended
previous_close
lot_size
price_tick
resolution_status
failure_code
```

但不要把大量重复 Reference 内容直接复制到每个 Fill。

建议：

```text
Result/Manifest 保存 Registry Fingerprint
交易事实保存使用的 Record Fingerprint
Artifact 单独保存 Reference Snapshot 表
```

参考数据 Artifact 建议使用稳定 JSON 和/或 Parquet Schema。

零记录时也必须有稳定 Schema。

---

## 十三、Checkpoint 与恢复

本 PR 不新增 Streaming Recovery，但 Backtest Checkpoint 必须考虑 Reference Authority。

如果 Reference Registry 是启动后不可变的配置权威，建议：

```text
Checkpoint 保存 Registry Fingerprint
恢复时重新从配置/DataSource 构建 Registry
校验 Fingerprint 完全一致
```

不要把整套不可变 Reference 重复写入每个 Checkpoint，除非当前 Persistence 架构要求。

恢复要求：

```text
配置 A 建立 checkpoint
配置 B 使用不同 Reference
尝试恢复
→ Fail Closed
```

需要覆盖：

```text
board 改变
st_status 改变
suspended 改变
previous_close 改变
source_version 改变
data_version 改变
effective range 改变
```

任何一项变化都应导致不兼容 Fingerprint。

---

## 十四、Runtime Factory 接线

Backtest 和 Paper Factory 不应继续手工从普通 Mapping 中读取：

```text
board
st_status
```

建议统一改为：

```text
Reference Authority Resolution
→ only_instrument_reference(...)
```

或让 `only_instrument_reference` 本身接收正式 Snapshot，而不是松散参数。

目标链路：

```text
OnlyRuntimeAssemblyPlan
→ Build Reference Registry
→ Validate Required Reference Coverage
→ Bind Reference Query to Market Rule Engine
```

要求：

1. Backtest 启动前验证覆盖完整；
2. Paper Historical Bootstrap 启动前验证覆盖；
3. 缺失 Reference 时 Runtime Assembly 失败；
4. 多 Cluster 共享同一 Runtime 时只建立一套 Registry；
5. 兼容性分组必须考虑 Reference Fingerprint；
6. 两个 Cluster 对同一 Instrument 使用不同 Reference 时不能错误共享 Runtime。

---

## 十五、Runtime Compatibility Key

审计 `OnlyRuntimeCompatibilityKey` 当前是否包含足够的 Reference 身份。

如果没有，需要加入：

```text
reference_registry_fingerprint
```

或等价稳定标识。

必须防止：

```text
Cluster A:
600000.XSHG, ST=false

Cluster B:
600000.XSHG, ST=true

Planner 错误地把两者放入同一 Runtime
```

冲突配置应：

* 在 Planner/Validation 阶段拒绝；
* 或形成不同 Runtime；
* 不能在运行中出现“后注册覆盖前注册”。

优先选择同一 Engine 内对同一 Instrument/Trading Day 的冲突 Reference 直接拒绝。

---

## 十六、测试要求

### 16.1 Domain 单元测试

覆盖：

```text
合法构造
不可变
Decimal 精度
禁止 float
lot_size 非正拒绝
price_tick 非正拒绝
previous_close 非正拒绝
非法 effective range
稳定序列化
稳定 fingerprint
```

### 16.2 Registry 测试

覆盖：

```text
单条注册
多 Instrument
多生效区间
相邻区间
区间重叠
完全相同幂等重复
内容冲突重复
按日期精确解析
无记录
区间边界
稳定 Registry Fingerprint
注册顺序无关
```

### 16.3 Config 测试

覆盖：

```text
YAML/JSON 加载
Decimal 字符串
未知 board
缺失字段
冲突记录
标准化 Payload
Config Fingerprint
--dry-run 错误
```

### 16.4 Runtime Planning 测试

覆盖：

```text
相同 Reference 的 Cluster 可共享 Runtime
不同 Reference 不得错误共享
缺失 Reference 装配失败
多 Cluster 冲突 Fail Closed
```

### 16.5 Rule Engine 集成测试

本 PR 不实现完整交易拒绝，但需要证明：

```text
Market Rule Engine 获得正式 Resolved Snapshot
不再读取自由 Mapping
Record Fingerprint 能进入 Rule Diagnostic
```

### 16.6 Provider Contract 测试

MiniQMT/Tushare 使用冻结输入测试：

```text
Provider Raw
→ Canonical Reference
→ Registry
```

不得访问真实网络或导入真实 xtquant。

### 16.7 Scenario 测试

建立最小离线 Reference Scenario：

```text
主板普通股票
ST 股票
创业板股票
科创板股票
停牌股票
缺失 Reference
冲突 Reference
```

本 PR 只断言 Reference Resolution，不要求 A 股订单进入 Durable Transaction。

### 16.8 Recovery 测试

覆盖：

```text
相同 Reference Fingerprint 恢复成功
Reference 内容变化恢复失败
Reference 注册顺序变化但内容相同恢复成功
```

### 16.9 Determinism

至少执行多次重复构建，断言：

```text
Record Fingerprint 一致
Registry Fingerprint 一致
Runtime Compatibility Key 一致
Artifact 内容一致
```

---

## 十七、Golden Dataset

扩展或新增冻结 A 股 Reference Dataset。

建议目录：

```text
tests/fixtures/reference/cn_a_share_v1/
```

或符合现有 Fixture 结构的等价目录。

至少包含：

```text
普通主板股票
ST 股票
创业板股票
科创板股票
停牌交易日
前收盘价
生效区间
数据来源信息
文件指纹
Manifest
```

要求：

1. Fixture 只读；
2. Manifest 记录文件 SHA；
3. 测试加载前校验完整性；
4. 不依赖当前日期；
5. 不依赖网络；
6. 不使用当前 ST 状态；
7. 明确 Fixture 不覆盖的产品范围。

如果扩展现有 MiniQMT Golden Dataset，需要避免把行情数据与 Reference 权威混成一个无版本文件。

---

## 十八、错误码

建议形成稳定 Reference 错误码：

```text
REFERENCE_NOT_FOUND
REFERENCE_AMBIGUOUS
REFERENCE_EFFECTIVE_RANGE_INVALID
REFERENCE_EFFECTIVE_RANGE_OVERLAP
REFERENCE_BOARD_MISSING
REFERENCE_BOARD_UNSUPPORTED
REFERENCE_EXCHANGE_UNSUPPORTED
REFERENCE_SECURITY_TYPE_UNSUPPORTED
REFERENCE_LOT_SIZE_INVALID
REFERENCE_PRICE_TICK_INVALID
REFERENCE_ST_STATUS_UNKNOWN
REFERENCE_SUSPENSION_STATUS_UNKNOWN
REFERENCE_PREVIOUS_CLOSE_MISSING
REFERENCE_PREVIOUS_CLOSE_INVALID
REFERENCE_DATA_VERSION_MISSING
REFERENCE_SOURCE_VERSION_MISSING
REFERENCE_FINGERPRINT_MISMATCH
REFERENCE_RUNTIME_CONFLICT
REFERENCE_ADJUSTMENT_SEMANTICS_CONFLICT
```

错误码必须进入：

```text
Validation Result
Runtime Assembly failure
Scenario Assertion
Diagnostic Artifact
```

不要只返回模糊的：

```text
invalid reference data
```

---

## 十九、架构门禁

增加架构测试，禁止以下模式：

```text
通过证券代码 startswith 判断板块
Runtime Factory 直接读取 instrument_attributes["board"]
Runtime Factory 直接读取 instrument_attributes["st_status"]
Rule Engine 使用默认 board
Rule Engine 默认 st_status=False
Rule Engine 默认 suspended=False
A 股价格规则使用 float
Strategy 读取 Reference Registry
Provider SDK 类型泄漏进入 Core
```

允许的 Legacy Adapter 必须有明确白名单和移除说明。

---

## 二十、文档要求

更新：

```text
README.md
AGENTS.md
docs/roadmap.md
docs/market*.md
docs/reference*.md
必要的 ADR
```

建议新增 ADR：

```text
ADR：Versioned A-Share Reference Data Authority
```

ADR 至少说明：

```text
为什么不能使用代码前缀
为什么必须版本化
为什么 previous_close 不是上一根 Bar.close
为什么缺失数据必须 Fail Closed
Registry/Query 谁是唯一权威
如何参与 Runtime Compatibility
如何参与 Checkpoint Fingerprint
```

README 中不要提前宣称 A 股 Durable Backtest 已完成。

准确描述应类似：

```text
A 股版本化 Reference Authority 已完成；
A 股 Durable Execution、T+1、费用和撮合闭环仍在后续 PR 中完成。
```

---

## 二十一、兼容性要求

优先保持现有 Generic T0 Backtest 行为不变。

必须确认：

```text
GENERIC_T0_CASH 场景不回归
现有 Synthetic Backtest 不被强制要求 A 股 Reference
非 CN_A_SHARE_CASH Profile 不读取 A 股专用字段
Paper MiniQMT 当前只读流程不被破坏
```

A 股 Reference Authority 只能在：

```text
CN_A_SHARE_CASH
```

或明确要求该 Reference 的场景下成为必需。

---

## 二十二、建议修改文件范围

具体以审计结果为准，可能涉及：

```text
src/onlyalpha/reference/
src/onlyalpha/market/reference.py
src/onlyalpha/market/runtime_rules.py
src/onlyalpha/config/
src/onlyalpha/runtime/planning.py
src/onlyalpha/runtime/backtest/factory.py
src/onlyalpha/runtime/paper/factory.py
src/onlyalpha/scenario/
src/onlyalpha/artifact/
packages/provider/onlyalpha-plugin-tushare/
packages/provider/onlyalpha-plugin-miniqmt/
tests/
docs/
```

不要为了本任务新增多个职责重叠的 Manager。

---

## 二十三、质量检查

至少运行：

```text
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha

uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py miniqmt-contract
```

如修改 Provider 插件，运行对应插件 strict mypy。

发布前运行：

```text
uv run python scripts/test_suite.py release
```

没有执行的外部测试必须标记：

```text
NOT EXECUTED
```

不能写成 PASS。

---

## 二十四、验收标准

只有全部满足才算完成：

```text
[ ] 存在正式不可变 A 股 Reference Record
[ ] Reference Record 有明确版本和生效区间
[ ] 存在唯一 Registry/Query Authority
[ ] 可以按 Instrument + Trading Day 精确解析
[ ] 重叠和冲突记录 Fail Closed
[ ] board 不再通过代码前缀推断
[ ] st_status 不再使用当前状态回填历史
[ ] suspended 状态不可缺省为 false
[ ] previous_close 有正式语义和来源
[ ] Decimal 字段不使用 float
[ ] Registry Fingerprint 稳定且与注册顺序无关
[ ] Runtime Compatibility 考虑 Reference Identity
[ ] Backtest/Paper Factory 不再直接读取松散 A 股字段
[ ] 缺失 Reference 在 validate/assembly 阶段失败
[ ] Reference Artifact 可审计
[ ] Checkpoint 恢复验证 Reference Fingerprint
[ ] Golden Dataset 完全离线
[ ] Generic T0 Backtest 无回归
[ ] 不修改 Durable Execution Capability
[ ] 不提前实现 T+1、费用和 A 股撮合
[ ] 文档没有过度声明
```

---

## 二十五、最终目标结果

完成后，系统应能稳定回答：

```text
对于 600000.XSHG，在 2025-01-03：
使用哪一个交易所？
属于哪个板块？
是否 ST？
是否停牌？
交易单位是多少？
最小价格变动是多少？
正式前收盘价是多少？
这份信息来自哪里？
哪个版本？
在哪个时间区间生效？
内容指纹是什么？
```

结果必须唯一、可审计、可重复。

标准链路为：

```text
OnlyClusterRunConfig
→ Reference Record Normalization
→ Reference Registry
→ Reference Query
→ Resolved Snapshot
→ Market Rule Engine
```

完成本 PR 后，OnlyAlpha 可以准确声明：

> 已建立 `CN_A_SHARE_CASH` 的版本化 Reference Data Authority，支持板块、ST、停牌、交易单位、价格精度和前收盘价按交易日精确解析，并参与配置校验、Runtime 兼容性、审计和恢复指纹。

仍不能声明：

> A 股 Durable Execution 已完成。

---

## 二十六、最终交付说明

完成后请输出：

### 1. 当前问题审计

说明旧 Reference 数据流和重复权威。

### 2. 架构决策

说明：

```text
Record
Registry
Query
Resolution
Fingerprint
Fail Closed
Runtime Compatibility
Checkpoint Validation
```

### 3. 修改文件

逐文件说明职责和修改内容。

### 4. 数据流

提供完整时序：

```text
Config/Provider
→ Adapter
→ Canonical Record
→ Registry
→ Query
→ Resolved Snapshot
→ Rule Engine
```

### 5. 兼容性

说明 Generic T0、Paper、MiniQMT、Tushare 是否受影响。

### 6. 测试结果

分别列出：

```text
Unit
Contract
Architecture
Integration
A-share
Recovery
MiniQMT Contract
Ruff
Mypy
Release
```

### 7. 未完成事项

明确列出后续 PR：

```text
PR2：A 股 Rule Decision
PR3：A 股 T+1 Settlement
PR4：A 股 Fee Closure
PR5：A 股 Durable Capability 接线
PR6：Virtual Broker 与 Scenario Pack
PR7：Recovery 与 Product Acceptance
```
