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
