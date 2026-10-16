import {
    useEffect,
    useEffectEvent,
    useLayoutEffect,
    useRef,
    useState,
    type ComponentProps
} from "react";
import { PriceChart } from "../../charts/lightweight/PriceChart";
import type { StudySeriesEvidence } from "../../charts/lightweight/studySeriesProjection";
import { useLocalReadCredentials, useMarketDataApi } from "../../app/providers";
import { MarketDataWebError } from "../../api/marketData/client";
import {
    readChartStudyCapabilities,
    readChartStudyEvidence,
    assertChartStudyHistory,
    ChartStudyWebError,
    type ChartStudyCapability
} from "../../api/chartStudies/client";
import type { ChartStudyEvaluateRequest } from "../../api/chartStudies/http.generated";
import { transientConfigurationErrors, type ChartStudyContext } from "./chartStudy";
import {
    onlyAssertMarketDataBarsAuthority,
    MarketDataBarsAuthorityMismatchError
} from "./marketDataBarsAuthority";
import "./TransientStudyPriceChart.css";

interface QueryState {
    readonly key: string;
    readonly evidence: readonly StudySeriesEvidence[];
    readonly status: string;
    readonly rejected: readonly string[];
    readonly failed: readonly string[];
}
function failureStatus(error: unknown): string {
    if (error instanceof MarketDataBarsAuthorityMismatchError) return "INVALID";
    if (!(error instanceof ChartStudyWebError) && !(error instanceof MarketDataWebError))
        return "UNAVAILABLE";
    return error.status === 401
        ? "UNAUTHORIZED"
        : error.status === 403
          ? "FORBIDDEN"
          : error.status === 409
            ? "STALE"
            : error instanceof MarketDataWebError
              ? "UNAVAILABLE"
              : error.status === 500 || error.code === "INVALID"
                ? "INVALID"
                : [
                        "UNSUPPORTED",
                        "CHART_STUDY_INPUT_UNSUPPORTED",
                        "MARKET_DATA_BAR_GRID_UNSUPPORTED"
                    ].includes(error.code)
                  ? "UNSUPPORTED"
                  : "UNAVAILABLE";
}
/** Shipping read-only consumer. Main-chart Acquisition and stream remain independent. */
export function TransientStudyPriceChart({
    context,
    dataGeneration,
    expectedSourceId,
    expectedEnvironment,
    previewStreamId = null,
    onTransientRevalidated,
    ...chart
}: ComponentProps<typeof PriceChart> & {
    readonly context: ChartStudyContext | null;
    readonly dataGeneration: string | null;
    readonly expectedSourceId: string | null;
    readonly expectedEnvironment: string | null;
    readonly previewStreamId?: string | null;
    readonly onTransientRevalidated?: (
        capability: ChartStudyCapability,
        instanceIds: readonly string[]
    ) => void;
}) {
    const [settled, setSettled] = useState(0);
    const [retry, setRetry] = useState<{ id: string | null } | null>(null);
    const credentials = useLocalReadCredentials();
    const marketApi = useMarketDataApi();
    const [state, setState] = useState<QueryState>({
        key: "",
        evidence: [],
        status: "NOT_CONNECTED",
        rejected: [],
        failed: []
    });
    // Only complete initial history plus admitted closes advances this anchor. Older
    // pages and Preview are deliberately absent from the calculation intent.
    const before = dataGeneration === null ? null : (chart.bars.at(-1)?.barEndNs ?? null);
    const intent = JSON.stringify(
        (chart.studies ?? []).map((instance) => ({
            id: instance.instanceId,
            configuration: instance.configuration,
            source: instance.selection.source
        }))
    );
    const key = JSON.stringify([
        context?.key,
        chart.incarnationKey,
        before,
        dataGeneration,
        expectedSourceId,
        expectedEnvironment,
        credentials.getGeneration(),
        intent,
        previewStreamId
    ]);
    const previewRevision = previewStreamId === null ? null : JSON.stringify(chart.liveBar);
    const live = useRef({ key, generation: 0, mounted: true });
    const work = useRef<{
        running: boolean;
        pending: boolean;
        retryId: string | null;
        controller: AbortController | null;
        timer: ReturnType<typeof setTimeout> | null;
        deferred: boolean;
    }>({
        running: false,
        pending: false,
        retryId: null,
        controller: null,
        timer: null,
        deferred: false
    });
    useLayoutEffect(() => {
        if (work.current.timer !== null) clearTimeout(work.current.timer);
        work.current.timer = null;
        work.current.deferred = false;
        live.current = { key, generation: live.current.generation + 1, mounted: true };
    }, [key]);
    useEffect(
        () => () => {
            live.current.mounted = false;
            ++live.current.generation;
            work.current.pending = false;
            if (work.current.timer !== null) clearTimeout(work.current.timer);
            work.current.timer = null;
            work.current.controller?.abort();
        },
        []
    );
    const querySnapshot = useEffectEvent(
        async (controller: AbortController, retryId: string | null) => {
            const generation = live.current.generation;
            const credentialGeneration = credentials.getGeneration();
            const current = () =>
                live.current.mounted &&
                live.current.key === key &&
                live.current.generation === generation &&
                credentials.getGeneration() === credentialGeneration &&
                !controller.signal.aborted;
            const update = (
                status: string,
                evidence: readonly StudySeriesEvidence[] = [],
                rejected: readonly string[] = [],
                failed: readonly string[] = []
            ) => {
                if (current()) {
                    setState({ key, status, evidence, rejected, failed });
                    // Withdrawing shared proof also retires every captured admission,
                    // including a previously displayed sibling retained for a retry.
                    if (status !== "QUERYING" && evidence.length === 0) ++live.current.generation;
                }
            };
            const selected = (chart.studies ?? []).filter(
                (instance) => instance.selection.source === "CHART_STUDY_TRANSIENT"
            );
            if (selected.length === 0) {
                update("NOT_CONNECTED");
                return;
            }
            if (dataGeneration === null) {
                update("INPUT_INCOMPLETE");
                return;
            }
            if (
                context === null ||
                chart.contextKey !== context.key ||
                before === null ||
                expectedSourceId === null ||
                expectedEnvironment === null ||
                context.source.expected_type_id === undefined
            ) {
                update("UNAVAILABLE");
                return;
            }
            const retained =
                retryId !== null && state.key === key
                    ? state.evidence.filter((row) => row.instanceId !== retryId)
                    : [];
            const rejected: string[] =
                retryId !== null && state.key === key
                    ? state.rejected.filter((row) => !row.startsWith(`${retryId}:`))
                    : [];
            const failed: string[] =
                retryId !== null && state.key === key
                    ? state.failed.filter((id) => id !== retryId)
                    : [];
            update("QUERYING", state.key === key ? state.evidence : retained, rejected, failed);
            try {
                const capabilities = await readChartStudyCapabilities(
                    credentials,
                    controller.signal
                );
                if (!current()) return;
                const supports = capabilities.map(
                    (capability) => capability.capability_projection.input_support
                );
                const formation = context.barSemantic.formation;
                if (
                    formation.kind !== "FIXED_DURATION" ||
                    supports.length === 0 ||
                    formation.alignment !== "SESSION_START" ||
                    formation.window_minutes !== formation.stride_minutes
                ) {
                    update("UNSUPPORTED");
                    return;
                }
                const sourceReference = {
                    ...context.source,
                    expected_type_id: context.source.expected_type_id
                };
                const window = {
                    anchor_kind: "BEFORE_TIME" as const,
                    before_ns: before,
                    target_bar_count: 2000
                };
                const history = await marketApi.queryBars(
                    context.source,
                    {
                        instrument_id: context.instrumentId,
                        bar_semantic: context.barSemantic,
                        ...window
                    },
                    controller.signal
                );
                if (!current()) return;
                onlyAssertMarketDataBarsAuthority(
                    {
                        reference: sourceReference,
                        expectedSourceId,
                        instrumentId: context.instrumentId,
                        barSemantic: context.barSemantic,
                        anchorKind: window.anchor_kind,
                        beforeNs: before,
                        targetBarCount: window.target_bar_count
                    },
                    history
                );
                if (history.source_selection.environment !== expectedEnvironment)
                    throw new ChartStudyWebError("INVALID");
                if (
                    supports.some((support) => history.resolution_mode !== support.resolution_mode)
                ) {
                    if (
                        history.resolution_mode === "DERIVED" &&
                        history.coverage.status === "COMPLETE" &&
                        history.resolution_plan_fingerprint !== null &&
                        history.calendar_fingerprint !== null &&
                        history.derived_projection_fingerprint !== null &&
                        history.aggregation_semantics_version !== null
                    ) {
                        update("UNSUPPORTED");
                        return;
                    }
                    throw new ChartStudyWebError("INVALID");
                }
                assertChartStudyHistory(
                    {
                        source_reference: sourceReference,
                        instrument_id: context.instrumentId,
                        bar_semantic: context.barSemantic,
                        window
                    },
                    expectedSourceId,
                    expectedEnvironment,
                    history
                );
                if (history.coverage.status === "INCOMPLETE") {
                    update("INPUT_INCOMPLETE");
                    return;
                }
                if (
                    history.coverage.status !== "COMPLETE" ||
                    history.history_projection_fingerprint === null
                ) {
                    update("UNAVAILABLE");
                    return;
                }
                // Compare exact currently plotted closed facts, not lossy renderer numbers
                // or a matching time/fingerprint. No second chart-history collection.
                const existing = new Map(chart.bars.map((bar) => [bar.barStartNs, bar]));
                for (const bar of history.bars) {
                    const plotted = existing.get(bar.bar_start_ns);
                    if (
                        plotted !== undefined &&
                        (plotted.barEndNs !== bar.bar_end_ns ||
                            plotted.open !== bar.open ||
                            plotted.high !== bar.high ||
                            plotted.low !== bar.low ||
                            plotted.close !== bar.close ||
                            plotted.volume !== bar.volume ||
                            plotted.closed !== bar.closed)
                    )
                        throw new ChartStudyWebError("INVALID");
                }
                if (
                    retained.some(
                        (row) =>
                            row.source.kind !== "CHART_STUDY_TRANSIENT" ||
                            row.source.historyProjectionFingerprint !==
                                history.history_projection_fingerprint ||
                            !capabilities.some(
                                (capability) =>
                                    row.source.kind === "CHART_STUDY_TRANSIENT" &&
                                    row.source.capabilityProjectionFingerprint ===
                                        capability.capability_projection_fingerprint
                            )
                    )
                ) {
                    update("STALE");
                    return;
                }
                const evidence: StudySeriesEvidence[] = [...retained];
                for (const instance of selected) {
                    if (retryId !== null && instance.instanceId !== retryId) continue;
                    if (instance.selection.source !== "CHART_STUDY_TRANSIENT") continue;
                    const capability = capabilities.find(
                        (candidate) =>
                            instance.selection.source === "CHART_STUDY_TRANSIENT" &&
                            candidate.type_id === instance.selection.capability.type_id &&
                            candidate.semantic_version ===
                                instance.selection.capability.semantic_version
                    );
                    if (capability === undefined) {
                        rejected.push(`${instance.instanceId}: UNAVAILABLE`);
                        continue;
                    }
                    // Revalidation preserves the exact originally selected type/version.
                    if (
                        instance.connectionState !== "STALE_CONFIG" &&
                        instance.selection.capability.capability_projection_fingerprint !==
                            capability.capability_projection_fingerprint
                    ) {
                        rejected.push(`${instance.instanceId}: STALE`);
                        continue;
                    }
                    const errors = transientConfigurationErrors(capability, instance.configuration);
                    if (errors.length > 0) {
                        rejected.push(`${instance.instanceId}: ${errors.join("；")}`);
                        continue;
                    }
                    const request: ChartStudyEvaluateRequest = {
                        schema_version: 2,
                        source_reference: sourceReference,
                        instrument_id: context.instrumentId,
                        bar_semantic: context.barSemantic,
                        window,
                        expected_history_projection_fingerprint:
                            history.history_projection_fingerprint,
                        calculation: {
                            kind: capability.kind,
                            type_id: capability.type_id,
                            semantic_version: capability.semantic_version,
                            typed_parameters: Object.fromEntries(
                                Object.entries(instance.configuration.parameters).filter(
                                    (
                                        entry
                                    ): entry is [
                                        string,
                                        Exclude<(typeof entry)[1], { type: "NULL" }>
                                    ] => entry[1].type !== "NULL"
                                )
                            ),
                            output_members: [...instance.configuration.outputNames],
                            expected_descriptor_fingerprint: capability.descriptor_fingerprint,
                            expected_implementation_fingerprint:
                                capability.implementation_fingerprint,
                            expected_capability_projection_fingerprint:
                                capability.capability_projection_fingerprint
                        },
                        include_unclosed_preview:
                            previewStreamId !== null && capability.presentation.preview_supported,
                        preview_stream_id: capability.presentation.preview_supported
                            ? previewStreamId
                            : null
                    };
                    try {
                        const result = await readChartStudyEvidence(
                            credentials,
                            request,
                            capability,
                            history,
                            {
                                instanceId: instance.instanceId,
                                chartContextKey: context.key,
                                incarnationKey: chart.incarnationKey ?? "",
                                configurationKey: JSON.stringify(instance.configuration)
                            },
                            current,
                            controller.signal
                        );
                        if (!current()) return;
                        if (result === null) {
                            update("INPUT_INCOMPLETE");
                            return;
                        }
                        evidence.push(...result);
                        onTransientRevalidated?.(capability, [instance.instanceId]);
                    } catch (error) {
                        if (!current()) return;
                        if (
                            error instanceof ChartStudyWebError &&
                            (error.status === 401 ||
                                error.status === 403 ||
                                error.status === 409 ||
                                ![
                                    "CHART_STUDY_CAPACITY_UNAVAILABLE",
                                    "CHART_STUDY_CAPACITY_EXCEEDED",
                                    "CHART_STUDY_REQUEST_INVALID",
                                    "CHART_STUDY_OUTPUT_INVALID",
                                    // Adapter/transport failure rejects this reply only;
                                    // it does not invalidate an independently admitted sibling.
                                    "INVALID",
                                    "UNAVAILABLE"
                                ].includes(error.code))
                        )
                            throw error;
                        rejected.push(
                            `${instance.instanceId}: ${error instanceof ChartStudyWebError ? error.code : failureStatus(error)}`
                        );
                        failed.push(instance.instanceId);
                    }
                }
                // Only exact admitted completions revalidate the presentation owner;
                // type/version/normalized parameters were proved by the client adapter.
                update(
                    rejected.length === 0
                        ? "DISPLAYABLE"
                        : evidence.length === 0
                          ? "REJECTED_CONFIG"
                          : "PARTIALLY_DISPLAYABLE",
                    evidence,
                    rejected,
                    failed
                );
            } catch (error) {
                if (!current()) return;
                if (
                    (error instanceof MarketDataWebError || error instanceof ChartStudyWebError) &&
                    error.code === "MARKET_DATA_WINDOW_NOT_CLOSED" &&
                    error.status === 503 &&
                    error.retryAfterSeconds !== null &&
                    !work.current.deferred
                ) {
                    work.current.deferred = true;
                    update("WAITING_FOR_CLOSED_WINDOW", [], [error.code]);
                    const waitingGeneration = live.current.generation;
                    const timer = setTimeout(() => {
                        if (
                            work.current.timer !== timer ||
                            !live.current.mounted ||
                            live.current.key !== key ||
                            live.current.generation !== waitingGeneration ||
                            credentials.getGeneration() !== credentialGeneration
                        )
                            return;
                        work.current.timer = null;
                        work.current.pending = true;
                        work.current.retryId = null;
                        setSettled((previous) => previous + 1);
                    }, error.retryAfterSeconds * 1000);
                    work.current.timer = timer;
                    return;
                }
                update(
                    failureStatus(error),
                    [],
                    error instanceof MarketDataWebError
                        ? [`${error.code}: ${error.message}`]
                        : error instanceof ChartStudyWebError
                          ? [error.code]
                          : []
                );
            }
        }
    );
    const pump = useEffectEvent(async () => {
        if (work.current.running || !work.current.pending || !live.current.mounted) return;
        work.current.running = true;
        work.current.pending = false;
        const retryId = work.current.retryId;
        work.current.retryId = null;
        const controller = new AbortController();
        work.current.controller = controller;
        try {
            await querySnapshot(controller, retryId);
        } finally {
            work.current.running = false;
            work.current.controller = null;
            // Do not abort/reissue on intent changes: disconnected HTTP work may
            // still hold a server slot. Wait for issued completion, then latest only.
            // React must commit this completion before a queued instance retry
            // captures the sibling evidence it must preserve.
            setSettled((previous) => previous + 1);
        }
    });
    useEffect(() => {
        if (work.current.timer !== null) return;
        work.current.pending = true;
        work.current.retryId = null;
        void pump();
    }, [key, previewRevision]);
    useEffect(() => {
        if (retry === null || (work.current.pending && work.current.retryId === null)) return;
        work.current.pending = true;
        work.current.retryId = retry.id;
        void pump();
    }, [retry]);
    useEffect(() => {
        void pump();
    }, [settled]);
    const active =
        state.key === key
            ? state
            : { key, evidence: [], status: "STALE", rejected: [], failed: [] };
    const hasTransient = (chart.studies ?? []).some(
        (instance) => instance.selection.source === "CHART_STUDY_TRANSIENT"
    );
    const partial =
        active.status === "PARTIALLY_DISPLAYABLE" ||
        active.evidence.some((row) => row.points.some((point) => point.readiness === "PARTIAL"));
    const statusCopy: Record<string, string> = {
        NOT_CONNECTED: "尚未连接指标",
        QUERYING: "正在加载指标…",
        DISPLAYABLE: partial ? "部分可用" : "指标已就绪",
        PARTIALLY_DISPLAYABLE: "部分可用",
        REJECTED_CONFIG: "指标配置不可用",
        INPUT_INCOMPLETE: "缺少已完成历史 K 线",
        WAITING_FOR_CLOSED_WINDOW: "等待 K 线时间窗口就绪 · 将自动重新查询一次",
        STALE: "指标已过期，请重新查询",
        UNAVAILABLE: "指标暂不可用",
        INVALID: "指标结果无效",
        UNAUTHORIZED: "请重新验证访问凭据",
        FORBIDDEN: "无权访问指标",
        UNSUPPORTED: "当前图表不支持此指标"
    };
    return (
        <div className="transient-study-chart">
            {hasTransient ? (
                <div className="transient-study-chart__status">
                    <div
                        role="status"
                        data-testid="chart-study-query-status"
                        data-query-status={active.status}
                    >
                        <span>{statusCopy[active.status] ?? "指标暂不可用"} · 仅供图表观察</span>
                        {active.evidence.length === 0 ? null : (
                            <span data-testid="chart-study-preview-status">
                                {active.evidence.some((row) => row.previewPoint !== undefined)
                                    ? "未收盘预览 · 仅供观察"
                                    : "未收盘预览：等待实时数据 · 已收盘结果可用"}
                            </span>
                        )}
                        <details className="transient-study-chart__details">
                            <summary>指标查询详情</summary>
                            <p>
                                {active.status === "INPUT_INCOMPLETE"
                                    ? "缺少已完成历史 K 线"
                                    : active.status === "WAITING_FOR_CLOSED_WINDOW"
                                      ? "等待 K 线时间窗口就绪 · 将自动重新查询一次"
                                      : active.status}{" "}
                                · DISPLAY_ONLY · 不是 Research Result
                                {active.rejected.length === 0
                                    ? null
                                    : ` · ${active.rejected.join("；")}`}
                                {active.evidence.some((row) =>
                                    row.points.some((point) => point.readiness === "PARTIAL")
                                )
                                    ? " · PARTIAL · 有限历史初始化窗口"
                                    : null}
                            </p>
                        </details>
                    </div>
                    {["UNAVAILABLE", "INVALID", "STALE", "INPUT_INCOMPLETE"].includes(
                        active.status
                    ) ? (
                        <button
                            type="button"
                            onClick={() => {
                                setRetry({ id: null });
                            }}
                        >
                            重新查询指标
                        </button>
                    ) : null}
                    {active.failed.map((id) => (
                        <button
                            type="button"
                            key={id}
                            onClick={() => {
                                setRetry({ id });
                            }}
                        >
                            重试指标 {id}
                        </button>
                    ))}
                </div>
            ) : null}
            <div className="transient-study-chart__plot">
                <PriceChart {...chart} studyEvidence={active.evidence} />
            </div>
        </div>
    );
}
