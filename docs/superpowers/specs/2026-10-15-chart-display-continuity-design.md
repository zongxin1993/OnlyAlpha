# 图表显示与指标连续性

## 产品目标与行为

用户在真实工作台上叠加 SMA20/SMA10 后，可以拖动、缩放、切换代码或原生周期，保留显示实例和参数，并看到当前上下文的新结果。图表以正式 Product API 为入口，Web 只显示、管理配置、提交请求。

- 切换周期/代码保留实例身份、参数、颜色、显隐和位置，立即撤下旧数值，再验证新上下文和计算。所有现有 Provider-native 周期须从正式能力/目录证明支持，不依赖 Web 品牌/代码/15m 白名单。
- 同一根 Preview 更新不漂移；新柱在跟随最新行情时推进，历史回看不被拉回。拖动/缩放/样式变化不触发 Study 重算或清空有效曲线。输入仍是最近最多2000根完整证明的 closed Bars；视口超出计算范围明确提示无指标数据，不伪造延长线。
- 两个 SMA 使用独立实例，保留各自完整结果；单个计算失败隔离、可见原因及重试。共享权限或输入证明失效仍撤下相关全部值。浏览器取消不能当作服务端容量已释放的证明。
- SMA 的 PRICE 输出与 K 线共用主图价格轴。不同单位和未知单位默认独立副图/纵轴；单位来自正式已准入输出，不能凭名称猜测，不归一化数值。本轮不增加新的 Indicator/Factor 数值实现。
- 成交量逐柱复用对应 K 线的红涨绿跌规则，平盘复用现有蜡烛规则。显示颜色不改变 OHLCV；Preview 与 closed 使用相同显示规则。
- 右下角显示时区选择，首次默认UTC，提供UTC、北京时间Asia/Shanghai、浏览器本地时区。只改变轴刻度和轴上的十字线时间文字，原始UTC、bar identity、边界、价格、指标、查询参数、Calendar均不变。选择只保存在当前浏览器，存储异常仍可正常使用；观察栏继续明确标记UTC。
- 显示接收延迟：OnlyAlpha入口接收时刻减真实交易所事件时刻。显示最近收盘到达延迟：收到该收盘事件的入口时刻减该K线的UTC结束边界。两者分别命名、单位ms，不能互相替代。
- 延迟依赖同一次、同源/标的/周期、当前stream incarnation的真实时序观察。缺字段/缺Provider时间证明/历史重播无实时观察时显示—；负值保留符号并提示时钟偏差，不clamp为0。断开时标为最后样本/非当前，不把浏览器Date.now或canonical ts_init冒充入口时间。

## 边界与缺口

当前工程已有原生周期准入与实例连续性实现可复用，但未部署的草稿不是当前产品事实。优先复用已经提交的相关实现，逐项验证当前组合；不导入旧工作树未提交的偏好恢复/短历史变更，也不执行此前被审批拒绝的Source Revision补丁。

Provider事件时刻与入口接收时刻已有raw evidence，当前Product stream没有提供它们。补充最小正式实时观察投影，语义是显示遥测，不是新的Bar/Research/交易Authority。Provider字段解释停留在插件边界，Core只承载通用明确时序观察。禁止从canonical Bar ts_event/ts_init、bar_start、clamped receive或共享时间戳推断真实入口观察；衍生链路无直接对应观察时保留不可用。

坚持现有renderer(ADR0094)、完整Source/Revision/环境/目录/native/calendar/closed coverage证明、Decimal/ns原值、唯一ledger和immutable inputs。任何新增wire字段同步DTO、schema、generated消费者和compatibility检测；不修改persisted事实格式、identity、WAL、migration、质量规则或Compose拓扑。Constitution Impact: NO。

## 验收路径

真实UI：BTC15m→SMA20和SMA10→拖动/缩放→显隐/改色→1m→15m；两实例/参数保留，新周期查询和曲线可见，旧回复不能挂接。真实量柱红绿，三个时区仅转换轴文字，两项延迟有明确状态。

确定性测试：native多周期、A→B→A/focus/grant/late reply/capacity、兄弟失败隔离、closed/preview/older paging、2000窗口、独立纵轴、同柱与新柱、正/零/负/缺失时间、无Provider时间fallback、错误上下文/重播/derived、跨日/DST本地格式及存储异常。所有正式本地验证通过唯一dev_verification/Compose，单worker串行，真实UI与controlled技术证据分开。

## 外部工程参考

- Binance官方WebSocket文档：https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md — E、t、T分别为事件、开始、收盘时间，UTC Unix；将时间语义差异变为回归，不能把bar_start作传输延迟基准。
- Lightweight Charts issue2154：https://github.com/tradingview/lightweight-charts/issues/2154 — 重复setData后追加Series再更新可能丢失原生时间轴。验证现安装renderer的实际序列/多实例/移除/拖动/Preview路径；不采用无依据clear/reset、sleep或依赖升级。
- issue1457：https://github.com/tradingview/lightweight-charts/issues/1457 — 滚动与纵轴状态的历史失败；转化为多曲线真实renderer测试，不直接复制修复。
- 本仓FP-DATA-001/004、FP-RUNTIME-001/002：旧事件、时钟来源、重连和Current proof必须区分，不能以缺失猜测有效性。
