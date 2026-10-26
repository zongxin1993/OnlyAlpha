import {
    temporaryWindowVector,
    temporaryEvaluationVector,
    temporaryBatchVector
} from "../../test/temporaryChartVectors";
import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { AppProviders } from "../../app/providers";
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
import { isAdmittedChartStudyEvidence } from "../../api/chartStudies/client";

vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: ({ studyEvidence }: { studyEvidence: readonly unknown[] }) => (
        <div data-testid="study-admission-count">
            {
                studyEvidence.filter(
                    (row) =>
                        typeof row === "object" && row !== null && isAdmittedChartStudyEvidence(row)
                ).length
            }
        </div>
    )
}));
afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
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
    if (mutation === "native") Object.assign(history, { resolution_mode: "UNSUPPORTED" });
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
        if (url.includes("/api/v2/chart/market-data/bars?"))
            return Promise.resolve(
                new Response(JSON.stringify(temporaryWindowVector(history)), {
                    headers: { "cache-control": "no-store" }
                })
            );
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
        return (
            <TransientStudyPriceChart
                pageId="00000000-0000-4000-8000-000000000001"
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
            vi.fn((url: string, init?: RequestInit) => {
                if (url.includes("/api/v2/chart/market-data/bars?"))
                    return Promise.resolve(
                        new Response(JSON.stringify(temporaryWindowVector(history)), {
                            headers: { "cache-control": "no-store" }
                        })
                    );
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
                const count = (JSON.parse(init?.body as string) as { calculations: unknown[] })
                    .calculations.length;
                const batch = temporaryBatchVector(
                    Array.from({ length: count }, () => temporaryEvaluationVector(evaluation))
                );
                const response =
                    sibling === "price"
                        ? {
                              ...batch,
                              results: batch.results.map((row, index) =>
                                  index === 0
                                      ? {
                                            status: "REJECTED",
                                            request_index: index,
                                            error: "CHART_STUDY_REQUEST_INVALID"
                                        }
                                      : row
                              )
                          }
                        : batch;
                return Promise.resolve(
                    new Response(JSON.stringify(response), {
                        headers: { "cache-control": "no-store" }
                    })
                );
            })
        );
        function Query({ dataGeneration }: { dataGeneration: string | null }) {
            return (
                <TransientStudyPriceChart
                    pageId="00000000-0000-4000-8000-000000000001"
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
                new Response(
                    JSON.stringify(temporaryBatchVector([temporaryEvaluationVector(evaluation)])),
                    {
                        headers: { "cache-control": "no-store" }
                    }
                )
            );
            await delayedResponse;
        });
        expect(screen.getByTestId("study-admission-count")).toHaveTextContent("0");
        expect(acquire).not.toHaveBeenCalled();
    }
);

beforeEach(() => vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true"));

it("reuses only unchanged admitted siblings, evicts changed configurations and clears on new input", async () => {
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

    let corruptCatalog = false;
    const evaluations = vi.fn();
    const catalogReads = vi.fn();
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init?: RequestInit) => {
            let value: unknown;
            if (url.includes("/api/v2/chart/market-data/bars?"))
                value = temporaryWindowVector(history);
            else if (url.endsWith("capabilities")) {
                catalogReads();
                value = { schema_version: 2, capabilities: [sample.capability] };
            } else {
                evaluations();
                const result = temporaryEvaluationVector(evaluation);
                value = corruptCatalog
                    ? {
                          ...result,
                          calculation: {
                              ...result.calculation,
                              catalog_generation_fingerprint: "e".repeat(64)
                          }
                      }
                    : result;
            }
            if (!url.includes("/bars?") && !url.endsWith("capabilities")) {
                const body = JSON.parse(init?.body as string) as { calculations: unknown[] };
                value = temporaryBatchVector(body.calculations.map(() => value));
            }
            return Promise.resolve(
                new Response(JSON.stringify(value), { headers: { "cache-control": "no-store" } })
            );
        })
    );
    const market = marketDataClient({
        queryBars: () => Promise.resolve(history),
        createAcquisition: vi.fn()
    });
    const tree = (invalid = false, generation = "verified", missingType = false) => (
        <AppProviders marketDataClient={market}>
            <TransientStudyPriceChart
                pageId="00000000-0000-4000-8000-000000000001"
                context={context}
                dataGeneration={generation}
                expectedSourceId={history.source_selection.source_id}
                expectedEnvironment={history.source_selection.environment}
                contextKey={context.key}
                incarnationKey="incarnation"
                studies={[
                    instance,
                    {
                        ...instance,
                        instanceId: "two",
                        selection: {
                            source: "CHART_STUDY_TRANSIENT",
                            capability: missingType
                                ? { ...capability, type_id: "missing.type" }
                                : capability
                        },
                        configuration: invalid
                            ? {
                                  ...configuration,
                                  parameters: {
                                      ...configuration.parameters,
                                      period: { type: "INTEGER", value: 10001 }
                                  }
                              }
                            : configuration
                    }
                ]}
                bars={history.bars.map(projectMarketDataBar)}
                barSemantic={history.bar_semantic}
            />
        </AppProviders>
    );
    const view = render(tree());
    const settled = (status: string) =>
        waitFor(() => {
            expect(screen.getByTestId("chart-study-query-status")).toHaveAttribute(
                "data-query-status",
                status
            );
        });
    await settled("DISPLAYABLE");
    expect(evaluations).toHaveBeenCalledTimes(1);
    expect(catalogReads).toHaveBeenCalledTimes(1);
    view.rerender(tree(true));
    await settled("PARTIALLY_DISPLAYABLE");
    expect(evaluations).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("study-admission-count")).toHaveTextContent("1");
    view.rerender(tree());
    await settled("DISPLAYABLE");
    expect(evaluations).toHaveBeenCalledTimes(2);
    // The newly evaluated instance proves the same whole catalog generation.
    expect(catalogReads).toHaveBeenCalledTimes(2);
    view.rerender(tree(false, "new-input-occurrence"));
    await settled("DISPLAYABLE");
    expect(evaluations).toHaveBeenCalledTimes(3);
    view.rerender(tree(false, "new-input-occurrence", true));
    await settled("PARTIALLY_DISPLAYABLE");
    expect(evaluations).toHaveBeenCalledTimes(3);
    view.rerender(tree(false, "new-input-occurrence"));
    await settled("DISPLAYABLE");
    view.rerender(tree(true, "new-input-occurrence"));
    await settled("PARTIALLY_DISPLAYABLE");
    const readsBeforeFailure = catalogReads.mock.calls.length;
    corruptCatalog = true;
    view.rerender(tree(false, "new-input-occurrence"));
    await settled("REJECTED_CONFIG");
    // A local catalog key or an invalid evaluation cannot re-admit a cached sibling.
    expect(catalogReads).toHaveBeenCalledTimes(readsBeforeFailure);
    expect(screen.getByTestId("study-admission-count")).toHaveTextContent("0");
});
