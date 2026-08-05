# China A-Share Cash Profile

`CN_A_SHARE_CASH@2025.1` 的有效区间是 `[2025-01-01, 2026-07-06)`，`CN_A_SHARE_CASH@2026.07`
自 `2026-07-06` 起生效。Registry 必须按订单 Trading Day 唯一解析版本；显式固定的版本超出有效区间同样 Fail Closed。

`OnlyMarketRuleEngine.evaluate_pre_trade()` 是唯一申报前规则入口。Reference 提供证券事实，Profile 提供生效制度，Compiler
将两者解析为不再含 board/ST 原始判断的 Session、价格带和数量 Policy；Rule Engine 只按固定顺序执行已编译 Policy。

`2025.1` 下主板普通 10%、风险警示 5%，创业板/科创板普通与风险警示均为 20%；`2026.07` 下主板普通与风险
警示均为 10%，创业板/科创板保持 20%。价格上下限以 RAW `previous_close` 和 `price_tick` 使用 Decimal
`ROUND_HALF_UP` 对齐。主板/创业板买入最低 100 且按 100 递增；科创板最低 200 且按 1 递增；卖出零股仅允许一次性
卖出全部未预留可卖数量。

Session 明确区分 `OPENING_AUCTION`、`CONTINUOUS`、`MIDDAY_BREAK`、`CLOSING_AUCTION` 与 `CLOSED`。
当前集合竞价可识别但不撮合，申报返回 `TRADING_PHASE_NOT_SUPPORTED`。动态价格笼子因没有 Quote/OrderBook Authority，
Decision 明确记录 `NOT_EVALUATED / REALTIME_QUOTE_AUTHORITY_UNAVAILABLE`。

未完整覆盖：新股初期、退市整理、北交所、可转债、融资融券、集合竞价撮合、盘中临停及全部历史税费版本。

Reference 输入现在只接受按交易日解析的版本化 A 股权威记录。`previous_close` 是 RAW 规则基准，不从上一根
Bar 推导；Reference 缺失、区间重叠或字段未知均 Fail Closed。参见 `reference_data_authority.md`。
