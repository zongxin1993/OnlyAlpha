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
import { fixedDurationMinutes } from "../../api/marketData/model";
import {
    readChartStudyCapability,
    readChartStudyEvidence,
    assertChartStudyHistory,
    ChartStudyWebError
} from "../../api/chartStudies/client";
import type { ChartStudyEvaluateRequest } from "../../api/chartStudies/http.generated";
import { transientConfigurationErrors, type ChartStudyContext } from "./chartStudy";
import "./TransientStudyPriceChart.css";

interface QueryState {
    readonly key: string;
    readonly evidence: readonly StudySeriesEvidence[];
    readonly status: string;
    readonly rejected: readonly string[];
}

/** Shipping read-only consumer. Main-chart Acquisition and stream remain independent. */
export function TransientStudyPriceChart({
    context,
    dataGeneration,
    expectedSourceId,
    expectedEnvironment,
    ...chart
}: ComponentProps<typeof PriceChart> & {
    readonly context: ChartStudyContext | null;
    readonly dataGeneration: string | null;
    readonly expectedSourceId: string | null;
    readonly expectedEnvironment: string | null;
}) {
    const credentials = useLocalReadCredentials();
    const marketApi = useMarketDataApi();
    const [state, setState] = useState<QueryState>({
        key: "",
        evidence: [],
        status: "NOT_CONNECTED",
        rejected: []
    });
    const [before, setBefore] = useState<string | null>(null);
    const lastClosed = chart.bars.at(-1)?.barEndNs ?? null;
    // The finite evaluation window is independent of viewport movement and live Preview.
    if (before === null && lastClosed !== null) setBefore(lastClosed);
    const intent = JSON.stringify(
        (chart.studies ?? []).map((instance) => ({
            id: instance.instanceId,
            configuration: instance.configuration,
            capability:
                instance.selection.source === "CHART_STUDY_TRANSIENT"
                    ? instance.selection.capability.capability_projection_fingerprint
                    : null,
            state: instance.connectionState
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
        intent
    ]);
    const live = useRef({ key, generation: 0 });
    // The render gate drops mismatched evidence; commit invalidates its runtime
    // owner before any effect can attach an A→B→A or abandoned-generation response.
    useLayoutEffect(() => {
        live.current = { key, generation: live.current.generation + 1 };
    }, [key]);
    const querySnapshot = useEffectEvent(async (controller: AbortController) => {
        const generation = ++live.current.generation;
        const current = () =>
            live.current.key === key &&
            live.current.generation === generation &&
            !controller.signal.aborted;
        const update = (
            status: string,
            evidence: readonly StudySeriesEvidence[] = [],
            rejected: readonly string[] = []
        ) => {
            if (current()) setState({ key, status, evidence, rejected });
        };
        const selected = (chart.studies ?? []).filter(
            (instance) =>
                instance.connectionState !== "STALE_CONFIG" &&
                instance.selection.source === "CHART_STUDY_TRANSIENT"
        );
        async function query() {
            if (selected.length === 0) {
                update("NOT_CONNECTED");
                return;
            }
            if (
                context?.instrumentId !== "BTCUSDT.BINANCE" ||
                fixedDurationMinutes(context.barSemantic) !== 15
            ) {
                update("UNSUPPORTED");
                return;
            }
            if (
                before === null ||
                dataGeneration === null ||
                expectedSourceId === null ||
                expectedEnvironment === null ||
                context.source.expected_type_id === undefined
            ) {
                update("UNAVAILABLE");
                return;
            }
            update("QUERYING");
            const sourceReference = {
                ...context.source,
                expected_type_id: context.source.expected_type_id
            };
            try {
                const capability = await readChartStudyCapability(credentials, controller.signal);
                if (!current()) return;
                const history = await marketApi.queryBars(
                    context.source,
                    {
                        instrument_id: context.instrumentId,
                        bar_semantic: context.barSemantic,
                        anchor_kind: "BEFORE_TIME",
                        before_ns: before,
                        target_bar_count: 2000
                    },
                    controller.signal
                );
                if (!current()) return;
                assertChartStudyHistory(
                    {
                        source_reference: sourceReference,
                        instrument_id: context.instrumentId,
                        bar_semantic: context.barSemantic,
                        window: {
                            anchor_kind: "BEFORE_TIME",
                            before_ns: before,
                            target_bar_count: 2000
                        }
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
                    history.history_projection_fingerprint === null ||
                    history.resolution_mode !== "PROVIDER_NATIVE"
                ) {
                    update("UNAVAILABLE");
                    return;
                }
                const evidence: StudySeriesEvidence[] = [];
                const rejected: string[] = [];
                for (const instance of selected) {
                    if (instance.selection.source !== "CHART_STUDY_TRANSIENT") continue;
                    if (
                        instance.selection.capability.capability_projection_fingerprint !==
                        capability.capability_projection_fingerprint
                    ) {
                        rejected.push(`${instance.instanceId}: STALE`);
                        continue;
                    }
                    const errors = transientConfigurationErrors(capability, instance.configuration);
                    const period = instance.configuration.parameters.period;
                    if (errors.length > 0 || period?.type !== "INTEGER") {
                        rejected.push(`${instance.instanceId}: ${errors.join("；")}`);
                        continue;
                    }
                    const request: ChartStudyEvaluateRequest = {
                        schema_version: 1,
                        source_reference: {
                            ...context.source,
                            expected_type_id: history.source_selection.type_id
                        },
                        instrument_id: context.instrumentId,
                        bar_semantic: context.barSemantic,
                        window: {
                            anchor_kind: "BEFORE_TIME",
                            before_ns: before,
                            target_bar_count: 2000
                        },
                        expected_history_projection_fingerprint:
                            history.history_projection_fingerprint,
                        calculation: {
                            kind: "INDICATOR",
                            type_id: "onlyalpha.indicator.sma",
                            semantic_version: "1",
                            typed_parameters: {
                                period: { type: "INTEGER", value: period.value },
                                price_field: { type: "STRING", value: "CLOSE" }
                            },
                            output_members: ["value"],
                            expected_descriptor_fingerprint: capability.descriptor_fingerprint,
                            expected_implementation_fingerprint:
                                capability.implementation_fingerprint,
                            expected_capability_projection_fingerprint:
                                capability.capability_projection_fingerprint
                        },
                        include_unclosed_preview: false
                    };
                    const result = await readChartStudyEvidence(
                        credentials,
                        request,
                        capability,
                        history,
                        {
                            instanceId: instance.instanceId,
                            chartContextKey: instance.context.key,
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
                    evidence.push(result);
                }
                update(
                    rejected.length === 0
                        ? "DISPLAYABLE"
                        : evidence.length === 0
                          ? "REJECTED_CONFIG"
                          : "PARTIALLY_DISPLAYABLE",
                    evidence,
                    rejected
                );
            } catch (error) {
                if (!current()) return;
                update(
                    error instanceof ChartStudyWebError
                        ? error.status === 401
                            ? "UNAUTHORIZED"
                            : error.status === 403
                              ? "FORBIDDEN"
                              : error.status === 409
                                ? "STALE"
                                : error.status === 500
                                  ? "INVALID"
                                  : error.code === "INVALID"
                                    ? "INVALID"
                                    : "UNAVAILABLE"
                        : "UNAVAILABLE"
                );
            }
        }
        await query();
    });
    useEffect(() => {
        const controller = new AbortController();
        void querySnapshot(controller);
        return () => {
            controller.abort();
            ++live.current.generation;
        };
        // Intent deliberately excludes visibility/color/pane/selection/viewport.
    }, [key]);
    const active = state.key === key ? state : { key, evidence: [], status: "STALE", rejected: [] };
    // Metadata-only configuration has no Chart Query status or numeric admission.
    // Preserve plot space without remounting the native chart on Study addition.
    const hasTransient = (chart.studies ?? []).some(
        (instance) => instance.selection.source === "CHART_STUDY_TRANSIENT"
    );
    return (
        <div className="transient-study-chart">
            {hasTransient ? (
                <p
                    role="status"
                    data-testid="chart-study-query-status"
                    data-query-status={active.status}
                >
                    {active.status === "INPUT_INCOMPLETE" ? "缺少已完成历史 K 线" : active.status} ·
                    DISPLAY_ONLY · 不是 Research Result
                    {active.rejected.length === 0 ? null : ` · ${active.rejected.join("；")}`}
                </p>
            ) : null}
            <div className="transient-study-chart__plot">
                <PriceChart {...chart} studyEvidence={active.evidence} />
            </div>
        </div>
    );
}
