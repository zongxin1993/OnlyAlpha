import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { AppProviders, useLocalReadCredentials } from "../../app/providers";
import { marketDataClient } from "../../test/marketDataClient";
import { marketDataBarsSchema } from "../../api/marketData/model";
import {
    ChartStudyCapabilitiesSchema,
    ChartStudyEvaluateSchema
} from "../../api/chartStudies/http.generated";
import { projectMarketDataBar } from "../../charts/lightweight/marketDataChartProjection";
import sample from "../../../../../test-data/web/chart-studies/query.json";
import { TransientStudyPriceChart } from "./TransientStudyPriceChart";
import type { ChartStudyInstance } from "./chartStudy";

vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: ({ studyEvidence }: { studyEvidence: readonly unknown[] }) => (
        <div data-testid="study-admission-count">{studyEvidence.length}</div>
    )
}));
afterEach(() => {
    vi.unstubAllGlobals();
});

it.each([
    "valid",
    "instrument",
    "source",
    "revision",
    "type",
    "environment",
    "window",
    "count",
    "native",
    "coverage"
])("validates initial shortage ownership before interpreting coverage: %s", async (mutation) => {
    vi.stubGlobal(
        "crypto",
        (await vi.importActual<{ webcrypto: Crypto }>("node:crypto")).webcrypto
    );
    const original = marketDataBarsSchema.parse({
        ...sample.history,
        instrument_id: "BTCUSDT.BINANCE"
    });
    const history = structuredClone(original);
    history.bars = [];
    history.history_projection_fingerprint = null;
    history.revision_evidence = [];
    history.resume_after_sequence = null;
    history.resume_plan_fingerprint = null;
    history.coverage.status = "INCOMPLETE";
    history.coverage.actual_bar_count = 0;
    history.coverage.gaps = [
        { start_ns: history.resolved_start_ns, end_ns: history.resolved_end_ns }
    ];
    if (mutation === "instrument") history.instrument_id = "OTHER.BINANCE";
    if (mutation === "source") history.source_selection.source_id = "other";
    if (mutation === "revision")
        history.source_selection.integration_revision_fingerprint = "b".repeat(64);
    if (mutation === "type") history.source_selection.type_id = "other.market_data";
    if (mutation === "environment") history.source_selection.environment = "other";
    if (mutation === "window")
        history.resolved_start_ns = (
            BigInt(history.resolved_start_ns) - 900_000_000_000n
        ).toString();
    if (mutation === "count") history.requested_bar_count = 1;
    if (mutation === "native") history.resolution_mode = "DERIVED";
    if (mutation === "coverage")
        history.coverage.gaps[0] = { start_ns: "0", end_ns: history.resolved_end_ns };
    const capability = ChartStudyCapabilitiesSchema.parse({
        schema_version: 2,
        capabilities: [sample.capability]
    }).capabilities[0];
    if (capability === undefined) throw new Error("Expected capability vector");
    const context = {
        key: "source:revision:native15",
        source: {
            integration_id: original.source_selection.integration_id,
            integration_revision_fingerprint:
                original.source_selection.integration_revision_fingerprint,
            expected_type_id: original.source_selection.type_id
        },
        instrumentId: original.instrument_id,
        barSemantic: original.bar_semantic
    };
    const instance: ChartStudyInstance = {
        instanceId: "one",
        context,
        selection: { source: "CHART_STUDY_TRANSIENT", capability },
        configuration: {
            parameters: {
                period: { type: "INTEGER", value: 20 },
                price_field: { type: "STRING", value: "CLOSE" }
            },
            outputNames: ["value"]
        },
        presentation: {
            placement: "PRICE_OVERLAY",
            color: "#2962FF",
            lineWidth: 2,
            opacity: 1,
            visible: true
        },
        connectionState: "CONFIGURED_NOT_EXECUTED"
    };
    const acquisition = vi.fn();
    const evaluations = vi.fn();
    const transport = vi.fn((url: string) => {
        if (!url.endsWith("capabilities")) evaluations(url);
        return Promise.resolve(
            new Response(JSON.stringify({ schema_version: 2, capabilities: [sample.capability] }), {
                headers: { "cache-control": "no-store" }
            })
        );
    });
    vi.stubGlobal("fetch", transport);
    const market = marketDataClient({
        queryBars: () => Promise.resolve(history),
        createAcquisition: acquisition
    });
    function Query() {
        const credentials = useLocalReadCredentials();
        useLayoutEffect(() => {
            if (credentials.capture().bearer === null) credentials.replace("ee".repeat(32));
        }, [credentials]);
        return (
            <TransientStudyPriceChart
                context={context}
                dataGeneration="verified"
                expectedSourceId={original.source_selection.source_id}
                expectedEnvironment={original.source_selection.environment}
                contextKey={context.key}
                incarnationKey="incarnation"
                studies={[instance]}
                bars={original.bars.map(projectMarketDataBar)}
                barSemantic={original.bar_semantic}
            />
        );
    }
    render(
        <AppProviders marketDataClient={market}>
            <Query />
        </AppProviders>
    );
    await waitFor(() => {
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            mutation === "valid" ? "INPUT_INCOMPLETE" : "INVALID"
        );
    });
    expect(screen.getByTestId("study-admission-count")).toHaveTextContent("0");
    expect(evaluations).not.toHaveBeenCalled();
    expect(acquisition).not.toHaveBeenCalled();
});

it.each(["none", "period", "price", "stale"])(
    "isolates %s sibling while historical proof loss fences every overlay without acquisition",
    async (sibling) => {
        vi.stubGlobal(
            "crypto",
            (await vi.importActual<{ webcrypto: Crypto }>("node:crypto")).webcrypto
        );
        const history = marketDataBarsSchema.parse({
            ...sample.history,
            instrument_id: "BTCUSDT.BINANCE"
        });
        const evaluation = ChartStudyEvaluateSchema.parse({
            ...sample.evaluation,
            instrument_id: history.instrument_id
        });
        const capability = ChartStudyCapabilitiesSchema.parse({
            schema_version: 2,
            capabilities: [sample.capability]
        }).capabilities[0];
        if (capability === undefined) throw new Error("Expected installed capability vector");
        const configuration = {
            parameters: evaluation.calculation.normalized_typed_parameters,
            outputNames: ["value"]
        };
        const context = {
            key: "source:revision:native15",
            source: {
                integration_id: history.source_selection.integration_id,
                integration_revision_fingerprint:
                    history.source_selection.integration_revision_fingerprint,
                expected_type_id: history.source_selection.type_id
            },
            instrumentId: history.instrument_id,
            barSemantic: history.bar_semantic
        };
        const instance: ChartStudyInstance = {
            instanceId: "one",
            context,
            selection: { source: "CHART_STUDY_TRANSIENT", capability },
            configuration,
            presentation: {
                placement: "PRICE_OVERLAY",
                color: "#2962FF",
                lineWidth: 2,
                opacity: 1,
                visible: true
            },
            connectionState: "CONFIGURED_NOT_EXECUTED"
        };
        const invalid: ChartStudyInstance = {
            ...instance,
            instanceId: "invalid",
            ...(sibling === "stale"
                ? {
                      selection: {
                          source: "CHART_STUDY_TRANSIENT",
                          capability: {
                              ...capability,
                              capability_projection_fingerprint: "a".repeat(64)
                          }
                      }
                  }
                : {}),
            configuration: {
                ...instance.configuration,
                parameters: {
                    ...instance.configuration.parameters,
                    ...(sibling === "period" ? { period: { type: "INTEGER", value: 10001 } } : {}),
                    ...(sibling === "price"
                        ? { price_field: { type: "STRING", value: "VOLUME" } }
                        : {})
                }
            }
        };
        const queryBars = vi.fn(() => Promise.resolve(history));
        const acquire = vi.fn();
        const market = marketDataClient({ queryBars, createAcquisition: acquire });
        let pendingResolve!: (response: Response) => void;
        let delayed: Promise<Response> | undefined;
        let block = false;
        vi.stubGlobal(
            "fetch",
            vi.fn((url: string) => {
                if (url.endsWith("capabilities"))
                    return Promise.resolve(
                        new Response(
                            JSON.stringify({
                                schema_version: 2,
                                capabilities: [sample.capability]
                            }),
                            { headers: { "cache-control": "no-store" } }
                        )
                    );
                if (block) {
                    delayed = new Promise<Response>((resolve) => {
                        pendingResolve = resolve;
                    });
                    return delayed;
                }
                return Promise.resolve(
                    new Response(JSON.stringify(evaluation), {
                        headers: { "cache-control": "no-store" }
                    })
                );
            })
        );
        function Query({ dataGeneration }: { dataGeneration: string | null }) {
            const credentials = useLocalReadCredentials();
            useLayoutEffect(() => {
                if (credentials.capture().bearer === null) credentials.replace("ee".repeat(32));
            }, [credentials]);
            return (
                <TransientStudyPriceChart
                    context={context}
                    dataGeneration={dataGeneration}
                    expectedSourceId={history.source_selection.source_id}
                    expectedEnvironment={history.source_selection.environment}
                    contextKey={context.key}
                    incarnationKey="incarnation"
                    studies={sibling === "none" ? [instance] : [invalid, instance]}
                    bars={history.bars.map(projectMarketDataBar)}
                    barSemantic={history.bar_semantic}
                />
            );
        }
        const tree = (dataGeneration: string | null) => (
            <AppProviders marketDataClient={market}>
                <Query dataGeneration={dataGeneration} />
            </AppProviders>
        );
        const view = render(tree("verified"));
        await waitFor(() => {
            expect(screen.getByTestId("study-admission-count")).toHaveTextContent("1");
        });
        expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
            "data-query-status",
            sibling === "none" ? "DISPLAYABLE" : "PARTIALLY_DISPLAYABLE"
        );
        expect(screen.getByText(/DISPLAY_ONLY/)).not.toBeVisible();
        if (sibling !== "none") expect(screen.getByText(/部分可用/)).toBeVisible();
        fireEvent.click(screen.getByText("指标查询详情"));
        expect(screen.getByText(/DISPLAY_ONLY/)).toBeVisible();
        if (sibling !== "none")
            expect(screen.getByTestId("chart-study-query-status")).toHaveTextContent("invalid:");
        block = true;
        view.rerender(tree("new-proof"));
        await waitFor(() => {
            expect(pendingResolve).toBeDefined();
        });
        view.rerender(tree(null));
        expect(screen.getByTestId("study-admission-count")).toHaveTextContent("0");
        const delayedResponse = delayed;
        if (delayedResponse === undefined) throw new Error("Expected blocked response");
        await act(async () => {
            pendingResolve(
                new Response(JSON.stringify(evaluation), {
                    headers: { "cache-control": "no-store" }
                })
            );
            await delayedResponse;
        });
        expect(screen.getByTestId("study-admission-count")).toHaveTextContent("0");
        expect(acquire).not.toHaveBeenCalled();
    }
);
