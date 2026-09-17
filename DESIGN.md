---
name: OnlyAlpha Web Console
description: A restrained evidence workbench for a stateful quantitative system.
colors:
  bg-deep: "#090f19"
  surface: "#101925"
  surface-raised: "#162233"
  surface-emphasis: "#1a2a3e"
  text: "#e4edf7"
  muted: "#96a7bd"
  primary-accent: "#53c7f5"
  primary-solid: "#106ca8"
  accent-soft: "#112c43"
  border: "#253449"
  border-soft: "#1c293a"
  field-bg: "#091524"
  action-bg: "#0e7490"
  action-border: "#0891b2"
  danger: "#fda4af"
  danger-bg: "#9f1239"
  danger-border: "#be123c"
  danger-strong: "#fb7185"
  warning: "#fde68a"
  warning-border: "#a16207"
  success: "#34d399"
  success-text: "#6ee7b7"
  success-border: "#047857"
  white: "#ffffff"
typography:
  display:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "clamp(1.5rem, 3vw, 2rem)"
    lineHeight: 1
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.875rem"
    lineHeight: 1.5
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.78rem"
    fontWeight: 800
    letterSpacing: "0.14em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.73rem"
rounded:
  sm: "4px"
  md: "6px"
  lg: "7px"
  xl: "8px"
  pill: "999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
  xl: "1.5rem"
  2xl: "2rem"
components:
  button-primary:
    backgroundColor: "{colors.action-bg}"
    textColor: "{colors.white}"
    rounded: "{rounded.lg}"
    padding: "0.55rem 0.85rem"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.primary-accent}"
    rounded: "{rounded.lg}"
    padding: "0.55rem 0.85rem"
  button-subtle:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.lg}"
    padding: "0.45rem 0.7rem"
  input:
    backgroundColor: "{colors.field-bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "0.8rem"
  surface-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.xl}"
    padding: "1rem"
  nav-link:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.md}"
    padding: "0.65rem"
  nav-link-active:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.primary-accent}"
    rounded: "{rounded.md}"
    padding: "0.65rem"
  status-badge:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.pill}"
    padding: "0.3rem 0.55rem"
---

# Design System: OnlyAlpha Web Console

## Overview

**Creative North Star: "Evidence Workbench"**

OnlyAlpha 的 Web Console 应该像一张严谨的证据工作台：操作者首先看到状态、来源、边界和可追溯关系，而不是装饰。视觉层级来自空间、细边框和相邻 surface 的色阶；整体气质务实、克制、严谨，并承认可见证据的有限性。

当前实现是深色工作台：深海军蓝背景承载多层蓝灰 surface，浅蓝 accent 只标记可操作、选中和可追踪关系。组件紧凑、信息密度高，但不通过大阴影或夸张的展示型排版制造权威感。浅色主题与主题切换是已确认的产品要求，当前代码尚未实现；新增页面应保留这项要求，不得把现有深色 token 误写成完整双主题系统。

**Key Characteristics:**

- 以 evidence、state、identity 和 provenance 为视觉组织单位。
- 通过 tonal surface 与 1px border 建立层次，不依赖大阴影。
- 紧凑、工具化、可扫描；稳定 identity 使用等宽字体。
- Web 文案默认使用中文；仅保留有明确语义的英文，如 `API token`、版本号和 canonical identity。

## Colors

当前调色板是低饱和深海军蓝中性底，配以单一冷浅蓝 primary accent；语义色只用于明确的成功、警告、失败状态。

### Primary

- **冷光证据蓝** (`#53c7f5`): 链接、选中态、焦点环和可追踪关系；应保持稀缺，不能铺满整屏。
- **深海执行蓝** (`#106ca8`): 需要比 accent 更实的强调背景时使用。
- **深青操作底** (`#0e7490`): primary button 与明确的 command action。

### Neutral

- **深夜底色** (`#090f19`): 页面与工作区的最底层背景。
- **工作台表面** (`#101925`): 卡片、工作台和主要容器。
- **抬升表面** (`#162233`): 导航 hover、事实标签和次级信息区。
- **强调表面** (`#1a2a3e`): 更高对比度的局部数据单元。
- **正文白** (`#e4edf7`): 主要文字与高优先级 identity。
- **证据灰** (`#96a7bd`): 辅助说明、标签和次要状态。
- **字段底色** (`#091524`): input、select、代码块与嵌入式数据区。
- **结构边界** (`#253449`): 主要边框、分隔线与事实表。
- **弱边界** (`#1c293a`): 密集分析区中的低强调分隔线。

### Semantic States

- **成功** (`#34d399` / `#6ee7b7`): 正常连接、resolved、completed 等已确认状态。
- **警告** (`#fde68a`): cancel requested、证据不足或需要注意的状态。
- **失败/风险** (`#fda4af`、`#fb7185`、`#9f1239`、`#be123c`): error、failed、cancelled、危险操作；不要把它们当作普通 accent。

### Named Rules

**The One Accent Rule.** Primary accent 只标记行动、选择、焦点与关系；surface、border 和 muted text 承担大部分信息层级。

## Typography

**Display Font:** Inter (with `ui-sans-serif`, system-ui and platform fallbacks)

**Body Font:** Inter (with `ui-sans-serif`, system-ui and platform fallbacks)

**Label/Mono Font:** `ui-monospace`, `SFMono-Regular`, Menlo, monospace

**Character:** Inter 提供中性的工具感，适合高密度状态与表格；等宽字体只承载稳定 identity、fact value、版本和机器可读内容，不用于制造装饰感。

### Hierarchy

- **Display** (browser-default bold, `clamp(1.5rem, 3vw, 2rem)`, line-height `1`): 页面标题和主要工作区标题。
- **Title** (组件按需缩放，常见 `1.1rem`–`1.2rem`): builder section、panel 和局部工作区标题。
- **Body** (regular, `0.875rem`, line-height `1.5`): 正文、表单和操作说明。
- **Label** (800, `0.78rem`, letter-spacing `0.14em`, uppercase only where an existing utility requires it): 区域标记和状态标签；不要为了制造层级任意新增 kicker。
- **Mono** (regular, `0.73rem`): canonical identity、事实值、版本、代码和机器状态。

### Named Rules

**The Evidence Hierarchy Rule.** 先用字号、间距和 muted text 建立层级，再使用 accent；不要用全大写、超大标题或粗重装饰替代信息关系。

## Layout

整体是 workstation shell：桌面端使用约 `12.5rem` 的左侧 navigation rail、`3.5rem` 的 top bar、主 workspace 和底部约 `1.75rem` 的 status footer。主要内容通常限制在 `1180px`、`1560px` 或分析页的 `1920px` 内，并以 `1rem` 左右的 gap 组织密集面板。

研究分析页使用三列 `24fr / 52fr / 24fr`：左侧 market rail、中间证据工作区、右侧 recent rail。因子工作区使用约 `15rem` 的 catalog 加主 evidence workspace；sticky inspector、catalog 和 status footer 让上下文在长页面中保持可见。

响应式布局在现有实现中以 `1279px`、`1050px`、`1000px`、`767px` 和 `700px` 等边界逐步收窄列、折叠 rail、调整 padding，并保证最小宽度 `320px`。新页面应优先保留 evidence 的阅读顺序，再压缩边栏和次要装饰。中文文案可能更长，布局必须允许 label、identity 和错误信息换行。

## Elevation & Depth

系统默认不使用 ambient drop shadow。深度由 `bg` → `surface` → `surface-2` → `surface-3` 的 tonal layering、1px border 和局部 inset active marker 表达；现有 `box-shadow: inset 2px 0 var(--accent)` 只表示 active navigation state，不是浮层阴影。

### Named Rules

**The Flat Surface Rule.** 静止表面保持平面；只有明确的状态标记可以使用 inset accent，不能为普通卡片添加大范围阴影。

## Shapes

形状是小圆角、细边框、可预测的矩形工作单元。核心半径为 `8px`；密集 panel 常用 `6px`，button/input 常用 `7px`，analysis badge 和 pulse cell 常用 `4px`，状态 pill 使用 `999px`。边框通常为 `1px solid`，chart、pre、facts 和 catalog 需要清楚的 clipping 与 overflow 边界。

## Components

组件应像工作台工具：状态清楚、动作可预测、内容优先。

### Buttons

- **Shape:** 小圆角矩形，primary/button radius `7px`。
- **Primary:** 深青操作底 (`#0e7490`) + 白字，padding `0.55rem 0.85rem`；用于明确 command action。
- **Hover / Focus:** 保持 border 与表面差异；所有可聚焦控件使用 `3px solid #53c7f5` 的 focus ring，offset `3px`。
- **Secondary / Ghost:** transparent background、accent 或 muted text、细边框；只降低视觉权重，不改变语义。
- **Danger:** 使用深红底与粉红边框，仅用于真实危险或 destructive action。

### Chips

- **Style:** 状态 badge 使用 transparent 或对应的低对比 surface，`1px` border、`999px` radius、`0.3rem 0.55rem` padding。
- **State:** resolved/completed 使用绿色，resolving/running 使用 accent，cancel requested 使用 warning，failed/cancelled 使用 danger；颜色必须对应真实状态，不得把 UNKNOWN 或缺失证据显示成成功。

### Cards / Containers

- **Corner Style:** 默认 `8px`，密集分析 panel `6px`。
- **Background:** 使用 `surface`、`surface-2`、`surface-3` 的相邻色阶；内容区可回落到 `bg`。
- **Shadow Strategy:** 不使用大阴影，参照 Elevation & Depth 的 tonal layering。
- **Border:** `1px solid var(--line)` 或低强调的 `var(--line-soft)`。
- **Internal Padding:** 常用 `0.75rem`–`1rem`；页面级容器可用 `1.5rem`–`2rem`。

### Inputs / Fields

- **Style:** `#091524` field background、`#253449` border、`7px` radius、`0.8rem` padding。
- **Focus:** `3px solid #53c7f5` outline，offset `3px`；不要仅依赖颜色变化。
- **Error / Disabled:** error 使用 danger；disabled 保留布局并降低 opacity，不伪造成功状态。

### Navigation

- **Style:** 左侧 rail 使用 muted text、`0.65rem` padding 和 `6px` radius。
- **Hover:** 使用 `surface-2`，保持文字可读。
- **Active:** 使用 `accent-soft`、accent text 与左侧 `2px` inset marker；active 只说明当前位置，不表示业务成功。
- **Mobile:** 在窄屏逐步收窄或折叠 rail，不把 navigation 变成装饰性 hero。

### Evidence Surfaces

facts、pre、chart、table 与 inspector 是 signature surfaces：它们优先显示 provenance、identity、时间和状态，机器值使用 mono，长值允许换行或滚动；缺失、UNKNOWN 和 incomplete 必须保留其不确定性。

## Do's and Don'ts

### Do:

- **Do** 使用现有深色 token 和相邻 surface 色阶，优先靠边框与空间表达结构。
- **Do** 保持 accent 稀缺，把它留给操作、选择、焦点和可追踪关系。
- **Do** 为 interactive element 提供明确的 `3px` focus ring 和 `3px` offset。
- **Do** 用中文写面向操作者的 Web 文案；保留 `API token`、版本号、canonical identity 等明确技术语义。
- **Do** 在实现主题切换时提供等价的 light/dark token 集合，并让状态语义在两套主题中保持一致。
- **Do** 让证据、来源、identity、时间和不确定性在视觉上可区分。

### Don't:

- **Don't** 为普通卡片、页面或导航添加大范围 drop shadow、玻璃效果或无证据的装饰。
- **Don't** 把当前深色实现误当作已完成的 light/dark 双主题；浅色主题与切换仍是待实现要求。
- **Don't** 用 accent、success 或 bold copy 掩盖 UNKNOWN、缺失证据、incomplete 或 failed 状态。
- **Don't** 为了制造层级新增大标题、kicker、全大写 eyebrow 或展示型 hero；现有辅助标签是实现事实，不是新页面的默认装饰。
- **Don't** 让 Web 视觉暗示它拥有 Trading Authority；Web 只呈现状态、接收输入并提交正式 command。
