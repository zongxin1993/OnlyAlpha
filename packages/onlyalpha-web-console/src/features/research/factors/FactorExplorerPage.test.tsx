import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ResearchApiClient } from "../../../api/research/client";
import { ResearchWebError } from "../../../api/research/errors";
import type { ResearchCalculationCatalogTransport } from "../../../api/research/schemas";
import { AppProviders } from "../../../app/providers";
import { parseDecimalText } from "../../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseResearchRunId,
    parseSha256Fingerprint,
    parseStatisticsFingerprint
} from "../../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchCandidate,
    ResearchCandidateGraph,
    ResearchGraphNode,
    ResearchMarketPoint,
    ResearchPublishedSeries,
    ResearchRunSummary,
    ResearchScientificSeriesPage,
    ResearchStatisticsDescriptor
} from "../../../domain/research/model";
import { parseUnixNanoseconds } from "../../../domain/research/time";
import { researchClient } from "../../../test/researchClient";
import type { FinancialEvidenceChart } from "../../../visualization/financial/lightweight/FinancialEvidenceChart";
import { publishedSeriesKey } from "../results/model/selectors";
import { FactorExplorerPage } from "./FactorExplorerPage";

vi.mock("../../../visualization/financial/lightweight/FinancialEvidenceChart", () => ({
    FinancialEvidenceChart: (props: ComponentProps<typeof FinancialEvidenceChart>) => (
        <div
            data-testid="explorer-financial-chart"
            data-label={props.variableLabel}
            data-variable={JSON.stringify(props.variable)}
            data-pane={String(props.variablePane)}
        />
    )
}));
vi.mock("../../../visualization/scientific/echarts/ScientificEvidenceChart", () => ({
    ScientificEvidenceChart: () => <div data-testid="explorer-statistics-chart" />
}));

const resultA = parseResearchResultFingerprint("a".repeat(64));
const resultB = parseResearchResultFingerprint("b".repeat(64));
const candidateA = parseSha256Fingerprint("1".repeat(64));
const candidateB = parseSha256Fingerprint("2".repeat(64));
const calculationA = parseSha256Fingerprint("3".repeat(64));
const calculationB = parseSha256Fingerprint("4".repeat(64));
const nodeA = parseSha256Fingerprint("5".repeat(64));
const nodeB = parseSha256Fingerprint("6".repeat(64));
const graphA = parseSha256Fingerprint("7".repeat(64));
const graphB = parseSha256Fingerprint("8".repeat(64));
const statisticA = parseStatisticsFingerprint("9".repeat(64));
const statisticB = parseStatisticsFingerprint("c".repeat(64));
const runA = parseResearchRunId("10000000-0000-4000-8000-000000000001");
const runB = parseResearchRunId("10000000-0000-4000-8000-000000000002");
const firstStock = "AAA.XNAS";
const secondStock = "BBB.XNAS";
const timestamp = parseUnixNanoseconds("1709164800000000000");
const exclusiveEnd = parseUnixNanoseconds("1709251200000000000");
type VariableSeriesRequest = Parameters<ResearchApiClient["getVariableSeries"]>[0];

function calculation(
    version = "1.0.0",
    indicator = false
): ResearchCalculationCatalogTransport["calculations"][number] {
    const kind = indicator ? "INDICATOR" : "FACTOR";
    return {
        kind,
        type_reference: {
            kind,
            type_id: indicator ? "example.indicator" : "example.momentum",
            semantic_version: version
        },
        inputs: [],
        outputs: [
            {
                name: "score",
                data_type: "DECIMAL",
                nullable: true,
                semantic_type: indicator ? "INDICATOR_VALUE" : "FACTOR_SCORE",
                dimensions: ["TIME", "INSTRUMENT"],
                unit: null
            }
        ],
        parameters: [],
        parameter_sweep_allowed: true
    };
}

function candidate(second = false): ResearchCandidate {
    return {
        candidateFingerprint: second ? candidateB : candidateA,
        candidateCalculationId: second ? "momentum-second" : "momentum-first",
        calculationFingerprint: second ? calculationB : calculationA,
        graphFingerprint: second ? graphB : graphA,
        assignment: {},
        assignmentTypes: {},
        statisticsFingerprints: [second ? statisticB : statisticA],
        signalRoles: []
    };
}

function published(second = false): ResearchPublishedSeries {
    return {
        candidateFingerprint: second ? candidateB : candidateA,
        calculationFingerprint: second ? calculationB : calculationA,
        nodeFingerprint: second ? nodeB : nodeA,
        outputName: "score",
        valueKind: "DECIMAL"
    };
}

function graphNode(second = false): ResearchGraphNode {
    return {
        nodeFingerprint: second ? nodeB : nodeA,
        alias: "Momentum",
        definition: {
            schemaVersion: 2,
            kind: "FACTOR",
            typeId: "example.momentum",
            semanticVersion: second ? "2.0.0" : "1.0.0",
            parameters: {},
            inputs: [],
            inputBindings: {},
            outputs: [
                {
                    name: "score",
                    dataType: "DECIMAL",
                    nullable: true,
                    semanticType: "FACTOR_SCORE",
                    dimensions: ["TIME", "INSTRUMENT"],
                    unit: null
                }
            ],
            warmup: {
                minimumObservations: 1,
                readyCondition: "READY",
                preReadyOutput: "NULL",
                initialization: "FIRST_OBSERVATION"
            },
            missingValues: "PROPAGATE",
            timestamp: "OBSERVATION_TIME",
            numeric: {
                representation: "DECIMAL",
                precision: 28,
                outputQuantum: parseDecimalText("0.0001"),
                rounding: "ROUND_HALF_EVEN"
            },
            factorKind: "CROSS_SECTION",
            extensions: {}
        }
    };
}

function graph(result: typeof resultA, second = false): ResearchCandidateGraph {
    const selected = candidate(second);
    return {
        researchResultFingerprint: result,
        candidateFingerprint: selected.candidateFingerprint,
        calculationFingerprint: selected.calculationFingerprint,
        graphFingerprint: selected.graphFingerprint,
        graph: { schemaVersion: 1, nodes: [graphNode(second)] }
    };
}

function descriptor(second = false): ResearchStatisticsDescriptor {
    const selected = published(second);
    return {
        statisticsFingerprint: second ? statisticB : statisticA,
        statisticsResultFingerprint: "d".repeat(64),
        resultContentFingerprint: "e".repeat(64),
        statisticsResultSchemaVersion: 1,
        rowCount: 1,
        feature: {
            calculationFingerprint: selected.calculationFingerprint,
            nodeFingerprint: selected.nodeFingerprint,
            outputName: "score"
        },
        target: {
            calculationFingerprint: selected.calculationFingerprint,
            nodeFingerprint: "f".repeat(64),
            outputName: "forward_return_5d"
        },
        definition: {
            method: "SPEARMAN_RANK_IC",
            minimumObservations: 3,
            pairingPolicy: "PAIRWISE_COMPLETE",
            universePolicy: "EXACT_INTERSECTION",
            rankTieMethod: "AVERAGE",
            weighting: "EQUAL",
            numeric: {
                representation: "DECIMAL",
                precision: 28,
                outputQuantum: parseDecimalText("0.0001"),
                rounding: "ROUND_HALF_EVEN"
            }
        }
    };
}

function summary(result = resultA): ResearchArtifactSummary {
    return {
        researchResultFingerprint: result,
        researchResultPlanFingerprint: "d".repeat(64),
        researchResultContentFingerprint: "e".repeat(64),
        datasetSnapshotFingerprint: "f".repeat(64),
        artifactContentFingerprint: "0".repeat(64),
        researchResultSchemaVersion: 2,
        artifactProfile: "RESEARCH_SCIENTIFIC_V2",
        artifactSchemaVersion: 2,
        statisticsCount: 1,
        rowCount: 1,
        candidateCount: 1,
        publishedSeriesCount: 1,
        signalSeriesCount: 0,
        marketRowCount: 2,
        instrumentIds: [firstStock, secondStock],
        createdAt: "2024-03-01T00:00:00Z"
    };
}

function completedRun(second = false): ResearchRunSummary {
    return {
        runId: second ? runB : runA,
        revision: 1n,
        state: "COMPLETED",
        specificationSchemaVersion: 2,
        specificationFingerprint: "d".repeat(64),
        admissionResolutionFingerprint: "e".repeat(64),
        queuedAt: "2024-03-01T00:00:00Z",
        startedAt: "2024-03-01T00:00:01Z",
        cancelRequestedAt: null,
        finishedAt: "2024-03-01T00:00:02Z",
        resultRef: second ? resultB : resultA,
        artifactRef: "f".repeat(64),
        failure: null
    };
}

function marketPoint(instrumentId: string, exactTime = timestamp): ResearchMarketPoint {
    return {
        kind: "MARKET",
        instrumentId,
        tsEventNs: exactTime,
        open: parseDecimalText("10.000"),
        high: parseDecimalText("12.000"),
        low: parseDecimalText("9.000"),
        close: parseDecimalText("11.000"),
        volume: parseDecimalText("100.000")
    };
}

function variablePage(request: VariableSeriesRequest): ResearchScientificSeriesPage {
    return {
        researchResultFingerprint: request.researchResultFingerprint,
        points: [
            {
                kind: "VARIABLE",
                instrumentId: request.instrumentId,
                tsEventNs: request.fromTsEventNs ?? timestamp,
                valueKind: "DECIMAL",
                decimalValue: parseDecimalText(
                    request.calculationFingerprint === calculationA ? "0.125000" : "0.875000"
                ),
                integerValue: null,
                booleanValue: null,
                stringValue: null
            }
        ],
        hasMore: false,
        nextAfterTsEventNs: null
    };
}

type TestApi = {
    [Key in keyof ResearchApiClient]: (
        ...args: Parameters<ResearchApiClient[Key]>
    ) => ReturnType<ResearchApiClient[Key]>;
};

function client({
    twoCandidates = false,
    overrides = {}
}: {
    readonly twoCandidates?: boolean;
    readonly overrides?: Partial<ResearchApiClient>;
} = {}): TestApi {
    const choices = (result: typeof resultA) =>
        result === resultB ? [true] : twoCandidates ? [false, true] : [false];
    const api = researchClient({
        getCalculationCatalog: () =>
            Promise.resolve({
                schema_version: 2,
                calculations: [calculation(), calculation("2.0.0"), calculation("1.0.0", true)]
            }),
        listRuns: () =>
            Promise.resolve({
                runs: [completedRun(), completedRun(true)],
                hasMore: false,
                nextCursor: null
            }),
        getArtifactSummary: (result) =>
            Promise.resolve({
                ...summary(result),
                candidateCount: choices(result).length,
                statisticsCount: choices(result).length,
                publishedSeriesCount: choices(result).length,
                rowCount: choices(result).length
            }),
        getCandidateCatalog: (result) =>
            Promise.resolve({
                researchResultFingerprint: result,
                candidates: choices(result).map(candidate)
            }),
        getPublishedSeriesCatalog: (result) =>
            Promise.resolve({
                researchResultFingerprint: result,
                series: choices(result).map(published)
            }),
        getStatisticsCatalog: (result) =>
            Promise.resolve({
                researchResultFingerprint: result,
                statistics: choices(result).map(descriptor)
            }),
        getCandidateGraph: (result, selected) =>
            Promise.resolve(graph(result, selected === candidateB)),
        getMarketSeries: (result, instrumentId, request) =>
            Promise.resolve({
                researchResultFingerprint: result,
                points: [marketPoint(instrumentId, request?.fromTsEventNs ?? timestamp)],
                hasMore: false,
                nextAfterTsEventNs: null
            }),
        getVariableSeries: (request) => Promise.resolve(variablePage(request)),
        getStatisticSeries: (request) =>
            Promise.resolve({
                researchResultFingerprint: request.researchResultFingerprint,
                statisticsFingerprint: request.statisticsFingerprint,
                points: [
                    {
                        tsEventNs: request.fromTsEventNs ?? timestamp,
                        statisticValue: parseDecimalText("0.234500"),
                        sampleCount: 300,
                        status: "VALID"
                    }
                ],
                hasMore: false,
                nextAfterTsEventNs: null
            }),
        ...overrides
    });
    for (const method of Object.keys(api) as (keyof ResearchApiClient)[]) vi.spyOn(api, method);
    return api;
}

function route(params: readonly (readonly [string, string])[] = [["result", resultA]]) {
    const query = new URLSearchParams();
    for (const [key, value] of params) query.append(key, value);
    return `/research/factors?${query.toString()}`;
}

function renderExplorer(api = client(), path = route()) {
    const router = createMemoryRouter(
        [
            { path: "/research/factors", element: <FactorExplorerPage /> },
            { path: "/research/new", element: <p>New Research</p> },
            { path: "/research/runs", element: <p>Run history</p> },
            { path: "/research/results/:researchResultFingerprint", element: <p>Full Result</p> }
        ],
        { initialEntries: [path] }
    );
    render(
        <AppProviders client={api}>
            <RouterProvider router={router} />
        </AppProviders>
    );
    return router;
}

function expectNoSeriesReads(api: TestApi) {
    expect(api.getMarketSeries).not.toHaveBeenCalled();
    expect(api.getVariableSeries).not.toHaveBeenCalled();
    expect(api.getStatisticSeries).not.toHaveBeenCalled();
}

it("searches exact catalog versions without reclassifying Indicators", async () => {
    const api = client();
    const router = renderExplorer(api, route([]));
    const library = screen.getByRole("complementary", { name: "Registered Factor catalog" });
    expect(
        await within(library).findAllByRole("button", { name: /example.momentum/ })
    ).toHaveLength(2);
    expect(
        within(library).queryByRole("button", { name: /example.indicator/ })
    ).not.toBeInTheDocument();
    await userEvent.type(
        screen.getByRole("searchbox", { name: "Search registered Factors" }),
        "example.momentum@2.0.0"
    );
    const choices = within(library).getAllByRole("button", { name: /example.momentum/ });
    expect(choices).toHaveLength(1);
    await userEvent.click(choices[0] ?? library);
    expect(new URLSearchParams(router.state.location.search).get("factor")).toBe(
        "FACTOR:example.momentum@2.0.0"
    );
    expect(screen.getByRole("link", { name: /Configure Research/ })).toHaveAttribute(
        "href",
        `/research/new?${new URLSearchParams({ factor: "FACTOR:example.momentum@2.0.0" }).toString()}`
    );
    expect(api.getArtifactSummary).not.toHaveBeenCalled();
    expectNoSeriesReads(api);
});

it("opens the sole exact Candidate and Factor with one stock and original-population Statistics", async () => {
    const api = client();
    renderExplorer(api);
    const chart = await screen.findByTestId("explorer-financial-chart");
    expect(chart).toHaveAttribute("data-pane", "true");
    expect(chart).toHaveAttribute("data-label", "Momentum · example.momentum@1.0.0 · score");
    expect(screen.getByRole("combobox", { name: "Exact Research Candidate" })).toHaveValue(
        candidateA
    );
    expect(screen.getByRole("combobox", { name: "Exact Factor output" })).toHaveValue(
        publishedSeriesKey(published())
    );
    expect(screen.getByRole("checkbox", { name: firstStock })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: secondStock })).not.toBeChecked();
    expect(await screen.findByTestId("explorer-statistics-chart")).toBeInTheDocument();
    expect(
        screen.getByText(/^Statistics population: original Research universe\./)
    ).toBeInTheDocument();
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(api.getMarketSeries).toHaveBeenCalledTimes(1);
    expect(api.getVariableSeries).toHaveBeenCalledTimes(1);
    expect(api.submitRun).not.toHaveBeenCalled();
    expect(api.resolveDefinition).not.toHaveBeenCalled();
    expect(api.getSignalSeries).not.toHaveBeenCalled();
});

it("shows two selected stocks without recalculating or relabeling whole-universe IC", async () => {
    const api = client();
    const router = renderExplorer(api);
    await screen.findByTestId("explorer-statistics-chart");
    const stock = screen.getByRole("checkbox", { name: secondStock });
    fireEvent.click(stock);
    expect(stock).toBeChecked();
    expect(new URLSearchParams(router.state.location.search).getAll("instrument")).toEqual([
        firstStock,
        secondStock
    ]);
    await waitFor(() => {
        expect(screen.getAllByTestId("explorer-financial-chart")).toHaveLength(2);
    });
    expect(api.getMarketSeries).toHaveBeenCalledTimes(2);
    expect(api.getVariableSeries).toHaveBeenCalledTimes(2);
    expect(api.getStatisticSeries).toHaveBeenCalledTimes(1);
    expect(
        screen.getByText(/^Statistics population: original Research universe\./)
    ).toBeInTheDocument();
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(
        screen.getAllByText(
            /single-instrument co-plot is not a time-series correlation coefficient/
        )
    ).toHaveLength(2);
    expect(screen.getByRole("combobox", { name: "Correlation statistic" })).toHaveValue(statisticA);
});

it("submits canonical UTC inclusive-start/exclusive-end filters for the displayed stock", async () => {
    const api = client();
    const router = renderExplorer(api);
    await screen.findByTestId("explorer-financial-chart");
    fireEvent.change(screen.getByLabelText("From UTC (inclusive)"), {
        target: { value: "2024-02-29" }
    });
    fireEvent.change(screen.getByLabelText("To UTC (exclusive)"), {
        target: { value: "2024-03-01" }
    });
    await userEvent.click(screen.getByRole("button", { name: "Apply time window" }));
    await waitFor(() => {
        expect(api.getMarketSeries).toHaveBeenCalledTimes(2);
    });
    expect(api.getMarketSeries).toHaveBeenLastCalledWith(
        resultA,
        firstStock,
        { limit: 500, fromTsEventNs: timestamp, toTsEventNs: exclusiveEnd },
        expect.any(AbortSignal)
    );
    expect(api.getVariableSeries).toHaveBeenLastCalledWith(
        {
            researchResultFingerprint: resultA,
            instrumentId: firstStock,
            candidateFingerprint: candidateA,
            calculationFingerprint: calculationA,
            nodeFingerprint: nodeA,
            outputName: "score",
            limit: 500,
            fromTsEventNs: timestamp,
            toTsEventNs: exclusiveEnd
        },
        expect.any(AbortSignal)
    );
    const params = new URLSearchParams(router.state.location.search);
    expect(params.get("from")).toBe("2024-02-29");
    expect(params.get("to")).toBe("2024-03-01");
});

it("rejects an invalid Result locally before any exact Artifact query", async () => {
    const api = client();
    renderExplorer(api, route([["result", "not-a-result"]]));
    expect(await screen.findByRole("alert")).toHaveTextContent("INVALID_QUERY");
    expect(api.getArtifactSummary).not.toHaveBeenCalled();
    expect(api.getCandidateGraph).not.toHaveBeenCalled();
    expectNoSeriesReads(api);
});

it.each([
    { name: "Candidate", params: [["candidate", "f".repeat(64)]] },
    { name: "Factor Series", params: [["series", "not-a-published-series"]] },
    { name: "stock", params: [["instrument", "FOREIGN.XNAS"]] },
    {
        name: "duplicate stock",
        params: [
            ["instrument", firstStock],
            ["instrument", firstStock]
        ]
    }
])(
    "fails closed for a nonmember $name selection without evidence queries",
    async ({ name, params }) => {
        const api = client();
        renderExplorer(
            api,
            route([
                ["result", resultA],
                ...params.map(([key, value]): [string, string] => [key ?? "", value ?? ""])
            ])
        );
        expect(await screen.findByRole("alert")).toHaveTextContent("INVALID_QUERY");
        expectNoSeriesReads(api);
        if (name === "Candidate") expect(api.getCandidateGraph).not.toHaveBeenCalled();
        expect(screen.queryByTestId("explorer-financial-chart")).not.toBeInTheDocument();
    }
);

it("rejects a Summary from a different Result before Graph or instrument reads", async () => {
    const api = client({
        overrides: { getArtifactSummary: () => Promise.resolve(summary(resultB)) }
    });
    renderExplorer(api);
    expect(await screen.findByRole("alert")).toHaveTextContent("CONTRACT_ERROR");
    expect(api.getCandidateGraph).not.toHaveBeenCalled();
    expectNoSeriesReads(api);
});

it("does not query nonmember Statistics while valid stock evidence remains independent", async () => {
    const api = client();
    renderExplorer(
        api,
        route([
            ["result", resultA],
            ["statistic", "f".repeat(64)]
        ])
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("INVALID_QUERY");
    expect(api.getStatisticSeries).not.toHaveBeenCalled();
    expect(screen.queryByTestId("explorer-statistics-chart")).not.toBeInTheDocument();
    expect(await screen.findByTestId("explorer-financial-chart")).toBeInTheDocument();
});

it.each(["2.0.0", "9.0.0"])(
    "does not silently substitute Factor version %s with historical version 1",
    async (version) => {
        const api = client();
        renderExplorer(
            api,
            route([
                ["result", resultA],
                ["factor", `FACTOR:example.momentum@${version}`]
            ])
        );
        expect(
            await screen.findByText(
                "No exact Factor type/version matching the catalog selection in this Candidate."
            )
        ).toBeInTheDocument();
        expectNoSeriesReads(api);
        expect(screen.queryByTestId("explorer-financial-chart")).not.toBeInTheDocument();
    }
);

it("reports unavailable V1 scientific evidence honestly without inferred Factor values", async () => {
    const api = client({
        overrides: {
            getArtifactSummary: () =>
                Promise.resolve({
                    ...summary(),
                    artifactProfile: "RESEARCH_STATISTICS_V1",
                    artifactSchemaVersion: 1
                }),
            getCandidateCatalog: () =>
                Promise.reject(
                    new ResearchWebError(
                        "SCIENTIFIC_EVIDENCE_NOT_AVAILABLE",
                        "Scientific evidence is unavailable in this Artifact profile",
                        404
                    )
                )
        }
    });
    renderExplorer(api);
    expect(
        await screen.findByText(/This Artifact profile has no published Factor Graph evidence/)
    ).toBeInTheDocument();
    expectNoSeriesReads(api);
    expect(api.getCandidateGraph).not.toHaveBeenCalled();
    expect(api.getPublishedSeriesCatalog).not.toHaveBeenCalled();
});

it("opening another completed Result clears dependent URL selections and old Factor evidence", async () => {
    const api = client();
    const router = renderExplorer(
        api,
        route([
            ["result", resultA],
            ["candidate", candidateA],
            ["series", publishedSeriesKey(published())],
            ["statistic", statisticA],
            ["instrument", secondStock],
            ["from", "2024-02-29"],
            ["to", "2024-03-01"]
        ])
    );
    await screen.findByTestId("explorer-financial-chart");
    await userEvent.selectOptions(
        screen.getByRole("combobox", { name: "Completed Factor Research Run" }),
        runB
    );
    await waitFor(() => {
        expect(screen.getByTestId("explorer-financial-chart")).toHaveAttribute(
            "data-label",
            "Momentum · example.momentum@2.0.0 · score"
        );
    });
    const params = new URLSearchParams(router.state.location.search);
    expect(params.get("result")).toBe(resultB);
    for (const key of ["candidate", "series", "statistic", "instrument", "from", "to"])
        expect(params.has(key)).toBe(false);
    expect(screen.getByRole("checkbox", { name: firstStock })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: secondStock })).not.toBeChecked();
    expect(api.getVariableSeries).toHaveBeenLastCalledWith(
        expect.objectContaining({
            researchResultFingerprint: resultB,
            calculationFingerprint: calculationB
        }),
        expect.any(AbortSignal)
    );
});

it("changing Candidate clears dependent Series/Statistics and rejects late prior-Candidate data", async () => {
    let finishOld: ((page: ResearchScientificSeriesPage) => void) | undefined;
    const old = new Promise<ResearchScientificSeriesPage>((resolve) => {
        finishOld = resolve;
    });
    let oldRequest: VariableSeriesRequest | undefined;
    const api = client({
        twoCandidates: true,
        overrides: {
            getVariableSeries: (request) => {
                if (request.calculationFingerprint === calculationA) {
                    oldRequest = request;
                    return old;
                }
                return Promise.resolve(variablePage(request));
            }
        }
    });
    const router = renderExplorer(
        api,
        route([
            ["result", resultA],
            ["candidate", candidateA],
            ["series", publishedSeriesKey(published())],
            ["statistic", statisticA]
        ])
    );
    await waitFor(() => {
        expect(api.getVariableSeries).toHaveBeenCalledTimes(1);
    });
    await userEvent.selectOptions(
        screen.getByRole("combobox", { name: "Exact Research Candidate" }),
        candidateB
    );
    const chart = await screen.findByTestId("explorer-financial-chart");
    expect(chart).toHaveAttribute("data-label", "Momentum · example.momentum@2.0.0 · score");
    expect(chart).toHaveAttribute(
        "data-variable",
        JSON.stringify([{ time: 1709164800, value: 0.875 }])
    );
    const params = new URLSearchParams(router.state.location.search);
    expect(params.get("candidate")).toBe(candidateB);
    expect(params.has("series")).toBe(false);
    expect(params.has("statistic")).toBe(false);
    if (finishOld === undefined || oldRequest === undefined)
        throw new Error("Old Candidate request did not reach the deterministic barrier");
    const latePage = variablePage(oldRequest);
    await act(async () => {
        finishOld?.(latePage);
        await old;
    });
    expect(screen.getByTestId("explorer-financial-chart")).toHaveAttribute(
        "data-variable",
        JSON.stringify([{ time: 1709164800, value: 0.875 }])
    );
    expect(screen.getByRole("combobox", { name: "Correlation statistic" })).toHaveValue(statisticB);
});
