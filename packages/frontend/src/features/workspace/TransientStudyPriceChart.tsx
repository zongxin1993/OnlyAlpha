import { createPortal } from "react-dom";
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
import { useLocalReadCredentials } from "../../app/providers";
import { MarketDataWebError } from "../../api/marketData/client";
import {
    isAdmittedChartStudyEvidence,
    readChartStudyCapabilities,
    readTemporaryChartStudyBatchEvidence,
    type TemporaryChartStudyBatchIntent,
    ChartStudyWebError,
    type ChartStudyCapability
} from "../../api/chartStudies/client";
import type { TemporaryChartStudyEvaluateRequest } from "../../api/chartStudies/http.generated";
import { transientConfigurationErrors, type ChartStudyContext } from "./chartStudy";
import { MarketDataBarsAuthorityMismatchError } from "./marketDataBarsAuthority";
import { readTemporaryMarketData } from "../../api/marketData/temporary";
import "./TransientStudyPriceChart.css";

interface Occurrence {
    key: string;
    evidence: readonly StudySeriesEvidence[];
}
/** Presentation continuity only: all overlapping exact closed facts must agree. */
function appendedCloses(
    previous: ComponentProps<typeof PriceChart>["bars"],
    next: ComponentProps<typeof PriceChart>["bars"]
): boolean {
    const last = previous.at(-1);
    if (last === undefined) return false;
    const index = next.findIndex((bar) => bar.barStartNs === last.barStartNs);
    if (index < 0 || index === next.length - 1) return false;
    const old = new Map(previous.map((bar) => [bar.barStartNs, bar]));
    for (const [position, bar] of next.entries()) {
        const prior = old.get(bar.barStartNs);
        if (
            position <= index &&
            (prior?.barEndNs !== bar.barEndNs ||
                prior.open !== bar.open ||
                prior.high !== bar.high ||
                prior.low !== bar.low ||
                prior.close !== bar.close ||
                prior.volume !== bar.volume ||
                !bar.closed)
        )
            return false;
        if (position > index && (!bar.closed || next[position - 1]?.barEndNs !== bar.barStartNs))
            return false;
    }
    return true;
}
interface QueryState {
    readonly key: string;
    readonly evidence: readonly StudySeriesEvidence[];
    readonly status: string;
    readonly rejected: readonly string[];
    readonly failed: readonly string[];
}
function failureStatus(error: unknown): string {
    if (
        error instanceof MarketDataBarsAuthorityMismatchError ||
        (error instanceof MarketDataWebError &&
            ["MARKET_DATA_TEMPORARY_RESPONSE_MISMATCH", "CONTRACT_ERROR"].includes(error.code))
    )
        return "INVALID";
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
function occurrenceAdmission(
    live: { current: { mounted: boolean } },
    admitted: { current: Map<string, { key: string; evidence: readonly StudySeriesEvidence[] }> },
    instanceId: string,
    occurrence: Occurrence,
    lagging: { current: Map<string, Occurrence> }
): () => boolean {
    return () =>
        live.current.mounted &&
        (admitted.current.get(instanceId) === occurrence ||
            lagging.current.get(instanceId) === occurrence);
}
/** Shipping display consumer. Only closed temporary inputs enter indicator calculation. */
export function TransientStudyPriceChart({
    context,
    dataGeneration,
    expectedSourceId,
    expectedEnvironment,
    pageId,
    onTransientRevalidated,
    continuityReady = true,
    statusTarget,
    ...chart
}: ComponentProps<typeof PriceChart> & {
    readonly statusTarget?: HTMLElement | null;
    readonly context: ChartStudyContext | null;
    readonly dataGeneration: string | null;
    readonly expectedSourceId: string | null;
    readonly expectedEnvironment: string | null;
    readonly pageId: string;
    readonly continuityReady?: boolean;
    readonly onTransientRevalidated?: (
        capability: ChartStudyCapability,
        instanceIds: readonly string[]
    ) => void;
}) {
    const [settled, setSettled] = useState(0);
    const [retry, setRetry] = useState<{ id: string | null } | null>(null);
    const credentials = useLocalReadCredentials();
    const [state, setState] = useState<QueryState>({
        key: "",
        evidence: [],
        status: "NOT_CONNECTED",
        rejected: [],
        failed: []
    });
    // Initial temporary inputs plus admitted closes advance this anchor. Older
    // pages and Preview are deliberately absent from the calculation intent.
    const before = dataGeneration === null ? null : (chart.bars.at(-1)?.barEndNs ?? null);
    const intent = JSON.stringify(
        (chart.studies ?? []).map((instance) => ({
            id: instance.instanceId,
            configuration: instance.configuration,
            selection: instance.selection
        }))
    );
    const inputKey = JSON.stringify([
        context?.key,
        chart.incarnationKey,
        before,
        dataGeneration,
        expectedSourceId,
        expectedEnvironment,
        credentials.getGeneration(),
        pageId,
        continuityReady
    ]);
    const key = JSON.stringify([
        inputKey,
        intent,
        (chart.studies ?? []).map((row) => row.connectionState === "STALE_CONFIG")
    ]);
    const continuityBinding = JSON.stringify([
        context,
        chart.contextKey,
        chart.incarnationKey,
        dataGeneration,
        expectedSourceId,
        expectedEnvironment,
        credentials.getGeneration(),
        pageId,
        intent,
        (chart.studies ?? []).map((row) => row.connectionState === "STALE_CONFIG"),
        continuityReady
    ]);
    const [previousWindow, setPreviousWindow] = useState<{
        binding: string;
        key: string;
        bars: typeof chart.bars;
        before: string | null;
        lagBefore: string | null;
        lagEvidence: readonly StudySeriesEvidence[];
    } | null>(null);
    const canContinue =
        continuityReady &&
        dataGeneration !== null &&
        previousWindow?.binding === continuityBinding &&
        appendedCloses(previousWindow.bars, chart.bars);
    const lagging = useRef(new Map<string, Occurrence>());
    const selectionKey = JSON.stringify([
        context?.key,
        chart.incarnationKey,
        expectedSourceId,
        expectedEnvironment,
        credentials.getGeneration(),
        pageId,
        (chart.studies ?? []).map((instance) => [instance.instanceId, instance.selection])
    ]);
    const verifiedSelection = useRef<string | null>(null);
    // At most one admitted result per currently selected instance. Configuration
    // or input departures retire the occurrence, including an A→B→A restoration.
    const admitted = useRef(
        new Map<
            string,
            {
                key: string;
                evidence: readonly StudySeriesEvidence[];
            }
        >()
    );
    const instanceKey = (instance: NonNullable<typeof chart.studies>[number]) =>
        JSON.stringify([inputKey, instance.configuration, instance.selection]);
    const live = useRef({ key, generation: 0, mounted: true });
    const work = useRef<{
        running: boolean;
        pending: boolean;
        retryId: string | null;
        controller: AbortController | null;
        timer: ReturnType<typeof setTimeout> | null;
        timerKind: "CLOSED_WINDOW" | null;
        deferred: boolean;
    }>({
        running: false,
        pending: false,
        retryId: null,
        controller: null,
        timer: null,
        timerKind: null,
        deferred: false
    });
    const retireAdmissions = useEffectEvent(() => {
        for (const [id, entry] of admitted.current) {
            const instance = chart.studies?.find((row) => row.instanceId === id);
            if (instance === undefined || entry.key !== instanceKey(instance))
                admitted.current.delete(id);
        }
    });
    const advanceWindow = useEffectEvent(() => {
        if (canContinue) {
            for (const [id, occurrence] of admitted.current)
                if (occurrence.evidence.length > 0) lagging.current.set(id, occurrence);
        } else lagging.current.clear();
        setPreviousWindow({
            binding: continuityBinding,
            key,
            bars: chart.bars,
            before,
            lagBefore: canContinue ? (previousWindow.lagBefore ?? previousWindow.before) : null,
            lagEvidence: [...lagging.current.values()].flatMap((row) => row.evidence)
        });
    });
    useLayoutEffect(() => {
        advanceWindow();
        retireAdmissions();
        if (work.current.timer !== null) clearTimeout(work.current.timer);
        work.current.timer = null;
        work.current.timerKind = null;
        work.current.deferred = false;
        live.current = { key, generation: live.current.generation + 1, mounted: true };
    }, [key]);
    useEffect(
        () => () => {
            live.current.mounted = false;
            lagging.current.clear();
            ++live.current.generation;
            work.current.pending = false;
            if (work.current.timer !== null) clearTimeout(work.current.timer);
            work.current.timer = null;
            work.current.timerKind = null;
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
                    if (status !== "QUERYING") {
                        lagging.current.clear();
                        setPreviousWindow((previous) =>
                            previous === null
                                ? null
                                : { ...previous, lagBefore: null, lagEvidence: [] }
                        );
                    }
                    setState({ key, status, evidence, rejected, failed });
                    if (status !== "QUERYING" && evidence.length > 0)
                        verifiedSelection.current = selectionKey;
                    // Withdrawing shared proof also retires every captured admission,
                    // including a previously displayed sibling retained for a retry.
                    if (status !== "QUERYING" && evidence.length === 0) {
                        admitted.current.clear();
                        verifiedSelection.current = null;
                        ++live.current.generation;
                    }
                }
            };
            const selected = (chart.studies ?? []).filter(
                (instance) => instance.selection.source === "CHART_STUDY_TRANSIENT"
            );
            if (selected.length === 0) {
                update("NOT_CONNECTED");
                return;
            }
            if (dataGeneration === null || !continuityReady) {
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
                // Parameter or closed-window changes can prove the unchanged
                // whole catalog through their new canonical evaluation. The adapter verifies that
                // reply's catalog generation, provider, invocation and capability;
                // local metadata alone never authorizes a sibling cache hit.
                const capabilitiesFresh = !(
                    retryId === null &&
                    verifiedSelection.current === selectionKey &&
                    selected.every((instance) => instance.connectionState !== "STALE_CONFIG") &&
                    selected.some(
                        (instance) =>
                            instance.selection.source === "CHART_STUDY_TRANSIENT" &&
                            (admitted.current.get(instance.instanceId)?.evidence.length ?? 0) ===
                                0 &&
                            transientConfigurationErrors(
                                instance.selection.capability,
                                instance.configuration
                            ).length === 0
                    )
                );
                const capabilities = capabilitiesFresh
                    ? await readChartStudyCapabilities(credentials, controller.signal)
                    : selected.flatMap((instance) =>
                          instance.selection.source === "CHART_STUDY_TRANSIENT"
                              ? [instance.selection.capability]
                              : []
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
                const history = await readTemporaryMarketData(
                    credentials,
                    context.source,
                    {
                        instrument_id: context.instrumentId,
                        bar_semantic: context.barSemantic,
                        ...window
                    },
                    pageId,
                    controller.signal
                );
                if (!current()) return;
                if (
                    history.source_selection.source_id !== expectedSourceId ||
                    history.source_selection.environment !== expectedEnvironment
                )
                    throw new ChartStudyWebError("INVALID");
                if (history.coverage.status !== "COMPLETE") {
                    update("INPUT_INCOMPLETE");
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
                            row.source.kind !== "CHART_STUDY_TEMPORARY" ||
                            row.source.windowFingerprint !== history.window_fingerprint ||
                            !capabilities.some(
                                (capability) =>
                                    row.source.kind === "CHART_STUDY_TEMPORARY" &&
                                    row.source.capabilityProjectionFingerprint ===
                                        capability.capability_projection_fingerprint
                            )
                    )
                ) {
                    update("STALE");
                    return;
                }
                const evidence: StudySeriesEvidence[] = [...retained];
                const verifiedCatalogs = new Set<string>();
                const queryOrder = capabilitiesFresh
                    ? selected
                    : [...selected].sort(
                          (a, b) =>
                              Number(
                                  (admitted.current.get(a.instanceId)?.evidence.length ?? 0) > 0
                              ) -
                              Number((admitted.current.get(b.instanceId)?.evidence.length ?? 0) > 0)
                      );
                const pending: {
                    intent: TemporaryChartStudyBatchIntent;
                    instanceId: string;
                    occurrence: { key: string; evidence: readonly StudySeriesEvidence[] };
                }[] = [];
                const reject = (instanceId: string, error: unknown) => {
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
                                "INVALID",
                                "UNAVAILABLE"
                            ].includes(error.code))
                    )
                        throw error;
                    rejected.push(
                        `${instanceId}: ${error instanceof ChartStudyWebError ? error.code : failureStatus(error)}`
                    );
                    failed.push(instanceId);
                };
                const flush = async (): Promise<boolean> => {
                    if (pending.length === 0) return true;
                    const batch = pending.splice(0);
                    let results;
                    try {
                        results = await readTemporaryChartStudyBatchEvidence(
                            credentials,
                            batch.map((item) => item.intent),
                            history,
                            current,
                            controller.signal
                        );
                    } catch (error) {
                        if (!current()) return false;
                        for (const item of batch) reject(item.instanceId, error);
                        return true;
                    }
                    if (!current()) return false;
                    if (
                        results.some(
                            (result) => result.status === "EVALUATED" && result.evidence === null
                        )
                    ) {
                        update("INPUT_INCOMPLETE");
                        return false;
                    }
                    for (const [index, item] of batch.entries()) {
                        const result = results[index];
                        if (result === undefined) throw new ChartStudyWebError("INVALID");
                        if (result.status === "REJECTED") {
                            reject(item.instanceId, result.error);
                            continue;
                        }
                        if (result.evidence === null) throw new ChartStudyWebError("INVALID");
                        const capability = item.intent.capability;
                        verifiedCatalogs.add(
                            JSON.stringify([
                                capability.catalog_generation_fingerprint,
                                capability.invocation_implementation_fingerprint
                            ])
                        );
                        item.occurrence.evidence = result.evidence;
                        evidence.push(...result.evidence);
                        onTransientRevalidated?.(capability, [item.instanceId]);
                    }
                    return true;
                };
                for (const instance of queryOrder) {
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
                        admitted.current.delete(instance.instanceId);
                        rejected.push(`${instance.instanceId}: UNAVAILABLE`);
                        continue;
                    }
                    // Revalidation preserves the exact originally selected type/version.
                    if (
                        instance.connectionState !== "STALE_CONFIG" &&
                        instance.selection.capability.capability_projection_fingerprint !==
                            capability.capability_projection_fingerprint
                    ) {
                        admitted.current.delete(instance.instanceId);
                        rejected.push(`${instance.instanceId}: STALE`);
                        continue;
                    }
                    const errors = transientConfigurationErrors(capability, instance.configuration);
                    if (errors.length > 0) {
                        admitted.current.delete(instance.instanceId);
                        rejected.push(`${instance.instanceId}: ${errors.join("；")}`);
                        continue;
                    }
                    const cached = admitted.current.get(instance.instanceId);
                    // A changed calculation must first prove the current catalog before
                    // unchanged siblings can reuse independently admitted evidence.
                    if (
                        !capabilitiesFresh &&
                        cached !== undefined &&
                        cached.evidence.length > 0 &&
                        pending.length > 0 &&
                        !(await flush())
                    )
                        return;
                    if (
                        retryId === null &&
                        cached !== undefined &&
                        cached.evidence.length > 0 &&
                        (capabilitiesFresh ||
                            verifiedCatalogs.has(
                                JSON.stringify([
                                    capability.catalog_generation_fingerprint,
                                    capability.invocation_implementation_fingerprint
                                ])
                            )) &&
                        cached.evidence.every(
                            (row) =>
                                isAdmittedChartStudyEvidence(row) &&
                                row.source.kind === "CHART_STUDY_TEMPORARY" &&
                                row.source.windowFingerprint === history.window_fingerprint &&
                                row.source.capabilityProjectionFingerprint ===
                                    capability.capability_projection_fingerprint
                        )
                    ) {
                        evidence.push(...cached.evidence);
                        onTransientRevalidated?.(capability, [instance.instanceId]);
                        continue;
                    }
                    const occurrence = {
                        key: instanceKey(instance),
                        evidence: [] as readonly StudySeriesEvidence[]
                    };
                    admitted.current.set(instance.instanceId, occurrence);
                    const request: TemporaryChartStudyEvaluateRequest = {
                        schema_version: 2,
                        source_kind: "TEMPORARY_MARKET_DATA",
                        page_id: pageId,
                        source_reference: sourceReference,
                        instrument_id: context.instrumentId,
                        bar_semantic: context.barSemantic,
                        window,
                        expected_window_fingerprint: history.window_fingerprint,
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
                        }
                    };
                    const instanceId = instance.instanceId;
                    pending.push({
                        instanceId,
                        occurrence,
                        intent: {
                            request,
                            capability,
                            binding: {
                                instanceId,
                                chartContextKey: context.key,
                                incarnationKey: chart.incarnationKey ?? "",
                                configurationKey: JSON.stringify(instance.configuration)
                            },
                            admissionCurrent: occurrenceAdmission(
                                live,
                                admitted,
                                instanceId,
                                occurrence,
                                lagging
                            )
                        }
                    });
                    if (pending.length === 4 && !(await flush())) return;
                }
                if (!(await flush())) return;

                evidence.sort(
                    (a, b) =>
                        selected.findIndex((row) => row.instanceId === a.instanceId) -
                        selected.findIndex((row) => row.instanceId === b.instanceId)
                );
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
                        work.current.timerKind = null;
                        work.current.pending = true;
                        work.current.retryId = null;
                        setSettled((previous) => previous + 1);
                    }, error.retryAfterSeconds * 1000);
                    work.current.timer = timer;
                    work.current.timerKind = "CLOSED_WINDOW";
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
        if (
            work.current.running ||
            !work.current.pending ||
            !live.current.mounted ||
            work.current.timer !== null
        )
            return;
        // Key changes replace this object, including an A→B→A occurrence.
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
        if (work.current.timerKind === "CLOSED_WINDOW") return;
        work.current.pending = true;
        work.current.retryId = null;
        void pump();
    }, [key]);
    useEffect(() => {
        if (retry === null) return;
        if (!(work.current.pending && work.current.retryId === null)) {
            work.current.pending = true;
            work.current.retryId = retry.id;
        }
        void pump();
    }, [retry]);
    useEffect(() => {
        void pump();
    }, [settled]);
    const pendingEvidence =
        canContinue && state.evidence.length > 0
            ? state.evidence
            : (previousWindow?.lagEvidence ?? []);
    const continuing =
        continuityReady &&
        previousWindow?.binding === continuityBinding &&
        (canContinue || previousWindow.key === key) &&
        pendingEvidence.length > 0 &&
        (state.key !== key || state.status === "QUERYING");
    const calculationCutoff = previousWindow?.lagBefore ?? previousWindow?.before ?? "0";
    const active = continuing
        ? { key, evidence: pendingEvidence, status: "UPDATING", rejected: [], failed: [] }
        : state.key === key
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
        UPDATING: `计算至 ${new Date(Number(BigInt(calculationCutoff) / 1_000_000n)).toISOString()} · 更新中`,
        DISPLAYABLE: partial ? "部分可用" : "指标已就绪",
        PARTIALLY_DISPLAYABLE: "部分可用",
        REJECTED_CONFIG: "指标配置不可用",
        INPUT_INCOMPLETE: "临时闭合 K 线不足",
        WAITING_FOR_CLOSED_WINDOW: "等待 K 线时间窗口就绪 · 将自动重新查询一次",
        STALE: "指标已过期，请重新查询",
        UNAVAILABLE: "指标暂不可用",
        INVALID: "指标结果无效",
        UNAUTHORIZED: "请重新验证访问凭据",
        FORBIDDEN: "无权访问指标",
        UNSUPPORTED: "当前图表不支持此指标"
    };
    const attention =
        (state.key === key &&
            [
                "REJECTED_CONFIG",
                "INPUT_INCOMPLETE",
                "STALE",
                "UNAVAILABLE",
                "INVALID",
                "UNAUTHORIZED",
                "FORBIDDEN",
                "UNSUPPORTED"
            ].includes(active.status)) ||
        active.failed.length > 0;
    const queryStatus = hasTransient ? (
        <div className="transient-study-chart__status">
            <div
                role="status"
                data-testid="chart-study-query-status"
                data-query-status={active.status}
            >
                <span>{statusCopy[active.status] ?? "指标暂不可用"} · 仅供图表观察</span>
                {active.evidence.length === 0 ? null : (
                    <span data-testid="chart-study-input-status">仅计算已收盘 K 线</span>
                )}
                <details className="transient-study-chart__details">
                    <summary>指标查询详情</summary>
                    <p>
                        {active.status === "INPUT_INCOMPLETE"
                            ? "临时闭合 K 线不足"
                            : active.status === "WAITING_FOR_CLOSED_WINDOW"
                              ? "等待 K 线时间窗口就绪 · 将自动重新查询一次"
                              : active.status}{" "}
                        · DISPLAY_ONLY · 不是 Research Result
                        {active.rejected.length === 0 ? null : ` · ${active.rejected.join("；")}`}
                        {active.evidence.some((row) =>
                            row.points.some((point) => point.readiness === "PARTIAL")
                        )
                            ? " · PARTIAL · 有限历史初始化窗口"
                            : null}
                    </p>
                </details>
            </div>
            {["UNAVAILABLE", "INVALID", "STALE", "INPUT_INCOMPLETE"].includes(active.status) ? (
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
    ) : null;
    return (
        <div className="transient-study-chart">
            {attention || statusTarget === undefined
                ? queryStatus
                : statusTarget === null
                  ? null
                  : createPortal(queryStatus, statusTarget)}
            <div className="transient-study-chart__plot">
                <PriceChart {...chart} studyEvidence={active.evidence} />
            </div>
        </div>
    );
}
