# Tushare 数据源

## 目的与职责

原生 Rust 库提供 Tushare 日线 HTTP 采集、证券元数据、真实交易日期、明确基准的动态复权，以及完整历史证券 Reference 映射。日线采用 `CALENDAR_PERIOD / DAY / 1 / SESSION_START`；不是 1440 分钟 Bar。`daily + adj_factor` 组合实现 `pro_bar` 的有效行为，不请求不存在的 `pro_bar` HTTP 端点，也不替换成静态复权产品。

## 边界与依赖

[http](src/http.rs) 使用已锁定 reqwest/rustls、tokio 和显式 Trust。生产固定 `https://api.tushare.pro`，不允许明文回退、重定向、代理发现、环境 token 或系统根证书发现。调用方必须先验证 Source grant、精确配置 revision、Credential generation 与 `INTEGRATION_SECRET/integration_id/token` Slot，之后从正式 Secret 显式传入；token 不属于公开配置、日志或证据。原始响应包含 token（包括 JSON 转义后）时拒绝返回，不修改原始证据。

Domain 提供冻结 Asia/Shanghai 时区、日历和金融值；CN A 股插件拥有 Reference 的规则边界。SHA-256 只用于完整 cache 输入身份；BigDecimal/BigInt 进行精确转换和有理数舍入。插件不拥有产品权限、存储、正式发布、券商、撮合或交易状态。

## 公开接口

- [daily_authoring](src/lib.rs) 保留原配置和 descriptor 身份；声明不能证明运行安装。
- [native_authoring、DailyFactory 和 history_identity](src/source.rs) 描述沪深上市股票数据源，每份配置选择 XSHG 或 XSHE。通过 HistoricalDays 的公开查询、逐项获取和纯回放接口返回原始响应、冻结日历、日线及复权依据。收盘完整性由正式历史存储验证。基金分类与北交所 Session 制度超出当前正式数据源的支持范围。
- [HttpTransport::new](src/http.rs) 接受显式 Secret 明文借用与 Trust，内部以 Zeroizing 持有，不实现 Debug/序列化。所有错误只暴露固定错误码；HTTP 权限错误和响应结构错误分别拒绝。`Table::decode` 保留 JSON 数字的十进制原文，检查重复字段、宽度和上限。
- [DailyClient / DailyRequest](src/daily.rs) 接受来源、Instrument、有限冻结 Calendar、半开 UTC 区间、Equity/ETF 和 `none/qfq/hfq`。所有公开异步操作从进入到 post、解码、归一化、Domain 构造、Cache 操作及最终成功出口共享同一个绝对预算；同步结果全部构造完成后再次采样单调时钟，预算耗尽不得返回成功。取消通过丢弃原 Future 传播。返回 canonical Bar 和精确 Query/响应证据，不代表已持久化或完整无缺口。发布前必须由产品的唯一 Recorder 持久化原始证据和对应事实。
- `DailyClient::calendar` 用 `trade_cal` 的每个日期冻结有限日历；调用方提供显式版本的开收盘 Session 模板。缺失、错误交易所、冲突日期拒绝。BSE 采用官方说明中的 SSE 交易日历。`securities` 返回 `SecuritiesResult`，保留完整原始 `evidence`，另以 `rows` 按请求交易所的 SH/SZ/BJ 明确筛选。股票结果标记 `ListedEquities`；`Asset::Etf` 的 `fund_basic(market=E)` 结果仅标记 `ListedFundCandidates`，包含 ETF、LOF 等场内基金候选，不能当作已确认的 ETF 分类或指定交易所 ETF 全集。当前证券名不能代替历史 ST/停牌事实。ETF 当前只支持原始日线。
- `Cache` 是显式注入的观察复用接口，保存完整原始响应包；不能直接写产品存储或建立第二套交易事实。`cache_only` 缺失直接失败且不创建网络请求；命中重放同一校验，不接受注入的 canonical 价格。同步 Cache 端口要求 Host 提供有界实现；本库不声称能抢占任意阻塞的 Cache 调用。
- [mapping::ashare_reference](src/mapping.rs) 必须输入已明确拼接的历史 ST、停牌、前收盘、有效区间及版本，输出 CN 插件的 `Reference`。不猜测、不从当前名字推导。

## 状态与生命周期

`DailyClient` 不维护订单或运行状态。Cache key 包含 source、完整 Instrument、Calendar、区间、复权类型、qfq 的 inclusive end_date anchor 与时间语义版本。qfq 使用请求 end_date 范围内最新因子，hfq 直接乘当日因子；缺少对应因子拒绝，不向前或向后猜补。复权价格最终按 SDK 两位小数以精确有理数半偶舍入；原始价格严格服从 Instrument precision。成交量手乘 100，成交额千元乘 1000，收盘事件时间取冻结日历最后 Session 结束，不接受未收盘或非交易日行。

相同重复行去重并计数，冲突重复拒绝；输出按交易日排序。开市区间的完全空响应不能证明合法空结果，明确拒绝。非空响应可能因停牌或上游缺失留有间隔，不声明覆盖完成。HTTP token、预算和接收过程不参与 canonical 价格事实。

旧 Python 实现仍在退役中；尚未闭合的正式产品装配阻止其成套删除。旧 wheel、Reference identity 与历史工件不能由新 Rust ELF 冒充。精确旧工件由原恢复边界保留。

## 使用与验证

独立固定向量和故障测试在 [native_daily.rs](tests/native_daily.rs)；配置身份测试在 [authoring.rs](tests/authoring.rs)。真实应用、数据库及公开 API 验证只能使用隔离 `onlyalpha-dev`。

正式日线输入使用独立的 `HistoricalDayRequest`，前复权要求显式的真实交易日并读取对应因子。请求的交易日和基准日须落在同一有效 CN 政策版本，跨版本查询需要分段。官方 HTTP 文档示例使用 HTTP；本实现为凭据安全强制 HTTPS，真实 TLS 服务、账户积分、权限和外部数据尚需专项取证；服务不支持安全 TLS 时不得降级。

参考：[HTTP 协议](https://tushare.pro/document/1?doc_id=130)、[通用行情](https://tushare.pro/document/1?doc_id=109)、[动态复权](https://tushare.pro/document/2?doc_id=146)、[日线单位](https://tushare.pro/document/2?doc_id=27)、[交易日历](https://tushare.pro/document/2?doc_id=26)、[上游 SDK](https://github.com/waditu/tushare/blob/master/tushare/pro/data_pro.py)。
