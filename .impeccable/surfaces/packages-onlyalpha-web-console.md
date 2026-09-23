---
version: 1
slug: "packages-onlyalpha-web-console"
primary_target: "packages/onlyalpha-web-console"
related_targets: []
---

# W0 — Chart-Centric Workspace shell

Mode: **Operate**. Surface: the primary workspace route `/` plus the application shell that wraps every product route.

## Surface strategy

- **Job**：OnlyAlpha owner/operator 每天长时间使用的主工作区。到达时已经知道自己要看什么，需要的是 map 上
  “这个标的/这张图/这些面板” 的连续上下文，不离开图表去别处翻状态。
- **Outcome**：在图表上下文里读到 canonical 状态（Strategy Revision、Run、Backtest、执行事实）并通过正式 command 发起下一步。
  W0 只交付持久外壳与交互拓扑，使用 realistic placeholder 数据并标注为 synthetic；真实 Query 从 W1 起接入。
- **Proof 底线**：所有状态最终来自正式 Product API。浏览器不重算 Research/Trading truth，不直连 DB/Store/Core。
  W0 不新增 Product API、不新增 Authority。
- **Untouched**：Trading Kernel 语义、Product API 契约、Authority 边界、URL/identity 原则、现有实现页面与其能力。
  渲染器边界沿用 ADR 0094/0135：financial time series → lightweight-charts（现有依赖），scientific → ECharts，不换渲染器。
- **Anti-goals**：SaaS dashboard、大卡片堆叠、以 Research 页面为产品中心的组织、渐变/玻璃拟态/大圆角/巨型 Hero、
  深色 Evidence Workbench 视觉世界、动画编排式入场、把图表挤成面板之间的空隙。

## States and ranges

外壳必须为这些状态留位：loading、empty、backend unavailable、degraded/stale、error、permission denied、未认证；
`UNKNOWN` 与 incomplete 保留其不确定性，不得被 accent 或 success 掩盖。长 canonical identity 不破版。
假设量级：watchlist 数十行、底部面板数百行（虚拟化）、symbol 搜索数十条即时结果。

## Layout and interaction topology

- 顶栏：symbol / timeframe / chart type / 图层与工作区动作，高度约 40px，密度优先，不放入营销文案。
- 左 rail：48px 工具条，可收成图标条；只承载与图表相关的工具。
- 中央：主图区，占据剩余宽高，是页面唯一视觉中心。
- 右面板：320px 上下文面板，默认 Watchlist，可切到 Inspector（identity / provenance / 精确值）。
- 底部面板：约 240px，可收起，默认 Research Runs / Results，为 Backtest 与执行面留标签位。
- 底部状态条：28px 常驻，承载 authority 声明与连接状态。
- 层级：图表 > 面板 > chrome；结构靠 1px 分隔线与空间表达。响应式阈值假设：1280–1920 全功能；更窄时左 rail 折叠、
  右面板转抽屉、底部面板收起。焦点 3px ring + 3px offset，键盘可达，反馈 150–250ms 且只表达状态。

## Direction contract

THESIS: W0 交付的外壳必须一眼是成熟的专业量化工作台：图表是唯一视觉中心，四条面板围着它工作；它明确拒绝成为以
Research 卡片为中心的 dashboard。

OWN-WORLD: 浅色工作图纸。近白底 `#f8f8f5`、面板纸灰 `#f1f1ec`、hairline `#e2e2dd`、正文 `#20242b`、muted `#6b7280`；
状态色只服务状态与数据（涨 `#c8332a`、跌 `#2f7d47`、未知/过期 `#8a6d1f`），accent `#1f5f8b` 只用于操作与选中；
所有数值与 identity 用等宽数字；1px 分隔、圆角不超过 6px、除浮层外无阴影、无渐变、无玻璃。

STORY: 操作者进入后第一秒就知道“现在是什么标的、哪张图、哪些面板跟着它、哪些事实是可信的”，不需要读标题或卡片才能开始工作。

FIRST VIEWPORT: 顶栏 40px（symbol / timeframe / chart type / 图层与工作区动作）；左侧 48px 工具条；中央图表占满剩余宽高；
右侧 320px 面板默认 Watchlist，切 Inspector 展示 identity 与 provenance；底部 240px 可折叠面板默认 Research Runs / Results；
最底 28px 状态条常驻。

FORM: 标准形（canon，standing exit），seed key `2db962f8`；craft bar = TradingView chart 页面。本标准形原本以深色终端材料出现，
而 brief 钉死了浅色优先，因此保留它的拓扑、控制词汇与状态词汇，只把材料表达翻译成浅色工作图纸——这是被钉死材料的翻译，
不是对惯例的削弱。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Shell extension — top-bar controls and chart overlays

顶栏现在承载四件事，顺序与 TradingView chart 的参考一致：标的搜索框（带过滤建议）、K 线周期下拉、指标选择器
（点开是搜索框 + 列表）、因子选择器（同样是搜索框 + 列表）。选定后直接画在图上：指标叠加在主图（MA 线，带末值与
标签），因子画在独立窗格，共享同一条时间轴。工作区右侧新增一条窄工具栏（自选 / 检查器 / 回测），与左侧图表工具条对
称。选择器支持多选；Esc 或点击外部关闭弹层。

Authority 边界：叠加值当前是 **synthetic 占位序列**（`buildPlaceholderOverlay`），不是 canonical 计算结果。
真实指标与因子值必须来自 `onlyalpha.calculations` 并经 Product API 投影到 Web；这项缺口按 W3（Indicator / Factor）
处理，Web 不得自行重算。渲染器边界不变：仍是 lightweight-charts，指标在主 pane、因子在 pane 1。
