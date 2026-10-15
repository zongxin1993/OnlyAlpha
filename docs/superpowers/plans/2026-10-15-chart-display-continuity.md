# 图表显示与指标连续性实施计划

> Agent执行：使用subagent-driven-development串行实施，每任务限定审查，最后whole-branch审查。本文只保存建设顺序，不记录完成状态；Task Contract保留当前上下文，运行记录只放ignored test-results。

**Goal:** 六项已确认图表行为通过正式API和真实工作台可用。
**Architecture:** 复用既有native准入、有限closed batch、实例/请求世代和Lightweight Charts。时区/颜色/纵轴仅呈现；延迟由同一源实时观察投影，不改变数据和计算Authority。
**Tech:** 现有Python/FastAPI/DTO生成、React/TypeScript、Intl、Lightweight Charts、canonical dev_verification；不新增依赖。
**Spec:** docs/superpowers/specs/2026-10-15-chart-display-continuity-design.md

## Global Constraints

- Constitution Impact NO；L0只读，ADR0007/0094/0135/0138保持。
- 不导入旧Task3未提交内容、不执行此前拒绝的Source Revision补丁；不改持久格式、migration、quality、Compose、发行号，不自动merge/push。
- 2000闭合输入上限、SMA period1..10000、native目录/calendar/source/grant/process composition proofs保持；范围外不延长数值。
- 固定Decimal/ns真值；时间显示不改变查询或fingerprint；不能猜测缺失时间/能力/单位。
- 正式验证仅python3 -m scripts.dev_verification --web run(或Python lane)，单worker串行；禁止prepare/down/reset/prune/删卷，验证服务已绑定当前worktree。宿主仅编辑格式化/快速诊断。
- 单一实现者写源和跑runner；reviewer只读。所有证据/ledger在test-results/chart-display-continuity，不写仓库PASS状态。

## Review Focus

- 两实例之一失败/取消、focus、closed更新交错：另一已成功实例不丢失，取消不释放服务slot。
- native多曲线重复数据/添加/删除/拖动/分页：原生轴、Price/Volume和全部合法Study保持。
- 收到timestamp但缺真实Provider时间：不可用，不显示假0；重复/旧epoch/错误源不能更新当前遥测。
- 时区跨日/DST/存储异常：只有轴文字改变，两个Study的Query数和configuration不变。
- 未知/不同unit：独立纵轴，不挤压主图或重算/归一化；unit只能来自已准入输出。

### Task 1: 原生周期与多实例连续性

**Files:** application/chart_study_product_query.py/chart_study_input.py/chart_study_numeric.py/market_data_product.py及最近测试；HTTP chart_studies DTO/OpenAPI/generated；Web api/chartStudies/client、ChartStudies、WorkspacePage、TransientStudyPriceChart及对应tests/E2E。PriceChart只在真实renderer缺陷被证明时修改。
**Consumes:** 当前UI分支228b9fc3已验证renderer及16色；既有formal Source/read/native能力。
**Produces:** 所有当前native周期可证明的SMA输入准入；上下文切换保留实例；单已发批次+最新待处理意图；焦点新proof恢复及兄弟隔离。

1. 先通过真实Shipping UI复现SMA20+10后拖动，记录status/series/pane/viewport/请求失败边界；区分focus/容量/输入失效/原生renderer故障，不用猜测替代根因。
2. 在最近边界补/运行RED：15m→1m→15m保留两实例/参数/颜色，新数值来自新上下文；双SMA拖动/缩放/分页不撤有效结果；兄弟失败、cancel未释放slot、focus重新证明、迟到A回复不得挂回。
3. 优先复用已提交native/连续性实现f306804e、a20ac504、65714631。可cherry-pick并按真实冲突解决，保留228b9fc3的16色/原子renderer及精确测试，不复制旧工作树未提交代码。Provider版本/content、DTO生成和仓内消费者原子对应，不改SMA数学。
4. 只补当前组合被证明的缺陷。Current原生支持来自formal capability/catalog；数据不足/能力或权限拒绝有明确状态。单实例失败保留合法兄弟，共享无效性撤下相关值。
5. 正式affected Python/Ruff/format/mypy/generated/compatibility/nearest calculation/research-query与Web Vitest/lint/type/build/原生+genuine HTTP E2E；保存source digest和日志。bounded simplicity、独立重推导review后提交。

### Task 2: 纵轴、红绿量柱和显示时区

**Files:** PriceChart.tsx/CSS、studySeriesProjection.ts/studySeriesRenderer.ts、api/chartStudies/client的呈现证据适配、WorkspacePage.tsx、必要chartDisplayTime.ts；package内对应tests/native fixture/E2E。
**Consumes:** Task1稳定两实例/新周期；严格已准入series输出unit。
**Produces:** PRICE共享主图轴；其他/unknown独立pane；逐柱颜色；displayTimezone配置只供formatter。

1. RED证明SMA20/10共轴；controlled非PRICE/unknown单位独立轴不改变数字和主图；Volume up/down/doji/Preview颜色；UTC/AsiaShanghai/USER_LOCAL跨日、DST、损坏偏好/存储失败不发新Query。
2. 从正式已准入输出读取unit；保留fixture明确CONTROLLED证据语义，不猜指标名称，不新增其它计算。复用原生pane/scale，Price/Volume资源独立。未知单位/无有效结果明确状态。
3. Volume每点携带对应K线颜色，复用现有up/down token和蜡烛相等规则；保持exact volume hover。
4. 右下角native选择控件，默认UTC，常用三选项；使用Intl formatter，不平移timestamp。只改变axis tick/timeFormatter，观察栏仍UTC。有限本地display设置不保存数值/凭证；损坏或不可写时仍可选并提示。
5. 正式affected tests、lint/format/type/build、native三viewport E2E；轴/hover/overlay/pane/颜色完整断言，bounded simplicity与限定review后提交。

### Task 3: 真实入口时序观察与延迟显示

**Files:** Binance resource.py及tests；必要通用data/models.py观察载体；application/market_data_stream.py及tests；HTTP market_data/stream_schema.py、stream contract/generator/generated消费者；useMarketDataChart/WorkspacePage/必要marketDataTiming.ts与tests。
**Consumes:** Provider raw E/入口receive_ns现有证据；正式source/stream incarnation；Task2呈现布局。
**Produces:** 同一次实时native事件的可空真实provider_event_ns/ingress_received_ns观察和原子strict Product wire；当前上下文的两种ms显示。

1. 重新推导timing owning relation：Provider解析→同一inbound occurrence→当前source/key/incarnation→Product。缺E、REST历史、replay、derived无直接观察为不可用；canonical/clamped ts_init/ts_event不是原始观察。建立context内proof/state表。
2. RED涵盖明确正/零/负ns、缺E但旧模型fallback、缺接收、closed结束边界、错误源/标的/周期、旧epoch/reconnect、derived/历史无原始观察。数学subtract可显示，不能影响Bar规范化、identity、排序、WAL、closed admission。
3. 在Plugin提取provider-specific E；Core只承载通用明确可空时序观察。优先复用已有raw/preview/inbound关系，只补最小typed observation，禁止Core读取Binance原始字段或Web读内部存储。
4. 原子更新formal DTO/stream schema/generated TS/Zod/contract vectors及repo consumers；missing metadata不拒绝合法价格，不升级成0。compatibility分类按ADR0130，无legacy版本分叉/loader。
5. UI接收延迟=ingress−provider event，最近收盘到达延迟=该closed occurrence ingress−bar_end；exact ns先求差再显示ms，负值标时钟偏差，缺失—，断开显示最后样本，context变化撤下旧遥测。不开浏览器时钟替代入口，不新增timer判定事实。
6. 正式Provider/stream/HTTP/consumer tests、affected static/generated/compatibility、最近market-data canonical lane；确定性浏览器状态+真实Shipping observation检查。bounded simplicity和高风险独立relation/proof rederivation后提交。

### Task 4: 真实工作台验收与收尾

**Files:** 必要existing package E2E；不创建tracked状态/完成报告。
**Consumes:** 前三任务接口和验证，全部closed native/grant/format/resource边界。

1. 真实UI走BTC15m→SMA20/SMA10→拖动/缩放/分页→显隐/改色/独立pane→1m→15m；检查参数/实例保留、真实新周期结果和旧结果撤下，等待真实closed事件验证自动更新。
2. 实际量柱红绿、UTC/北京时间/本地只改变轴、最新正/缺失/clock-skew/disconnected延迟状态可发现；实际环境不能产生的异常用严格controlled evidence独立记录，不冒充真实市场PASS。
3. 必要全scope限定review，Constitution/兼容/quality检查；Critical/High为零、Required Behavior与适用验收通过后停止。源码和计划Git留存，不自动push/merge；本地dev只用canonical start/stop保留现有业务卷。
