---
name: OnlyAlpha Web Console
description: A light, chart-centric professional workstation for a stateful quantitative system.
colors:
  bg: "#f8f8f5"
  surface: "#ffffff"
  surface-2: "#f1f1ec"
  surface-3: "#e9e9e2"
  text: "#20242b"
  muted: "#5f6874"
  accent: "#1f5f8b"
  accent-soft: "#e7eef4"
  accent-line: "#9dbdd3"
  line: "#e2e2dd"
  line-soft: "#eceae4"
  up: "#c8332a"
  down: "#2f7d47"
  stale: "#7a5c12"
  danger: "#a8322a"
  danger-line: "#d9a29c"
  warning: "#7a5c12"
  warning-line: "#d8c48a"
  success: "#24683f"
  success-line: "#9dc4ab"
  white: "#ffffff"
typography:
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.875rem"
    lineHeight: 1.5
  heading:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "1.05rem"
    fontWeight: 600
    letterSpacing: "-0.01em"
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.78rem"
    fontWeight: 600
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.78rem"
rounded:
  sm: "3px"
  md: "4px"
  lg: "6px"
  pill: "999px"
spacing:
  hairline: "1px"
  tight: "0.3rem"
  group: "0.75rem"
  section: "1.25rem"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.white}"
    rounded: "{rounded.lg}"
    padding: "0.55rem 0.85rem"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.accent}"
    rounded: "{rounded.lg}"
    padding: "0.55rem 0.85rem"
  button-subtle:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.lg}"
    padding: "0.45rem 0.7rem"
  toolbar-action:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "0.22rem 0.5rem"
  rail-button:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.md}"
    padding: "0"
  rail-button-active:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
    rounded: "{rounded.md}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "0.5rem 0.6rem"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "0.9rem"
  data-table:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "0"
    padding: "0.26rem 0.6rem"
  state-chip:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.pill}"
    padding: "0.3rem 0.55rem"
  synthetic-tag:
    backgroundColor: "transparent"
    textColor: "{colors.stale}"
    rounded: "{rounded.sm}"
    padding: "0 0.28rem"
---

# Design System: OnlyAlpha Web Console

## Overview

**Creative North Star: "Chart-Centric Workbench"**

OnlyAlpha 的 Web Console 是一张专业工作台，不是后台管理系统。图表是页面上唯一的视觉中心，顶栏、左侧工具条、右
侧上下文面板、底部研究面板与状态条围着它工作。视觉层级来自 1px 分隔线、相邻 surface 的极浅色阶和数值排版，而不
来自卡片、阴影或展示型排版。

世界是浅色的：近白工作纸承载面板，颜色只在它表达状态或数据时出现。这条浅色选择来自使用场景，不是分类默认值
——操作者长时间盯着行情、证据和 identity，深色终端与浅色工作纸都必须能承载，而本产品当前承诺的是浅色工作纸。

**Key Characteristics:**

- 图表是唯一焦点尺度；面板围着图表工作，不与它争夺注意力。
- 结构用 1px 分隔线和留白表达；除浮层外没有阴影，没有渐变，没有玻璃。
- 数值、时间戳、fingerprint 和状态值使用等宽数字；单位与列对齐靠 `tabular-nums`。
- 状态色只服务状态与数据；`UNKNOWN`、stale 与缺失保留其不确定性，不被 accent 或 success 掩盖。
- 操作者文案使用中文；canonical identity 与技术名词保留英文。

## Colors

### Neutral

近白工作纸与极浅面板色阶：`bg #f8f8f5`、`surface #ffffff`、`surface-2 #f1f1ec`、`surface-3 #e9e9e2`，分隔线
`line #e2e2dd` 与 `line-soft #eceae4`，正文 `text #20242b`，次要文字 `muted #5f6874`。

### Accent

`accent #1f5f8b` 只用于操作、选中与焦点；`accent-soft #e7eef4` 承载选中态背景，`accent-line #9dbdd3` 用于需要边框
的选中控件。

### Semantic States

涨 `up #c8332a`、跌 `down #2f7d47`、过期/未知 `stale #7a5c12`、失败 `danger #a8322a`、告警 `warning #7a5c12`、
完成/连接正常 `success #24683f`。每个状态色都配一条同色系线色用于 chips 边框，保证在浅底上仍有 ≥4.5:1 对比度。

### Named Rules

- **状态色不得转为装饰。** 涨跌颜色只能出现在价格与涨跌幅上，不得用来强调标题、按钮或面板。
- **accent 稀缺。** 一屏内 accent 只出现在一处主要操作、当前选中和 focus ring。
- **不加第二个色板。** 新页面复用这些 token；需要新颜色时先问它是否真的是一个新状态。

## Typography

### Hierarchy

- 页面标题 `1.05rem / 600`，紧接正文；不使用巨大的展示标题。
- 正文 `0.875rem / 1.5`；说明文字 `0.82rem` muted。
- 标签与表头 `0.78rem / 600`，句首大写，**不使用全大写、不加字距**。
- 数值、时间、fingerprint：等宽 0.78rem，配 `tabular-nums`。

### Named Rules

- **一个家族。** UI 使用 Inter（含系统栈回退），只有代码、数值、identity 使用等宽。
- **数字有嗓音。** 表格、统计、图表刻度与 identity 一律等宽或表格数字，保证纵向可比。
- **不要 kicker。** 标题自带权重；标题上方不允许出现全大写 eyebrow 或栏目标签。

## Layout

应用外壳是持久的两行 + 工作区：40px 顶栏（品牌、产品导航、工作区动作）→ 工作区 → 28px 状态条。

主工作区（路由 `/`）是四区网格：

~~~text
左 48px 工具条 | 主图（填满剩余宽高） | 右 320px 上下文面板
               | 底部 ~240px 可折叠研究面板
~~~

断点行为：1280–1920 全功能；`<1280px` 左工具条可收成窄条、右面板转为抽屉（由图表区标题栏的按钮打开）、底
部面板可收起为标签行；`<900px` 隐藏顶栏模式文字并允许产品导航横向滚动。移动端功能对齐不在范围内。

### Named Rules

- **图表先分空间。** 面板尺寸固定，图表吃掉剩余空间；不要让面板挤压图表。
- **密度优先。** 表格行高紧凑，列头 muted，数值右对齐或等宽对齐。
- **折叠要有出口。** 任何可折叠面板都保留可见的展开控件，且键盘可达。

## Elevation & Depth

没有 elevation 系统。层次只由 1px 分隔线、surface 色阶和留白产生；只有浮层（下拉、抽屉）允许一层柔和阴影。

### Named Rules

- **不要卡片堆叠。** 面板是 1px 边框的工作区，不是悬浮卡片；面板内不再套一层卡片。
- **不要用阴影表示层级。** 需要区分层级时，用分隔线或底色的一个色阶。

## Shapes

圆角上限 6px：控件 4px，输入 6px，tag 3px，chip 为 pill。没有装饰性几何、没有渐变、没有玻璃。

## Components

### Buttons

主要按钮 `accent` 底 + 白字；次要按钮透明底 + accent 文字 + 1px 边框；quiet/subtle 用于低频动作。所有按钮共享
`3px accent` focus ring 与 `3px` offset，禁用态降低不透明度并保持可读。

### Chips

运行状态 chip 使用 pill 形状 + 同色系边框（完成 / 运行中 / 失败 / 未知）。`UNKNOWN`、`stale`、`incomplete` 必须保持
其不确定性，不得被渲染成成功或失败。

### Tables

表格是主要数据载体：句首大写列头、muted、sticky；行高紧凑；数值列等宽；hover 用 `surface-2`。表格是权威事实
的投影，不在浏览器内重算。

### Panels and Containers

面板 = 1px 边框 + `surface` 底 + 4px 圆角 + 0.9rem 内距。面板内使用分隔线分区，不嵌套卡片容器。

### Inputs / Fields

输入框 `surface` 底、1px `line` 边框、6px 圆角；label 句首大写，错误信息紧邻字段并用 danger 色说明问题与恢复方式。

### Navigation

产品导航在顶栏，是紧凑文字链接：默认 muted，hover 用 `surface-2`，当前项用 `accent-soft` + accent 文字。左
侧工具条是图表工具，不是站点导航。

### Workspace Toolbar and Rail

图表区标题栏承载 symbol、时间周期与面板开关；工具条只放与图表相关的工具，图标使用统一的 1.5px 描边 SVG，
按钮 32×32，选中态 `accent-soft`。工具条与底部面板都只有图标按钮折叠，且 `aria-expanded` 与真实状态一致。

### Evidence Surfaces

facts、chart、table 与 inspector 仍是 signature surfaces：优先显示 provenance、identity、时间和状态，机器值使用
等宽，长值允许换行或滚动。占位或演示数据必须标注 `synthetic`。

### Chart

金融时间序列使用 TradingView Lightweight Charts（ADR 0094/0135），配色从 token 读取：浅底、`line-soft` 网格、
涨跌色来自 `up`/`down`。渲染器边界不得在功能实现中被替换。

## Do's and Don'ts

### Do:

- **Do** 用 1px 分隔线、留白和一个色阶表达层级。
- **Do** 让图表成为唯一焦点尺度，面板围着它工作。
- **Do** 让数值、时间与 identity 使用等宽数字并纵向对齐。
- **Do** 为所有交互元素提供 `3px` focus ring 与 `3px` offset，并保持键盘可达。
- **Do** 在折叠、抽屉、空态、加载、失败与 degraded 状态下保留明确出口与不确定性。
- **Do** 标注 `synthetic` 演示数据；权威事实一律来自服务端 Product API。

### Don't:

- **Don't** 在标题上方加全大写 eyebrow、kicker 或栏目标签。
- **Don't** 使用展示型大标题、巨大 Hero、渐变文字或玻璃拟态。
- **Don't** 堆叠卡片或在面板里再套卡片；不要用阴影制造层级。
- **Don't** 把 accent 或 success 用作装饰，也不要让它们掩盖 `UNKNOWN`、stale 或 incomplete。
- **Don't** 为普通数据面板加圆角超过 6px 的容器或彩色侧边条。
- **Don't** 让 Web 视觉暗示它拥有 Trading / Research Authority；Web 只呈现状态、接收输入并提交正式 command。

## Surfaces

当前已实现的首个 Product Vertical Slice 是 W0 chart-centric workspace shell（路由 `/` 加持久外壳），其 surface
brief 与 direction contract 位于 `.impeccable/surfaces/packages-onlyalpha-web-console.md`。旧世界（深色 Evidence
Workbench）已被替换，仓库内不再保留其视觉语言。
