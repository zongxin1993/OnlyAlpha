/* eslint-disable @typescript-eslint/require-await */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AppProviders } from "../../../app/providers";
import { ResearchWebError } from "../../../api/research/errors";
import { parseDecimalText } from "../../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseSha256Fingerprint,
    parseStatisticsFingerprint
} from "../../../domain/research/identity";
import { parseUnixNanoseconds } from "../../../domain/research/time";
import { researchClient } from "../../../test/researchClient";
import { ResultWorkspacePage } from "./ResultWorkspacePage";

vi.mock("../../../visualization/financial/lightweight/FinancialEvidenceChart", () => ({
    FinancialEvidenceChart: ({ markers }: { markers: readonly unknown[] }) => (
        <div data-testid="financial-chart">{markers.length} authoritative markers</div>
    )
}));
vi.mock("../../../visualization/scientific/echarts/ScientificEvidenceChart", () => ({
    ScientificEvidenceChart: () => <div data-testid="scientific-chart">scientific evidence</div>
}));
vi.mock("../../../visualization/graph/graphviz/GraphvizInspectorView", () => ({
    GraphvizInspectorView: ({ onSelectNode }: { readonly onSelectNode: (id: string) => void }) => (
        <button
            type="button"
            data-testid="graphviz-view"
            onClick={() => {
                onSelectNode("1".repeat(64));
            }}
        >
            exact graph
        </button>
    )
}));

const result = parseResearchResultFingerprint("a".repeat(64));
const candidateA = parseSha256Fingerprint("1".repeat(64));
const candidateB = parseSha256Fingerprint("2".repeat(64));
const calculationA = parseSha256Fingerprint("3".repeat(64));
const calculationB = parseSha256Fingerprint("4".repeat(64));
const nodeA = parseSha256Fingerprint("5".repeat(64));
const nodeB = parseSha256Fingerprint("6".repeat(64));
const graphA = parseSha256Fingerprint("7".repeat(64));
const graphB = parseSha256Fingerprint("8".repeat(64));
const statisticA = parseStatisticsFingerprint("9".repeat(64));
const statisticB = parseStatisticsFingerprint("b".repeat(64));

function client() {
    return researchClient({
        getArtifactSummary: async () => ({
            researchResultFingerprint: result,
            researchResultPlanFingerprint: "c".repeat(64),
            researchResultContentFingerprint: "d".repeat(64),
            datasetSnapshotFingerprint: "e".repeat(64),
            artifactContentFingerprint: "f".repeat(64),
            researchResultSchemaVersion: 2,
            artifactProfile: "RESEARCH_SCIENTIFIC_V2",
            artifactSchemaVersion: 2,
            statisticsCount: 2,
            rowCount: 2,
            candidateCount: 2,
            publishedSeriesCount: 2,
            signalSeriesCount: 4,
            marketRowCount: 2,
            instrumentIds: ["510300", "510500"],
            createdAt: "2026-08-21T00:00:00Z"
        }),
        getCandidateCatalog: async () => ({
            researchResultFingerprint: result,
            candidates: [
                {
                    candidateFingerprint: candidateA,
                    candidateCalculationId: "decision",
                    assignment: { period: 14 },
                    assignmentTypes: { period: "INTEGER" },
                    calculationFingerprint: calculationA,
                    graphFingerprint: graphA,
                    statisticsFingerprints: [statisticA],
                    signalRoles: ["ENTRY_SIGNAL", "EXIT_SIGNAL"]
                },
                {
                    candidateFingerprint: candidateB,
                    candidateCalculationId: "decision",
                    assignment: { period: 28 },
                    assignmentTypes: { period: "INTEGER" },
                    calculationFingerprint: calculationB,
                    graphFingerprint: graphB,
                    statisticsFingerprints: [statisticB],
                    signalRoles: ["ENTRY_SIGNAL", "EXIT_SIGNAL"]
                }
            ]
        }),
        getPublishedSeriesCatalog: async () => ({
            researchResultFingerprint: result,
            series: [
                {
                    candidateFingerprint: candidateA,
                    calculationFingerprint: calculationA,
                    nodeFingerprint: nodeA,
                    outputName: "rsi",
                    valueKind: "DECIMAL"
                },
                {
                    candidateFingerprint: candidateB,
                    calculationFingerprint: calculationB,
                    nodeFingerprint: nodeB,
                    outputName: "rsi",
                    valueKind: "DECIMAL"
                }
            ]
        }),
        getStatisticsCatalog: async () => ({
            researchResultFingerprint: result,
            statistics: [
                descriptor(statisticA, calculationA, nodeA),
                descriptor(statisticB, calculationB, nodeB)
            ]
        }),
        getStatisticSeries: async (request) => ({
            researchResultFingerprint: result,
            statisticsFingerprint: request.statisticsFingerprint,
            points: [
                {
                    tsEventNs: parseUnixNanoseconds("2000000000"),
                    statisticValue: parseDecimalText(
                        request.statisticsFingerprint === statisticA ? "0.1" : "0.2"
                    ),
                    sampleCount: 300,
                    status: "VALID"
                }
            ],
            hasMore: false,
            nextAfterTsEventNs: null
        }),
        getMarketSeries: async (_result, instrumentId, page) => ({
            researchResultFingerprint: result,
            points: [
                {
                    kind: "MARKET",
                    instrumentId,
                    tsEventNs: page?.afterTsEventNs ?? parseUnixNanoseconds("1000000000"),
                    open: parseDecimalText("10"),
                    high: parseDecimalText("12"),
                    low: parseDecimalText("9"),
                    close: parseDecimalText("11"),
                    volume: parseDecimalText("100")
                }
            ],
            hasMore: false,
            nextAfterTsEventNs: null
        }),
        getVariableSeries: async (request) => ({
            researchResultFingerprint: result,
            points: [
                {
                    kind: "VARIABLE",
                    instrumentId: request.instrumentId,
                    tsEventNs: parseUnixNanoseconds("1000000000"),
                    valueKind: "DECIMAL",
                    decimalValue: parseDecimalText("29.5"),
                    integerValue: null,
                    booleanValue: null,
                    stringValue: null
                }
            ],
            hasMore: false,
            nextAfterTsEventNs: null
        }),
        getSignalSeries: async (request) => ({
            researchResultFingerprint: result,
            points: [
                {
                    kind: "SIGNAL",
                    instrumentId: request.instrumentId,
                    tsEventNs: parseUnixNanoseconds("1000000000"),
                    value: request.role === "ENTRY_SIGNAL" ? true : null
                }
            ],
            hasMore: false,
            nextAfterTsEventNs: null
        }),
        getCandidateGraph: async (_result, candidate) => {
            const second = candidate === candidateB;
            return {
                researchResultFingerprint: result,
                candidateFingerprint: second ? candidateB : candidateA,
                calculationFingerprint: second ? calculationB : calculationA,
                graphFingerprint: second ? graphB : graphA,
                graph: {
                    schemaVersion: 1,
                    nodes: [graphNode(second ? nodeB : nodeA)]
                }
            };
        }
    });
}

function descriptor(
    statisticsFingerprint: typeof statisticA,
    calculationFingerprint: typeof calculationA,
    nodeFingerprint: typeof nodeA
) {
    return {
        statisticsFingerprint,
        statisticsResultFingerprint: "c".repeat(64),
        resultContentFingerprint: "d".repeat(64),
        statisticsResultSchemaVersion: 1,
        rowCount: 1,
        feature: { calculationFingerprint, nodeFingerprint, outputName: "score" },
        target: { calculationFingerprint, nodeFingerprint, outputName: "return_5d" },
        definition: {
            method: "IC",
            minimumObservations: 2,
            pairingPolicy: "PAIRWISE_COMPLETE",
            universePolicy: "EXACT",
            rankTieMethod: "AVERAGE",
            weighting: "EQUAL",
            numeric: {
                representation: "DECIMAL",
                precision: 38,
                outputQuantum: parseDecimalText("0.0001"),
                rounding: "ROUND_HALF_EVEN"
            }
        }
    } as const;
}

function graphNode(nodeFingerprint: typeof nodeA) {
    return {
        nodeFingerprint,
        alias: "rsi",
        definition: {
            schemaVersion: 2 as const,
            kind: "INDICATOR" as const,
            typeId: "onlyalpha.indicator.rsi",
            semanticVersion: "1",
            parameters: { period: { type: "INTEGER" as const, value: "14" } },
            inputs: [],
            inputBindings: {},
            outputs: [
                {
                    name: "rsi",
                    dataType: "DECIMAL" as const,
                    nullable: true,
                    dimensions: ["TIME"],
                    semanticType: "INDICATOR_VALUE",
                    unit: null
                }
            ],
            warmup: {
                minimumObservations: 14,
                readyCondition: "READY",
                preReadyOutput: "NULL" as const,
                initialization: "WINDOW"
            },
            missingValues: "PROPAGATE" as const,
            timestamp: "EVENT_TIME" as const,
            numeric: {
                representation: "DECIMAL",
                precision: 38,
                outputQuantum: null,
                rounding: "CONTEXT"
            },
            factorKind: null,
            extensions: {}
        }
    };
}

function renderWorkspace(api = client()) {
    const router = createMemoryRouter(
        [
            {
                path: "/research/results/:researchResultFingerprint",
                element: <ResultWorkspacePage />
            }
        ],
        { initialEntries: [`/research/results/${result}`] }
    );
    render(
        <AppProviders client={api}>
            <RouterProvider router={router} />
        </AppProviders>
    );
}

it("deep-links one exact Result and renders admitted overview counts", async () => {
    renderWorkspace();
    expect(screen.getByRole("status")).toHaveTextContent("Loading verified");
    expect(
        await screen.findByRole("heading", { name: "Scientific Workstation" })
    ).toBeInTheDocument();
    expect(screen.getAllByText("2", { selector: "strong" })).toHaveLength(5);
    expect(screen.getAllByText(result)).toHaveLength(2);
});

it("shows Market Variable and Artifact Signal evidence without predicate calculation", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { name: "Scientific Workstation" });
    await userEvent.click(screen.getByRole("tab", { name: "Market" }));
    expect(await screen.findByTestId("financial-chart")).toHaveTextContent(
        "1 authoritative markers"
    );
    await userEvent.selectOptions(screen.getByLabelText("Instrument"), "510500");
    await waitFor(() => {
        expect(screen.getByText(/market · 1 variable · 2 signal rows loaded/)).toBeInTheDocument();
    });
});

it("uses one Candidate selection for comparison and exact Graph", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { name: "Scientific Workstation" });
    await userEvent.click(screen.getByRole("tab", { name: "Candidates" }));
    expect(await screen.findByTestId("scientific-chart")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    const lastRow = rows.at(-1);
    expect(lastRow).toBeDefined();
    if (lastRow === undefined) return;
    await userEvent.click(within(lastRow).getByRole("button", { name: "Select" }));
    await userEvent.click(screen.getByRole("tab", { name: "Graph" }));
    expect(await screen.findByTestId("graphviz-view")).toBeInTheDocument();
    expect(screen.getByText(graphB)).toBeInTheDocument();
});

it("shows exact Market Variable Signal and Statistics tables", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { name: "Scientific Workstation" });
    await userEvent.click(screen.getByRole("tab", { name: "Exact Data" }));
    expect(await screen.findByRole("heading", { name: "Market" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Variable · rsi" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Signal · ENTRY_SIGNAL" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Statistics · IC" })).toBeInTheDocument();
    expect(screen.getAllByText("NULL").length).toBeGreaterThan(0);
});

it("reports unsupported Scientific evidence honestly while preserving Overview", async () => {
    const base = client();
    renderWorkspace(
        researchClient({
            ...base,
            getCandidateCatalog: async () => {
                throw new ResearchWebError("SCIENTIFIC_EVIDENCE_NOT_AVAILABLE", "V1 profile", 409);
            }
        })
    );
    expect(
        await screen.findByRole("heading", { name: "Scientific Workstation" })
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Graph" }));
    expect(screen.getByText(/Graph evidence is unavailable/)).toBeInTheDocument();
});

it("fails closed when Candidate and Graph linkage mismatch", async () => {
    const base = client();
    renderWorkspace(
        researchClient({
            ...base,
            getCandidateGraph: async () => ({
                ...(await base.getCandidateGraph(result, candidateA)),
                graphFingerprint: graphB
            })
        })
    );
    await screen.findByRole("heading", { name: "Scientific Workstation" });
    await userEvent.click(screen.getByRole("tab", { name: "Graph" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("linkage mismatch");
});

it("paginates exact data with the API cursor", async () => {
    const base = client();
    let marketRequests = 0;
    renderWorkspace(
        researchClient({
            ...base,
            getMarketSeries: async (_result, instrumentId, page) => {
                marketRequests += 1;
                const first = page?.afterTsEventNs === undefined;
                return {
                    researchResultFingerprint: result,
                    points: [
                        {
                            kind: "MARKET",
                            instrumentId,
                            tsEventNs: parseUnixNanoseconds(first ? "1000000000" : "2000000000"),
                            open: parseDecimalText("10"),
                            high: parseDecimalText("12"),
                            low: parseDecimalText("9"),
                            close: parseDecimalText("11"),
                            volume: parseDecimalText("100")
                        }
                    ],
                    hasMore: first,
                    nextAfterTsEventNs: first ? parseUnixNanoseconds("1000000000") : null
                };
            }
        })
    );
    await screen.findByRole("heading", { name: "Scientific Workstation" });
    await userEvent.click(screen.getByRole("tab", { name: "Exact Data" }));
    const marketSection = (await screen.findByRole("heading", { name: "Market" })).closest(
        "section"
    );
    expect(marketSection).not.toBeNull();
    if (marketSection === null) return;
    await userEvent.click(
        within(marketSection).getByRole("button", { name: "Load next exact page" })
    );
    await waitFor(() => {
        expect(within(marketSection).getByText("2 exact rows loaded")).toBeInTheDocument();
    });
    expect(marketRequests).toBe(2);
});
