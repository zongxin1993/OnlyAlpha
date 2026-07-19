# China A-Share Cash Profile

`CN_A_SHARE_CASH@2025.1` 正式表达 Long-only、禁止裸卖空、证券 T+1 可卖、现金账户、午休、停牌引用、买入整手、
零股仅清仓、最低佣金、卖出印花税、过户费、Bar 10% participation 和 Next-Bar Open。

涨跌幅由 Reference 的 board/ST 解析：主板 10%、ST/*ST 5%、创业板 20%、科创板 20%。未知 board 在 strict 模式明确返回
`UNSUPPORTED_CN_A_SHARE_BOARD`，不按代码前缀猜测。

未完整覆盖：新股初期、退市整理、北交所、可转债、融资融券、集合竞价细节、盘中临停及全部历史税费版本。

