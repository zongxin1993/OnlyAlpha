# 研究画面能力缺口盘点（2026-11）

Web UI 重设计 P2（画面重组）按细则**不接研究画面**：`/research/*` 维持「研究 · 未实现」Deferred 占位契约不动。本文把冻结稿 [frozen-2026-11-10 `#v-research`](frozen-2026-11-10/index.html) 的逐区块与现行 product-api v2 契约对照，标注每块离实现的距离，供后续阶段凭此清单立任务契约。**只盘点不实现**，本文不构成新的验收 Authority，具体行为以契约与源码为准。

## 方法与总体事实

- 契约权威：`contracts/product-api/v2/openapi.json`（138 个路径）；后端 `packages/backend/src/transport/routes.rs` 在装配时按响应分类操作——**仅声明 501 响应的操作判为 `Operation::Deferred`**（routes.rs:219-226），运行时一律返回 `501 PRODUCT_CAPABILITY_NOT_IMPLEMENTED`（transport/host.rs:388-394）。研究域 `/api/v2/research/**` 除少数操作外几乎全部 Deferred（共 38 个 501-only 端点）。
- 前端证据：`packages/frontend/src/api/`（privateAssets、research、chartStudies、workspace 各 client）；`src/api/research/schemas.ts:1-4` 注明 artifacts/statistics 系列 zod 校验器是**保留的证据阅读器，不为 Deferred 端点背书**。
- agent-api v1 与本画面无关（检索 `research|factor|statistic|dataset|snapshot|replay` 无匹配）。

## 区块 1：私有因子表（名称 / 实现版本 / 最近验证 / 状态三态 + 过滤与导入）

| 冻结稿元素 | 现有契约证据 | 结论 |
| --- | --- | --- |
| 因子列表·名称 | `GET /api/v2/private-assets`（routes.rs:622，`PrivateAssetRegistryDto`）与 `GET /api/v2/private-assets/factors` 编制清单（routes.rs:1421，`PrivateFactorAuthoringInventoryDto`）均已实现；`display.display_name` + `usage_summary` 供名称列（前端 `api/privateAssets/display.ts`） | **可复用** |
| 实现版本（`rust · 0.11.1`） | 修订有 `semantic_version`、`source_sha256`、`factor_api_contract_fingerprint`（`PrivateFactorRevisionDto`）；**后端内核 runtime 版本号**仅出现在研究准备上下文（`application/research_wire.rs:117 backend_version`），清单/登记册响应无此字段 | **可复用**（显示 `semantic_version`）；内核版本号列 = **QUERY_GAP**（字段级小缺口） |
| 最近验证时间 | 清单 DTO 逐行拼装仅含 `factor_id/display/display_fingerprint/has_draft/current_revision_fingerprint/current_display_version`（`persistence/private_factor_postgres.rs:54-79`）；私有因子迁移（0029/0055/0056）各表无任何 `_at`/`TIMESTAMPTZ` 时间戳列，时间戳只在 research_run 表（0073） | **QUERY_GAP**（需按因子聚合最新 run 时间，且受区块 3 列表端点缺口牵连） |
| 状态三态（已验证/验证中/缺输入证据） | 因子级无任何验证状态字段；最接近的三态语义全在 run 级：`report_status.state = VERIFIED|UNAVAILABLE|NOT_APPLICABLE`、`decision_provenance.state = VERIFIED|UNAVAILABLE|NOT_CHECKED`（`research_wire.rs:41-70`），且只能按单个 `run_id` 查询 | **QUERY_GAP**（缺「因子 × 最新研究状态」批量查询） |
| 「全部 / 已冻结版本」过滤 | 清单有 `current_revision_fingerprint: string|null` + `has_draft`；登记册只列已发布修订的当前 locator → 客户端可派生过滤 | **可复用** |
| 「导入因子」按钮 | 两步组合已完整：`PUT /api/v2/private-assets/factors/{id}/draft`（含 `initial_display` 首次建档，routes.rs:1445）→ `POST .../revisions` 发布冻结修订（routes.rs:1453）；`Idempotency-Key` 强制、命令对账 `GET .../commands/{command_id}`（routes.rs:1461）；前端已封装（`api/privateAssets/authoring.ts:147-195`） | **可复用**（无单独 import 端点，也无须新增；「导入」语义 = 存草稿 + 发布） |

## 区块 2：版本详情卡（标的 / 参数 / IC 均值 + t 值 / 输入指纹）

| 字段 | 现有契约证据 | 结论 |
| --- | --- | --- |
| 标的 | `GET /api/v2/research/runs/{run_id}` 已实现（routes.rs:872-878），`FactorResearchReport.instrument_id + timeframe_minutes` 与样本窗口可得（`research_wire.rs:73-87`） | **可复用** |
| 参数 | 修订 `parameter_contract`（`PrivateFactorRevisionDto`） | **可复用** |
| IC 均值 + t 值 | 统计内核只有两种关联度量：`enum Metric { Pearson, Spearman }`（`application/research_statistics.rs:24-29`）；结果结构 `Estimate`/`Analysis`（:74-99）无 t 值；openapi 与 crates 全量检索 `ic_mean|information.coefficient|t_stat|t_value` 零真实命中 | **QUERY_GAP（字段级，且需内核先具备 IC/t 统计能力，属计算内核扩展而非纯查询）** |
| 输入指纹链接 | 见区块 4 | **QUERY_GAP** |

SPA 页面路由 `/research/results/:id/statistics/:stat` 只是导航白名单条目（routes.rs:250-279），当前整页渲染 Deferred 占位（`src/app/router.tsx`）；其设想数据源 `GET /api/v2/research/statistics/{fp}`、`.../artifacts/{fp}/statistics`、`.../statistics/{fp}/series` 全部 Deferred（routes.rs:973 等），接通后供给的也是统计目录 + 滚动统计序列，而非 IC/t 汇总。

## 区块 3：运行记录时间线（重放通过 / 参数扫描进行中 / 已归档）

| 条目 | 现有契约证据 | 结论 |
| --- | --- | --- |
| 时间线列表 | `GET /api/v2/research/runs` 仅 501（routes.rs:840；routes.rs:1184-1190 测试断言 `Operation::Deferred`）。DB 已具备按因子聚合的数据基础（迁移 0061 对 `payload->>'factor_revision_fingerprint'` 建函数索引）——纯缺查询端点 | **QUERY_GAP** |
| 单 run 状态 | `GET /api/v2/research/runs/{run_id}` 已实现；状态机全集 `QUEUED/RUNNING/CANCEL_REQUESTED/COMPLETED/FAILED/CANCELLED`（`persistence/research_execution.rs:64-98`）+ `worker_observation`；取消 `POST .../cancellation` 已实现（routes.rs:880） | **可复用**（详情级） |
| 「确定性重放通过」 | 无重放端点；`GET .../runs/{id}/execution-evidence` Deferred（routes.rs:888）；契约里的 `replayed: bool` 是命令幂等回执语义（`research_wire.rs:271`），`determinism_fingerprint` 只在回测证据（前端 `api/research/schemas.ts:499,525`） | **QUERY_GAP** |
| 「参数扫描 #41 · 12/48」 | `POST /api/v2/research/search/parameter-experiments`、`.../advance`、`GET search/experiments/{fp}`、`/ledger`、`/terminal` 及 symbolic 同族全部 501 stub（routes.rs:941-950），crates/backend 无任何实现体 | **COMMAND_GAP + QUERY_GAP**（写读两缺） |
| 「已归档版本」 | `ARCHIVED` 生命周期只存在于数据源集成（`transport/wire.rs:1610-1628`）；因子版本与 run 均无归档语义 | **QUERY_GAP** |

## 区块 4：输入指纹链接（数据集快照引用）

- 专门查询端点已声明但 Deferred：`GET /api/v2/research/datasets/{snapshot_fingerprint}`（routes.rs:816，仅 501 响应）。周边 `catalog-context/*`、`.../readiness`、`catalog/dataset-fields|statistics|universes`、`runtime-generations/*` 也全部 501-only。
- **内部事实已存在**，只差正式读取路径：快照身份与指纹（`application/research_dataset/mod.rs:83-117`）、持久化校验 `Store.load(fingerprint) -> VerifiedDataset{manifest}`（`persistence/research_dataset/mod.rs:95-268`）、封板物化绑定 `onlyalpha.sealed-market-data`（`materialization.rs:202`）、研究规格与准入记录中的 `dataset_snapshot_fingerprint`（`host_research_preparation.rs:1022-1034`；`application/research_admission.rs:332`）。
- 前端无对应 client（`src/api` 检索无 fetch 调用），market-data 域亦无快照/封板端点。
- 结论：**QUERY_GAP**（端点 + 前端 client 双缺；数据侧事实完备，接通成本低、语义风险小）。

## 区块 5：「在图表中对照」按钮

- **以因子实现为对象——可复用**：`GET /api/v2/chart/studies/capabilities`、`POST /api/v2/chart/studies/evaluate`、`POST /api/v2/chart/temporary-studies/evaluate(-batch)` 均已实现；现行链路 `ChartStudies.tsx → CalculationPicker（类别 FACTOR 内嵌 FactorExplorerPage）→ TransientStudyPriceChart` 在跑，工作区布局经 `PUT /api/v2/workspace` 持久化。研究画面按钮可把选中修订的参数/输入映射为图表研究意图，走同一条 transient-studies 路径。
- **以研究结果证据序列为对象——QUERY_GAP**：`/api/v2/research/artifacts/{fp}/market|variables/…/signals/…/statistics/{fp}/series` 全部 Deferred；前端遗留阅读器（`api/research/queryKeys.ts:13-79`、`resultWorkspace.ts` 的 MARKET/STATISTICS/GRAPH 页签模型）属待接通资产，端点接通后即可复用。

## 汇总

| 冻结稿元素 | 结论 |
| --- | --- |
| 因子列表（名称、冻结过滤、导入两步） | **可复用** |
| 实现版本列（内核 runtime 版本号） | QUERY_GAP（字段） |
| 最近验证时间、因子级状态三态 | QUERY_GAP |
| IC 均值 / t 值 | QUERY_GAP（需统计内核扩展） |
| 标的、参数、单 run 状态详情 | **可复用** |
| 运行时间线列表、重放徽章、归档语义 | QUERY_GAP |
| 参数扫描（12/48 进行中） | COMMAND_GAP + QUERY_GAP |
| 输入指纹（数据集快照）链接 | QUERY_GAP（端点+client，数据侧完备） |
| 图表对照（因子实现） | **可复用**（transient-studies 链路） |
| 图表对照（结果证据序列） | QUERY_GAP（artifacts series 端点接通后可复用遗留阅读器） |

## 后续立任务的建议切分（供参考，非承诺）

1. **最小诚实版研究画面**：只上「可复用」块——因子表（名称/semantic_version/冻结过滤/导入）+ 版本详情（标的/参数）+ 单 run 详情。零后端改动，与 P2 数据/系统画面同法。
2. **查询补齐批**（QUERY_GAP）：run 列表、因子×最新验证状态聚合、数据集快照身份、artifacts 序列读取——各自是独立读端点的解冻/实现，按查询侧专项审查验收。
3. **写能力批**（COMMAND_GAP）：参数扫描实验族是最大的一块，涉及命令、账本与 worker，应单独立阶段走完整契约流程，不进「画面重组」类任务。
