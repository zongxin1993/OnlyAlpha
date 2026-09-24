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

---

# Data Source Configuration & Management

Mode: **Operate**。Surface: 图表区标题栏的「数据源」入口 + 快速状态 Popover + 「管理数据源」Modal（已配置 / 添加数据源 /
数据源绑定）及其中的 Provider Catalog、契约驱动配置表单、Probe 结果与绑定编辑；以及伴随的空、错、禁用、未知、跳过状态。

状态：**构图已确认**。本节的交互与视觉决策已冻结，implementation baseline 是
`.impeccable/mocks/datasource-manager/comp.html`（逐屏截图同目录 `shots/`）。仍属于 W0 Chart-Centric Workbench 的扩展：
不新增 visual world，不修改 `DESIGN.md` 的 token 与规则，视觉语言与外壳几何全部继承现有实现。

## Surface strategy

- **Job**：OnlyAlpha owner 每天长时间开着工作台。他到达这里只有三件事——30 秒内判断数据层现在可不可信；把某个 Provider
  接上或修好；确认默认由谁负责。他不来这里浏览供应商，也不来这里管理覆盖度。
- **Outcome**：入口 2 秒内可判断整体状态（含文本，不只颜色）；Popover 不打开任何设置页就能看出哪个 Provider 有问题、问题在
  哪一层；添加数据源的第一步像「连接一个服务」，不像编辑后端 YAML；配置、测试、启用、归档在 Modal 内闭环，不跳独立页面。
- **Proof 底线**：每一条显示的配置、状态、延迟都来自正式 Product API 的 canonical 事实（integration revision、lifecycle、
  operational status、probe attempt）。浏览器只做投影与聚合，不重算、不推断、不 fallback。
- **Untouched**：Trading Kernel 语义、Product API 契约、Authority 边界、路由与 URL 语义、图表渲染器边界（ADR 0094/0135）。
  现有 `/data/sources`、`/data/sources/new`、`/data/sources/:integrationId` 保留为可深链页面，与 Modal 共用同一批组件与同一份
  query，不维护两套交互。

## Status semantics

### 单条数据源

| canonical 事实 | 值 | 显示 | 标记形状 | 语义 |
|---|---|---|---|---|
| `operational-status.status` | `READY` | 正常 | 实心圆 | 已发布当前 revision 探测通过 |
| | `DEGRADED` | 降级 | 半填充圆 | 部分能力异常，仍可用 |
| | `OFFLINE` | 连接中断 | 带横线圆 | 当前不可达 |
| | `FAILED` | 失败 | 带横线圆 | 探测失败 |
| | `UNKNOWN` | 未验证 | 虚线环 | 从未探测、revision 更新后未重测，或该类型不提供连接测试 |
| `lifecycle_state` | `DISABLED` | 已禁用 | 空心环 | 保留配置、凭据与历史，不参与使用 |
| | `ARCHIVED` | 已归档 | 空心环 | 默认不在列表；只读 |
| 客户端在途 | — | 测试中 | 旋转虚线环 | 仅表示 `POST /probe` 在途，**不写入任何持久状态** |

形状本身表意，颜色只是冗余；标记一律 `aria-hidden`，语义由紧邻文本承担。

### 汇总计数（顶栏入口与 Popover 标题共用同一规则）

```text
n 异常   = FAILED / OFFLINE / DEGRADED 计数
n 未验证 = UNKNOWN 计数（含 probe_supported = false、无可用验证结果）
```

- `DISABLED` / `ARCHIVED` 不计入任何计数；它们只出现在列表行内。
- 入口颜色只由「异常」决定：有 `FAILED/OFFLINE` → danger；否则有 `DEGRADED` → warning；否则**只有** `UNKNOWN` 时使用
  muted 虚线环 + 文本「n 未验证」，**不得**把入口永久染成黄色异常；全部 `READY` → success；无启用中的数据源 → 灰（未配置）。
- 文案规则：无异常且无未验证时只显示「数据源」；否则在图标后追加 `n 异常` / `n 未验证`（两者可同时出现）。
- 读取失败（正式 API 不可达）时入口退化为「状态未知」，既不显示正常也不显示异常。

## Probe capability 与 Probe check

### capability 由 Integration Type Descriptor 决定

- 判定唯一来源是 **Integration Type Descriptor 的 `probe_contract`**（`probe_contract != null`），不是前端白名单。
- **声明 `probe_contract`**：允许「测试连接」，展示能力级结果；`default_probe_instrument` 用于默认探测，
  `user_selectable_probe_instrument = true` 时允许用户改探测标的。
- **未声明 `probe_contract`**：明确显示「该类型未提供连接测试」并说明原因；**不得**只给一个无解释的 disabled 测试按钮。
  此时 `operational-status.probe_supported = false` 且 `status = UNKNOWN`，该 UNKNOWN 计入 `n 未验证`、不计入 `n 异常`。
- Probe 是**同步** `POST`，没有「进行中」这个服务端状态；「测试中」只能表示请求在途。
- Probe 永远作用于**已发布 revision**（请求带 `expected_revision_fingerprint`）。存在草稿时必须显式说明「本次测试不包含草稿修改」。

### 结果逐项状态

结果视图固定渲染数据源的 5 项检查（`CONNECTIVITY` / `AUTHENTICATION` / `REFERENCE_DATA` / `HISTORICAL_DATA` /
`REALTIME_DATA`，不含 `MODEL_DISCOVERY`），每项四态：

| 状态 | 来源 | 显示 | 允许的渲染 |
|---|---|---|---|
| `PASS` | 该次尝试的结果 | 通过 | 可表达成功 |
| `FAIL` | 该次尝试的结果 | 失败 + `detail` + `error_code` + `failure_kind` | 可表达失败 |
| `SKIPPED` | 检查存在，但本次没有完成验证 | **未验证** | 不得显示成功或失败 |
| 未声明 | 该类型 `probe_contract` 不含此检查 | **不适用** | 不得显示成功或失败 |

`SKIPPED` 与「未声明」是两种不同的「不适用」，必须分别渲染。已声明但结果里缺失的检查显示「未知」并保留 attempt 编号，
不得默认为成功。每项显示自身 `latency_ms`；总耗时取 `completed_at - started_at`；长 `observations` 允许换行或滚动。

## Capability 摘要

canonical capability ID 到三个显示桶的映射只有一份，禁止按 provider 分支：

| 显示桶 | canonical capability ID |
|---|---|
| 历史 | `HISTORICAL_BARS` `HISTORICAL_TICKS` `HISTORICAL_REFERENCE_PRICES` `HISTORICAL_FUNDING_RATES` `HISTORICAL_SETTLEMENTS` |
| 实时 | `LIVE_BARS` `LIVE_TICKS` `LIVE_RECONNECT` |
| 参考 | `INSTRUMENTS` `CALENDARS` |
| 不进入摘要 | `SUPPORTS_RUNTIME_CHECKPOINT:*` `CHECKPOINT_SCHEMA_VERSION`（只在详情「运行时」一行显示） |
| 未映射 ID | 原样显示 ID，不丢弃、不猜桶 |

摘要只在具备该桶任一能力时显示该标签；详情视图必须列出原始 capability ID 本体。

## Layout and interaction topology

### 入口

长在图表区标题栏（`2.1rem` 行高），与 symbol 搜索、周期、指标、因子同排，位于该组 controls 的最右端（`spacer` 起点，
`synthetic` 标记与右面板开关之前）。形态：`[图标] 数据源` + 状态标记 +（异常/未验证时）计数文本。窄屏（`<1280px`）折叠为
图标加状态标记，accessible name 仍为完整文本。全局 40px 顶栏的「数据」产品导航保留，指向现有 `/data/sources` 页面，不新增
第二个入口。

### Popover（宽 320–360，max-height 60vh，内容内部滚动）

每行：Provider 图标视觉盒（20px）、display name、状态标记 + 状态文本、能力摘要标签、最近探测时间与延迟；有失败时追加一行
失败检查名 + 时间。排序按严重度分组（异常 → 降级 → 未验证 → 正常 → 已禁用），组内按 `display_name` 稳定排序。

「当前工作区」块：在来源绑定 Authority 落地前**只能**显示缺口说明（尚未有 canonical 来源绑定、工作区数据当前为 synthetic 占位），
**不得**出现任何具体 Provider 名。

Popover 禁止承载：Token/API Key 表单、删除确认、长错误详情、Binding 配置、高级 Provider 参数、Coverage 管理。

### 管理 Modal（desktop 1000 × 800，内容区内部滚动，头部与 Tab 固定）

三个 Tab 解决三个不同问题，默认「已配置」；Tab 状态只存在于本次打开会话（局部 state），不写 URL、不持久化；切换 Tab 保持
Modal 尺寸稳定。

**Tab 已配置** —— 紧凑卡片列表，不是 Dashboard 卡片墙。每卡：图标 + display name + 描述、状态标记与文本、能力摘要标签、
最近探测（时间 / 用时 / 最慢检查延迟 / revision 前 8 位）、`type_id`、动作区。动作优先级：`测试连接`（次要按钮）> `编辑` >
`启用/禁用` > `⋯`。`⋯` 只放低频项：`归档（删除）`、`查看 revision / probe 历史`、`复制 integration id`；归档永不进一级动作区。
真实状态提示：`有未发布草稿`、`类型契约已更新`（附「重置到最新契约」）、`未验证 + 原因`。已禁用项降为 `surface-2` 底。
Modal footer 承载「显示已归档（n）」与排序说明。

**Tab 添加数据源** —— Provider Catalog：搜索框 + Provider 卡片网格（desktop 4 列）。卡片：图标视觉盒（36px 居中）、display
name、能力摘要、description 截断。无评分、无星级、无推荐、无「热门」、无 Marketplace。V1 平铺不分类（后端 descriptor 无分类字段，
凭空分类就是发明）。流程一步都不能省：`选 Provider → 填必要字段 → 测试连接 → 能力级结果 → 保存配置 / 保存并启用 → 启用`。

**Tab 数据源绑定** —— 明确产品概念，不是配置文件的别名。按「市场 · 品种类别」分组，每组四行（历史 / 实时 / 参考等），每行一个
选择器。选项**只能**选择具备对应 canonical capability 的已启用 integration（不满足能力的 Provider 不出现在该下拉里），并在
选项 label 中带 provider。顶部必须有缺口横幅：该 Tab 目前没有 canonical 事实，实现前必须先有正式绑定 Product API，Web 不得在
本地存储或自行推导默认来源。被禁用但仍被引用的数据源：阻断 + 明确出口（修改绑定 / 重新启用），**禁止自动 fallback**，禁止静默
切换成另一个 Provider。

### 配置表单（Modal 内二级视图，不跳独立页面）

- 字段全部来自 `configuration_contract`：`advanced = false` → 基本设置（按 field 顺序）；`advanced = true` → 折叠区并标注数量；
  `ENUM` → select；`BOOLEAN` → checkbox；`INTEGER / NUMBER / DURATION` → number input + 上下限提示（`DURATION` 以秒标注）；
  `PATH` → 文本输入（不引入文件选择器）。
- 凭据三态：`已配置`（带 generation）/ `未配置` / `需要更新`；动作只有 `更换凭据` 与 `清除`；**永不请求明文回显**，输入框
  `type=password`、`autoComplete=new-password`、提交后立即清空。前端不得出现「编辑原 Secret」的说法。
- 两个提交动作分开：`保存配置`（只发布新 revision，lifecycle 不变）与 `保存并启用`（发布 + `ACTIVE`）。`测试连接` 与
  `保存修改` 是独立动作。
- 草稿版本冲突（`expected_draft_version` 不匹配）→ 提示「该草稿已被其他操作更新」并给「重新载入」，不自动重试。
- 提交结果不确定（`TRANSPORT_ERROR` / `UNKNOWN_OUTCOME`）→ 保留输入与 command intent，提示「结果未确认，请重试同一操作」，
  绝不换 idempotency key 重发。

### 禁用 / 删除 / 归档

- `禁用` = lifecycle `DISABLED`：保留 Integration、Revision、凭据绑定与历史 Evidence，只是不再作为新的活动数据源使用。
- UI 上的「删除」在语义上**只能是归档**（lifecycle `ARCHIVED`）：保留 revision、凭据绑定与历史证据，不永久删除数据；归档项只读。
- 归档确认必须写明「保留了什么」；若仍被来源绑定引用，则阻断并给出「修改绑定」出口（见 comp 07）。

### Responsive

| 断点 | 入口 | Modal | Provider Grid | 表单 |
|---|---|---|---|---|
| ≥1280 | 图标 + 文本 + 状态标记 + 计数 | 1000 × 800 居中 | 4 列 | 单栏，分区标题分隔 |
| 1024–1280 | 图标 + 状态标记 | 90vw，上限 900px | 3 列 | 单栏 |
| 768–1024 | 图标 + 状态标记 | 90vw | 2 列 | 单栏，label 在上 |
| <768 | 仅图标 + 状态标记 | 全屏 dialog，头部与 Tab 固定，内容滚动，操作 sticky 底部 | 1 列 | 纵向，按钮不被遮挡，无水平滚动 |

Tab 在窄屏保持文字（允许横向滚动），不得缩成无法辨认的图标。

### 状态覆盖清单

empty（未配置任何数据源）· loading（skeleton，不用居中 spinner）· backend unavailable（正式 API 不可达，入口退化为状态未知）·
probing 在途 · ready · degraded（能力级分解，禁止压成一句「Provider 错误」）· failed / offline · unknown / never-probed ·
skipped（未验证）· 不适用（未声明）· disabled · archived · 草稿未发布 · 类型契约已更新 · binding 冲突 · permission denied ·
未认证 · 长 canonical id / 64 位 fingerprint 不破版。

## Direction contract

THESIS: 数据源是工作台的仪表，不是设置里的子产品。入口长在图表区标题栏，Modal 复用工作台的面板语法——1px 分隔线、紧凑行高、
中文操作者文案 + 英文 canonical id——而不是自建一套 Settings 外壳、自建品牌色、卡片墙或评分体系。

OWN-WORLD: 继承 DESIGN.md 的浅色工作纸（近白底、hairline、accent 只用于操作与选中、状态色只服务状态、数值与 identity 等宽、
圆角 ≤6px、除浮层外无阴影、无渐变、无玻璃）。

STORY: 操作者打开 Popover 的 2 秒内就知道「哪个 Provider 有问题、坏在哪一层、是不是只是没验证过」；进入 Modal 的第一屏就知道
「我已经有什么、还能接什么、默认是谁负责」。

FIRST VIEWPORT: 图表区标题栏最右的 `[图标] 数据源 ● n 异常 · n 未验证`；Popover 里每行一个 Provider 的 icon、名称、状态文本、
能力摘要、最近探测与失败检查行；底部「管理数据源…」。

FORM: 标准形（Operate，资料密度优先），craft bar = 现有工作台页面自身的密度与克制，不向 Marketplace 或 SaaS Dashboard 漂移。

FINISH: 状态不只靠颜色；数字、时间、fingerprint 等宽对齐；每条控制都有 default / hover / focus / active / disabled / loading /
error；comp 是 fidelity 基准，任何偏离都要在 finish review 里被点出来。

## Authority 与 Product API 映射

| 界面能力 | 正式 Product API |
|---|---|
| 数据源列表 / 详情 | `GET /api/v2/integrations`、`GET /api/v2/integrations/{id}` |
| Provider 目录与字段契约 | `GET /api/v2/integration-types?category=DATA_SOURCE` |
| 草稿读写 | `GET` / `PUT /api/v2/integrations/{id}/draft` |
| 凭据 | `PUT` / `DELETE /api/v2/integrations/{id}/draft/secrets/{field_id}` |
| 契约重置 | `POST /api/v2/integrations/{id}/draft/contract-reset` |
| 发布 revision | `POST /api/v2/integrations/{id}/revisions` |
| 启用 / 禁用 / 归档 | `PUT /api/v2/integrations/{id}/lifecycle` |
| 运行状态 | `GET /api/v2/integrations/{id}/operational-status` |
| 探测与历史 | `POST /api/v2/integrations/{id}/probe`、`GET .../probe-attempts`、`GET .../probe-attempts/{id}` |

复用现有 `packages/onlyalpha-web-console/src/api/integrations/client.ts` 与 `MutationSubmissionIntent`；不得新造第二套提交路径。

### 已知缺口（必须在实现中显性，不得由 Web 伪造）

| 缺口 | 类型 | 说明 |
|---|---|---|
| 来源绑定（Binding）无 Product API | DOMAIN_GAP + AUTHORITY_GAP | Tab 数据源绑定只能作为设计态呈现 |
| 工作区「当前来源」无 canonical 事实 | DOMAIN_GAP | Popover 该块只能是占位说明 |
| 无全局聚合状态 endpoint | QUERY_GAP（接受） | 入口总状态是展示层聚合，规则见上，必须唯一且可见 |
| 无 Instrument Search / Catalog Product API | DOMAIN_GAP | 搜索结果表达「历史✓ / 实时✓」不在本 Surface 交付范围 |
| 仓库内无 Provider 品牌资产 | ASSET | 先用 fallback 字母盒（中性底 + 1px line + provider 首字母），官方 Logo 由 owner 提供，不得下载未授权素材 |

## Anti-goals

Market Data Coverage 大屏、K 线历史 Acquisition 流程、自动 Provider failover、Provider 融合、Provider Ranking / 评分 /
推荐 / Marketplace、Broker 交易配置、Account / Order / Risk 页面、Quote / Depth 完整 UI、完整移动交易工作区、后端数据库 schema、
Provider SDK、Web 直连 Provider / PostgreSQL / ClickHouse。

## Builder 不得自行发明

1. Binding 的 canonical 事实：不得本地存储、不得用浏览器状态推导「默认来源」；没有后端就显示缺口态。
2. 汇总规则与计数口径（`n 异常` / `n 未验证` 的划分、UNKNOWN 不染黄入口）不得改写。
3. capability → 显示桶的映射表只此一份，禁止按 provider 增加分支。
4. `SKIPPED` ≠ 成功 ≠ 失败；「未声明」≠ `SKIPPED`；`UNKNOWN` ≠ 失败 ≠ 正常。
5. 「删除」= 归档；不做永久删除、不做静默 fallback。
6. 「测试中」只是客户端在途态，不写进任何服务端状态语义。
7. Probe 作用于**已发布 revision**；有草稿时必须显式说明。
8. Provider 列表、字段、能力、检查项一律来自 API；图标映射表可以按 `provider_id` 存在，业务真相不行。
9. 「当前工作区」来源在 Binding Authority 落地前只能占位，不得显示具体 Provider 名。
10. 不新增 Product API、不改路由语义、不改后端、不改 `DESIGN.md` 的 token 与规则——那属于后续独立 implementation task。
