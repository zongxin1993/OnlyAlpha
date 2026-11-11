# OnlyAlpha WebUI 管理台改稿迁移 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把冻结稿（`docs/webui/frozen-2026-11-10/index.html`，SHA-256 `400bfe80…3d1b`）的管理台布局迁入 `packages/frontend`，全程走正式 Product API，既有 E2E 18 个 spec 持续全绿。

**Architecture:** 替换 `WorkstationShell` 为左侧栏壳（六项导航 + rail-foot），上下文条只属于工作台、其余画面页内标题；token 层扩为暗色默认双主题；页面迁移按"壳 → 工作台二分 → 画面重组 → 总览 → 打磨"五个阶段推进，每阶段是手册 §11 意义上的完整切片。

**Tech Stack:** React + react-router-dom + antd（既有）、CSS 自定义属性、Playwright E2E、Vitest。不新增依赖。

**Spec:** `docs/webui/design-brief-2026-11-10.md`（设计契约）+ 冻结稿本体；流程与验收服从 `docs/web-product-development-mode.md`。

## Global Constraints

- 分支：`feature/webui-redesign`（本计划所在分支），每任务一提交；推送后核实远端。
- 新增依赖禁止；antd 既有能力优先；自研仅限布局与 token。
- 文案中文；红涨绿跌；tabular numerals；对比度 ≥ WCAG 4.5:1。
- 主题键 `oa-theme`（`dark|light`），暗色默认，持久化，首绘前应用（无闪白）。
- Web 无权威：不新增前端计算/造数；真实数据只来自正式 Product API；缺能力先按手册 §4 分类 Gap 并报告，不私开后门（Constitution §8/§9）。
- LIVE 一律本人授权路径；界面不代办。
- 视口矩阵 390/640/768/880/1024/1152/1440 页面级零横向溢出。
- 每任务收尾：`python3 scripts/dev_verification.py --web run -- npm run check`（lint+typecheck+test）通过；阶段收尾加跑 `npm run e2e` 全量。
- 演示/占位内容开发期必须页面内诚实标注，正式画面不留演示数据。

## 阶段蓝图（每阶段完成才写下一阶段细则）

| 阶段 | 交付 | 关键风险 / Gap 预判 |
|---|---|---|
| **P0 壳**（本计划 Task 1–6） | 双主题 token、左侧栏六项、按画面 ctxbar、抽屉、shell E2E | toolbarHost portal 兼容；antd 暗色算法同步 |
| P1 工作台二分 | 自选竖列(210px)+图表+图下指标行；路由不动 | 自选增删排序是否已有 Command/Query（若无 → COMMAND_GAP，先报告） |
| P2 画面重组 | 研究/策略/回测/数据/系统 接页内标题 + 样式对齐 + 空状态 | Deferred 页面实际完成度以现有代码为准，迁移时盘点 |
| P3 总览 | `/overview`：KPI 带/净值/敞口/市场概况/在跑策略/事件；落地切换决策点（`/`=总览、工作台迁 `/workspace`、E2E 初址同步） | 组合聚合、会话日历均为 QUERY_GAP，先出 Gap 清单与后端最小能力任务契约，再动前端 |
| P4 打磨 | quiet 密度、暗色细节、全量回归 + dogfood | — |

**Review Focus**（冻结稿未逐字写明、但最可能咬人的失败类，各自钉到任务）：
1. 主题首帧闪白（FOUC）→ Task 1：断言 HTML 首个 `<script>` 同步写 `data-theme`。
2. 窄栏中文不可见（批注期真实事故）→ Task 3：断言六项文字在任何断点 `visible`。
3. 非工作台页面 toolbarHost 断挂 → Task 4：workspace-toolbar E2E 保持绿。
4. 窄屏遮罩残留挡住操作 → Task 5：Esc/遮罩点击/选择后 `rail-open` 必清。
5. antd 弹层（Dropdown/Modal/Tooltip）在暗色下错色 → Task 1：ConfigProvider 同步 `darkAlgorithm`。

---

### Task 1: 双主题 token 与主题基础

**Files:**
- Modify: `src/app/styles/tokens.css`（现 34 行，light `:root` 保留为浅色调色板，新增 `[data-theme="dark"]` 块与 brief Token 表；现名 `--surface-2`↔brief `--surface2` 做映射合并，不重命名既有变量）
- Create: `src/app/theme/theme.ts`（`getStoredTheme/applyTheme/toggleTheme`，键 `oa-theme`，默认 `dark`，同步 `document.documentElement.dataset.theme` 与 `color-scheme`）
- Modify: `index.html`（`<head>` 内联同步脚本调用主题初始化，防 FOUC）
- Modify: `src/app/providers.tsx`（antd `ConfigProvider` theme.algorithm 随 `data-theme` 取 `darkAlgorithm/defaultAlgorithm`；用 MutationObserver 或受控 state 同步）
- Test: `src/app/theme/theme.test.ts`

**Interfaces:**
- Produces: `applyTheme(t:"dark"|"light"):void`、`toggleTheme():`"dark"|"light"`、`initTheme():void`（main 前执行）；CSS 属性 `[data-theme="dark"]`。

- [ ] **Step 1** 写失败测试：默认无存储时 `documentElement.dataset.theme==="dark"`；`toggleTheme()` 后为 `light` 且 `localStorage["oa-theme"]==="light"`；再次加载（同 storage mock）保持 `light`；`index.html` 内联脚本位置在 `<body>` 渲染前（读取文件断言脚本在首个样式链接后、`<div id="root">` 前）。
- [ ] **Step 2** 跑 `npm run test -- theme` 确认 FAIL。
- [ ] **Step 3** 按 Interfaces 实现 theme.ts + index.html 内联 + tokens.css 暗色块（取数自 brief 表：`--bg:#111418 --surface:#171b21 --surface-2:#1d222a --text:#e8ebef --muted:#9da6b2 --faint:#8b95a2 --line:#242a33 --line-soft:#1e242c --accent:#6f9eff --up:#f0565d --down:#4cc48d`，新增 `--ink-up:#ff9297 --ink-down:#6fd3a5`；浅色补 `--faint:#667080 --ink-up:#b3231f --ink-down:#0f7a48`）。
- [ ] **Step 4** providers.tsx 接 darkAlgorithm；`npm run test -- theme` PASS；`npm run check` 绿。
- [ ] **Step 5** Commit `feat(webui): 暗色默认双主题 token 与主题基础`。

### Task 2: 导航配置单一来源

**Files:**
- Create: `src/app/nav.ts`；Test: `src/app/nav.test.ts`

**Interfaces:**
- Produces: `NAV_GROUPS: {group:string; items: NavItem[]}[]`，`NavItem={to:string;label:string;icon:string;ctxbar:boolean}`；顺序=总览(占位 `/overview`)、工作台(`/`)、研究(`/research/new`)、策略(`/strategies`)、回测(`/backtest`)｜数据(`/data/inputs`)、系统(`/system/health`)；`ctxbar` 仅工作台为 true。
- Consumes: 路由不变（总览项暂指占位路由，Task 4 提供）。

- [ ] **Step 1** 写失败测试：两组、七项、顺序如上；`ctxbar===true` 恰一项；`to` 无重复。
- [ ] **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS + `npm run check` → **Step 5** Commit `feat(webui): 导航配置单一来源`。

### Task 3: 左侧栏 SideRail 与壳改造

**Files:**
- Create: `src/app/shell/SideRail.tsx`、`src/app/shell/sideRail.css`
- Modify: `src/app/shell/WorkstationShell.tsx`（右侧 icon rail 替换为左侧栏；**保留** `toolbarHost`/`railHost` 两个 portal host 与设置锚点 `openSettings`）
- Test: `src/app/shell/WorkstationShell.test.tsx`（更新）

**Interfaces:**
- Consumes: `NAV_GROUPS`、`toggleTheme`（rail-foot 主题钮）、`WorkspaceIcon`（既有；缺总览图标则同文件加内联 SVG，语义=四宫格仪表）。
- Produces: DOM 约定 `nav.side-rail`、`.rail-foot`、`body.rail-open`（Task 5 使用）；密度钮 `class="rail-quiet"` 写 `body.quiet`（样式 P4 完善，P0 仅落类）。

- [ ] **Step 1** 更新失败测试：六+一项 label 文字**可见**（`toBeVisible`，任何 jsdom 视口）；分组标题可见；当前路由项 `aria-current="page"`；rail-foot 含主题钮且点击后 `documentElement.dataset.theme` 翻转；品牌区不再是顶栏唯一入口。
- [ ] **Step 2** FAIL → **Step 3** 实现（200px 固定宽、组标签 11px `--faint`、项=图标+文字 flex、active 用 `--accent-soft`+左侧 2px 指示条；样式全部进 sideRail.css，不动 base.css）→ **Step 4** PASS、既有 `WorkstationShell.test.tsx` 其余断言全绿 → **Step 5** Commit `feat(webui): 左侧栏导航壳`。

### Task 4: 按画面上下文条 + 页内标题机制

**Files:**
- Create: `src/app/shell/PageHeader.tsx`（`<header class="view-head">` h1+副标题+窄屏 ☰）、`src/app/shell/ContextBar.tsx`（含 `#workspace-toolbar-host` portal 挂载点，兼容现 WorkspacePage）
- Modify: `src/app/shell/WorkstationShell.tsx`（按当前路由匹配 `NavItem.ctxbar` 渲染二选一）、`src/app/router.tsx`（新增 `{path:"/overview"}` → Create `src/app/OverviewPlaceholder.tsx`：PageHeader"总览"+诚实空态"画面于 P3 交付"）
- Test: `src/app/shell/WorkstationShell.test.tsx`（追加）

**Interfaces:**
- Consumes: `NAV_GROUPS.ctxbar`；`toolbarHost` 语义不变（WorkspacePage 零改动）。
- Produces: `PageHeader({title,subtitle})`（P2 各画面复用）；`body.no-ctx` 类（非工作台画面）。

- [ ] **Step 1** 失败测试：`/`（工作台）渲染 ContextBar 且含 toolbar host 节点、无 view-head；`/overview` 与 deferred 路由渲染 view-head 标题、无 ctxbar；壳含 `footer.status`，P0 内容仅限导航链接与设置入口（版本/健康数据无既有 API，宁缺毋假，真实内容归 P4）。
- [ ] **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS 且 `workspace-toolbar.spec.ts` 相关单测绿 → **Step 5** Commit `feat(webui): 上下文条按画面配置`。

### Task 5: ≤900px 抽屉导航

**Files:**
- Modify: `src/app/shell/sideRail.css`（媒体查询转 overlay + `#rail-mask`）、`src/app/shell/SideRail.tsx`（☰ 按钮、遮罩、Esc、选择后关闭）
- Test: `src/app/shell/SideRail.test.tsx`

- [ ] **Step 1** 失败测试：点 ☰ → `body.rail-open`；点遮罩/Esc/导航项 → 类清除；`aria-expanded` 同步。
- [ ] **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS → **Step 5** Commit `feat(webui): 窄屏抽屉导航`。

### Task 6: 壳 E2E + 全量回归

**Files:**
- Create: `e2e/shell-nav.spec.ts`
- Modify: 无（若发现既有 spec 因壳 DOM 失败，属本任务修复范围，改断不改测试意图）

- [ ] **Step 1** 写 spec：1440 下六项导航中文可见并逐项目击到目标画面标题；主题切换后 reload 保持暗/浅；`/` 有 ctxbar、`/overview` 无；390 下 ☰→抽屉→选择总览→抽屉自动关；七档视口 `scrollWidth<=innerWidth`。
- [ ] **Step 2** `npm run e2e`（dev_verification --web 拓扑）全量 19 spec 绿；`npm run check` 绿。
- [ ] **Step 3** Commit `test(webui): 壳导航 E2E 与响应式矩阵`。
- [ ] **Step 4** 手册 §11 停止条件核对 → 汇报 P0 关闭，不自动进入 P1。

---

**验收（P0 整体）**：真实浏览器经正式入口走完上列路径；`f65eab3b` 基线上的 18 个既有 spec 与新增 shell-nav 全绿；无新增依赖；工作树干净。

---

# P1 细则：工作台二分（2026-11-11 制定，P0 关闭后撰写）

**闸门核查（P1 前置）**：自选增删 Command/Query 完备——`/api/v2/watchlists` GET/PUT + `/commands/{id}`（乐观并发、schema v2、后端 application/persistence 齐备）；排序能力存在（members 有序 + PUT 全量），冻结稿无排序 UI 诉求 → **无 COMMAND_GAP**。

**布局裁决（冻结稿未覆盖的能力去留）**：
- 左列 210px 通高 = 自选卡（主）+ 检查器折叠卡（details，默认收起；能力不丢）。
- 图下 wb-c 双卡 = "指标 / 因子"（已挂列表 + 色块 + 图中/未上屏 + 目录按钮）与"工作区"（当前工作区 + 保存副本）。
- 研究面板（研究运行/研究结果）为现役能力，冻结稿未画——保留为图下第三行，P2 研究画面重组时迁出工作台。
- 自选行保持 `<table>` 语义，CSS 对齐冻结稿观感（名称截断、价格列不挤、tabular numerals）；现有交互（选标的、行菜单、行情轮询）全保留。
- 路由不动；ctxbar/工具条 portal 不动；桌面托盘"自选/检查器"开关随左列常开而撤除（shell 右轨宿主保留）。

### Task 7: 左自选竖列与托盘整合

**Files:**
- Modify: `src/features/workspace/WorkspacePage.tsx`（左 aside 常开竖列、检查器入折叠卡、tray 撤除）、`src/features/workspace/watchlists.css`（竖列观感对齐冻结稿：行高 9px 16px、`--line-soft`、截断）、必要处 `toolbars.css`
- Test: `WorkspacePage.test.tsx`、`WatchlistPanel.test.tsx` 同步（改锚不改意图）

- [ ] **Step 1** 失败测试：`/` 渲染 `aside.workspace-watchlist-column[aria-label=自选]` 常开（无 panelOpen 开关亦可见）、检查器为折叠卡默认收起、托盘"自选/检查器"按钮不再渲染。
- [ ] **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS → **Step 5** Commit `feat(webui): 工作台左自选竖列`。

### Task 8: 图下"指标 / 因子"卡

**Files:**
- Create: `src/features/workspace/ActiveStudiesCard.tsx`（+.css 或并入 chartStudy.css）
- Modify: `WorkspacePage.tsx`（wb-c 区渲染，instances/颜色/上屏态来自既有 ChartStudies 状态；"目录"按钮打开既有指标目录 dialog——提升受控入口，工具条六控件不动）
- Test: 新卡单测（列出已挂实例、色块、图中/未上屏、目录按钮触发）

- [ ] **Step 1** 失败测试 → **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS → **Step 5** Commit `feat(webui): 图下指标因子卡`。

### Task 9: 图下"工作区"卡

**Files:**
- Create: `src/features/workspace/WorkspaceSummaryCard.tsx`
- Modify: `WorkspacePage.tsx`（当前工作区名可得则显示、否则诚实空态；"保存副本"接既有保存流程入口）
- Test: 新卡单测（命名/空态/保存触发既有 command）

- [ ] **Step 1** 失败测试 → **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS → **Step 5** Commit `feat(webui): 图下工作区卡`。

### Task 10: 二分/单列响应式布局

**Files:**
- Modify: `WorkspacePage` 布局容器 CSS（≥900：grid `210px minmax(0,1fr)`，areas a/b、a/c、a/d；≤880 单列序：图表→指标行→工作区→研究面板→自选）
- Test: 布局合同由 Task 11 E2E 承担 + 单元 DOM 顺序锚

- [ ] **Step 1** 样式实现 → **Step 2** `npm run check` 绿 → **Step 3** Commit `feat(webui): 工作台二分响应式`。

### Task 11: 工作台 E2E 契约 + 全量回归

**Files:**
- Create: `e2e/workspace-layout.spec.ts`（1440：左自选竖列可见+点行切标的+图下双卡标题存在；390：单列序、无横向溢出；受影响既有 spec 修正锚点不改意图）
- Modify: `deploy/run-web-e2e.sh`（A 组加入新 spec）

- [ ] **Step 1** 写 spec 并经正式 native 入口跑绿；**Step 2** 全量默认计划回归对照（新增失败=0）；**Step 3** `npm run check` + prettier；**Step 4** Commit `test(webui): 工作台布局契约`；**Step 5** fresh-reviewer 全分支审查 → 修 Important → §11 核对 → 汇报 P1 关闭，不自动进入 P2。

---

**验收（P1 整体）**：`/` 呈冻结稿二分（真实数据、真实交互）；能力零丢失（检查器/研究面板/托盘功能各有归置）；壳 3 spec 与全部既有 web E2E 相对基线零新增失败；单元全绿。

---

# P2 细则：画面重组（2026-11-11 制定，P1 关闭后撰写）

**范围裁决（负责人已确认，2026-11-11）**：
- **数据画面接回**：`DataSourceManager` 以既有整页包装器挂 `/data/*` 正式路由，成为真画面；Deferred E2E 契约同步改写。
- **研究画面暂不接**：`/research/*` 维持「研究 · 未实现」Deferred 契约不动，`research.spec.ts` 保持全绿；P2 只产出 Gap 盘点清单（Task 16）。工作台研究面板**不迁出**（P1 细则的迁出义务随研究画面交付延后，记录于此）。
- **样式对齐深度 = 外壳对齐**：view-head 页头 + 卡片/`.tw` 表格容器 + 徽章纪律 + 单列断点到位；antd 表单、对话框等内部控件保留现状，不逐 DOM 复刻冻结稿。
- **系统画面 = 诚实画面**：只用真实可得事实，版本/迁移号缺口诚实标注，P2 不动后端。

**闸门核查（P2 前置，已核源码）**：
1. 后端 `packages/backend/src/transport/routes.rs::navigation()` 已注册 `/data`、`/data/inputs`、`/data/sources`、`/data/sources/new`、`/data/sources/{id}`、`/system`、`/system/health`（契约测试 `tests/transport/web_navigation.rs` 绿）→ **数据/系统接回零后端改动**。
2. `/health/live`、`/health/ready` 为 product-api v2 正式契约端点，返回 `NativeHealthDto { status: "LIVE" | "READY" }`，同源可达（`vite.config.ts` 已代理 `/health`）；`/health/execution` 恒 501，**不使用**。系统画面因此有真实运行时事实可读；「后端版本/迁移号」无端点 → 记 QUERY_GAP，界面宁缺毋假。
3. `DataSourcesPage` / `NewDataSourcePage` / `DataSourceDetailPage` 整页包装器与 `DataSourcesWorkspace.test.tsx`（memory router 按 `/data/sources{,/new,/:integrationId}`）完备，仅缺路由挂载与页头。
4. `Product API 无 version 端点`：P0 footer「宁缺毋假」裁决继续成立，P2 不改 footer。

**布局裁决（冻结稿 → 现有实现映射）**：
- 路由：`/data` → redirect `/data/inputs`；`/data/inputs` 与 `/data/sources` → `DataSourcesPage`；`/data/sources/new` → `NewDataSourcePage`；`/data/sources/:integrationId` → `DataSourceDetailPage`；`/system` → redirect `/system/health`；`/system/health` → 新建 `SystemHealthPage`。导航锚 `nav.ts` 不动。
- 三个数据整页包装器各加 `PageHeader title="数据" subtitle="数据源接入与授权"`（冻结稿 v-data 页头文案）；`DataSourceManager` 本体不感知页头 → 设置抽屉与工作台弹层两个既有入口原样保留，能力零丢失。
- 策略/回测：页头换 `PageHeader`（h1=画面名，副标题取冻结稿「草稿、冻结版本与晋级」「运行任务与证据」）；替换各自 `strategy-workflow-header` / `backtest-page-header` 顶栏中的 `Typography.Title` 职责，头部操作钮（刷新、返回链接等）保留为页头行右侧或次级行；`main` 的 `aria-label`（"策略记录"「策略回测」等）**不动**，是既有 E2E 锚。回测结果视图 h1 用「回测结果」。
- 系统画面内容（自上而下）：PageHeader「系统 / 运行时状态」→ 运行时健康卡（liveness/readiness 实测，成功显示 LIVE/READY 徽章，失败/503 按简报纪律说明「发生了什么、本次查看未生效、可重试」）→ 偏好说明卡（主题/密度当前值与切换指引，来自本地真实状态）→ 诚实缺省卡：「后端版本与迁移号暂无正式查询端点（QUERY_GAP），此处宁缺毋假」。不做任何演示数据。
- 共享样式：新增 `.view-detail`（冻结稿 `.detail`：`grid-template-columns: 1fr 340px; gap:16px; align-items:start`，`@media (max-width:1239px)` 转单列）与 `.tw`（`overflow-x:auto` 表格横滚容器）进 `src/app/styles/base.css` 共享层；策略/回测正文按语义套 `page-with-head`。

**Deferred 契约同步（改锚不改意图）**：
- `product-workspaces.spec.ts`：`/data/inputs` heading 锚 `数据 · 未实现` → `数据`（exact，level 1）`deferred:true→false`；`/system/health` → `系统`，`deferred:false`；`/strategies` 锚 `我的策略` → `策略`（level 1）；`/backtest` 锚 `策略回测` → `回测`（level 1，`main aria-label="策略回测"` 仍在但不再作 heading 锚）；研究行不动；文件头注释同步。Deferred 目的地「零业务请求」判定仅对研究保留。
- `analysis.spec.ts`：`/data/inputs`、`/data/sources/existing-source` 两行从 deferred 列表改为真画面移动锚（view-head 可见 + 390 零横向溢出 + 左栏可回工作台）；`/research/analysis` deferred 不动。
- `shell-nav.spec.ts`：38–42 行 `数据 · 未实现`/`系统 · 未实现` 锚改 `数据`/`系统`。
- `research.spec.ts` 与后端 `web_navigation.rs`：不动。

---

### Task 12: 数据画面接回

**Files:**
- Modify: `src/app/router.tsx`（`/data` redirect 与三个整页包装路由）、`src/features/data/sources/DataSourcesPage.tsx`、`NewDataSourcePage.tsx`、`DataSourceDetailPage.tsx`（各加 PageHeader）、`DataSourcesWorkspace.test.tsx`（页头断言追加）
- Modify: `e2e/analysis.spec.ts`、`e2e/product-workspaces.spec.ts`、`e2e/shell-nav.spec.ts`（按上表改锚）

- [ ] **Step 1** 失败测试：单测 `/data/inputs` 渲染 `view-head` h1「数据」与管理器主体；`/data/sources/new` 打开「添加数据源」页签；`/data/sources/<id>` 定位该 Integration。
- [ ] **Step 2** FAIL → **Step 3** 实现路由与页头 → **Step 4** PASS + 三个 E2E 改锚后本地跑绿 + `npm run check` → **Step 5** Commit `feat(webui): 数据画面接回正式路由`。

### Task 13: 策略画面外壳对齐

**Files:**
- Modify: `src/features/strategies/StrategyWorkflow.tsx`（PageHeader 替换自绘头、正文套 `page-with-head`/`.view-detail`/`.tw`、空状态对齐冻结稿文案骨架——「还没有策略…」按现有真实操作改写，不造「新建策略」假入口，入口沿用现有真实流程）、`strategyWorkflow.css`
- Test: `StrategyWorkflow.test.tsx`、`ManualStrategyWorkflow.test.tsx`（改锚不改意图）

- [ ] **Step 1** 失败测试：列表视图 h1「策略」+ 副标题存在；原「我的策略」降为卡内 h2；≤1239px 单列由 Task 17 E2E 承担。
- [ ] **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS + `npm run check` → **Step 5** Commit `feat(webui): 策略画面外壳对齐`。

### Task 14: 回测画面外壳对齐 + 徽章纪律

**Files:**
- Modify: `src/features/backtest/BacktestPage.tsx`（PageHeader：列表/新建 h1「回测」、结果视图 h1「回测结果」，副标题「运行任务与证据」；表格入 `.tw`；`aria-label="策略回测"` 不动）、`backtest.css`；徽章文案核查——徽章只放短状态词（完成/运行中/取消/失败），限定与后果移入正文字段，逐处记录
- Test: `BacktestPage.test.tsx`、`BacktestSetup.test.tsx`

- [ ] **Step 1** 失败测试（h1 锚 + 徽章短词断言）→ **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS + `e2e/backtest.spec.ts` 相关锚本地绿 + `npm run check` → **Step 5** Commit `feat(webui): 回测画面外壳对齐与徽章纪律`。

### Task 15: 系统诚实画面

**Files:**
- Create: `src/features/system/SystemHealthPage.tsx`（+.test.tsx）、`src/api/health/health.ts`（`getLiveHealth()/getReadyHealth()`：同源 `GET /health/{live,ready}`，`{status}` 解析，网络失败/503 → 类型化错误；仅此读路径，不新增依赖）
- Modify: `src/app/router.tsx`（`/system` redirect + `/system/health` 路由）、`e2e/product-workspaces.spec.ts`、`e2e/shell-nav.spec.ts`（系统行改真画面锚）

- [ ] **Step 1** 失败测试：成功态渲染 LIVE/READY 徽章与实测时间戳；503/网络失败显示「发生了什么 + 查看未生效 + 重试钮」；缺省卡文案存在（无版本数据时不得显示任何版本号）。
- [ ] **Step 2** FAIL → **Step 3** 实现 → **Step 4** PASS + E2E 锚绿 + `npm run check` → **Step 5** Commit `feat(webui): 系统画面诚实运行时状态`。

### Task 16: 研究画面 Gap 盘点（纯文档，闸门豁免）

**Files:**
- Create: `docs/webui/research-screen-gap-inventory-2026-11.md`

- [ ] **Step 1** 冻结稿 v-research 逐区块对照现有 product-api：私有因子表（现有 authoring/inventory 端点可覆盖程度）、版本详情（IC 均值/t 值有无契约字段）、运行记录时间线（Research Run 查询可得性）、输入指纹链接（Dataset Snapshot 引用）、「在图表中对照」（现有工作台挂载路径）；逐区块标注 `可复用 / COMMAND_GAP / QUERY_GAP`，附端点或字段证据。
- [ ] **Step 2** Commit `docs(webui): 研究画面能力缺口盘点`。只盘点不实现；研究画面后续阶段凭此清单立任务契约。

### Task 17: 画面壳 E2E + P2 全量回归

**Files:**
- Create: `e2e/screen-shells.spec.ts`：1440 下数据/策略/回测/系统四画面 view-head h1 逐项可见；数据画面经 native 真实列表可读（有配置源则名称可见，无则诚实空态）；系统画面健康徽章来自真实响应（拦截 `/health/ready` 断言确实发出且渲染一致）；1024 策略 detail 单列；390 全画面零横向溢出；`/data` `/system` redirect 生效
- Modify: `deploy/run-web-e2e.sh`（A 组加入新 spec）

- [ ] **Step 1** 写 spec 并经正式 native 入口跑绿；**Step 2** 全量默认计划回归对照（新增失败=0）；**Step 3** `npm run check` + prettier；**Step 4** Commit `test(webui): 画面壳契约 E2E`；**Step 5** fresh-reviewer 全分支审查 → 修 Important → 手册 §11 核对 → 汇报 P2 关闭，不自动进入 P3。

---

**验收（P2 整体）**：数据/系统是真画面（全部数字来自正式 API，零演示数据）；策略/回测外壳符合冻结稿布局契约（view-head、卡片、`.tw`、≤1239 单列、徽章短词）；研究诚实 Deferred 且有凭据的 Gap 清单入库；`research.spec.ts` 与后端导航契约全绿；全部既有 web E2E 相对基线零新增失败；单元全绿；能力零丢失（设置抽屉与工作台数据源入口原样保留）。

**分支**：沿用 `feature/webui-redesign`（已与 master 同步，直接续工）。
