import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import {
    parseResearchResultFingerprint,
    parseResearchRunId,
    parseResearchSubmissionKey,
    parseStatisticsFingerprint
} from "../../domain/research/identity";
import { parseUnixNanoseconds } from "../../domain/research/time";
import { FetchResearchApiClient } from "./client";
import { errorMessage, ResearchWebError } from "./errors";
import { mapResearchRun, mapStatisticSeriesPage } from "./mapper";
import { researchQueryKeys } from "./queryKeys";
import {
    artifactSummarySchema,
    researchCalculationCatalogSchema,
    researchCandidateCatalogSchema,
    researchCandidateGraphSchema,
    researchDefinitionResolutionSchema,
    researchErrorSchema,
    researchPublishedSeriesCatalogSchema,
    researchRunSchema,
    researchScientificSeriesPageSchema,
    statisticSeriesPageSchema
} from "./schemas";
import type { ResearchDefinitionTransport } from "./schemas";

const result = parseResearchResultFingerprint("a".repeat(64));
const statistics = parseStatisticsFingerprint("b".repeat(64));
const runId = parseResearchRunId("00000000-0000-4000-8000-000000000501");
const submissionKey = parseResearchSubmissionKey("00000000-0000-4000-8000-000000000502");
const point = {
    ts_event_ns: "1780000000000000123",
    statistic_value: "0.123400",
    sample_count: 4,
    status: "OK"
};
const page = {
    schema_version: 2 as const,
    research_result_fingerprint: result,
    statistics_fingerprint: statistics,
    points: [point],
    has_more: true,
    next_after_ts_event_ns: point.ts_event_ns
};
const summary = {
    schema_version: 2 as const,
    research_result_plan_fingerprint: "c".repeat(64),
    research_result_content_fingerprint: "d".repeat(64),
    research_result_fingerprint: result,
    dataset_snapshot_fingerprint: "e".repeat(64),
    artifact_content_fingerprint: "f".repeat(64),
    research_result_schema_version: 1,
    artifact_profile: "research-statistics-v1",
    artifact_schema_version: 1,
    statistics_count: 1,
    row_count: 1,
    candidate_count: 0,
    published_series_count: 0,
    signal_series_count: 0,
    market_row_count: 0,
    instrument_ids: [],
    created_at: "2026-08-16T00:00:00Z"
};
const descriptor = {
    statistics_fingerprint: statistics,
    statistics_result_fingerprint: "1".repeat(64),
    result_content_fingerprint: "2".repeat(64),
    statistics_result_schema_version: 1,
    row_count: 1,
    feature: {
        calculation_fingerprint: "3".repeat(64),
        node_fingerprint: "4".repeat(64),
        output_name: "score"
    },
    target: {
        calculation_fingerprint: "5".repeat(64),
        node_fingerprint: "6".repeat(64),
        output_name: "return"
    },
    definition: {
        method: "IC",
        minimum_observations: 2,
        pairing_policy: "PAIRWISE_COMPLETE",
        universe_policy: "EXACT",
        rank_tie_method: "AVERAGE",
        weighting: "EQUAL",
        numeric: {
            representation: "DECIMAL",
            precision: 38,
            output_quantum: "0.0001",
            rounding: "ROUND_HALF_EVEN"
        }
    }
};
const server = setupServer();
const run = {
    schema_version: 2 as const,
    run_id: runId,
    revision: "9007199254740993",
    state: "QUEUED" as const,
    specification_schema_version: 1,
    specification_fingerprint: "7".repeat(64),
    admission_resolution_fingerprint: "8".repeat(64),
    specification: { schema_version: 1 },
    queued_at: "2026-08-18T01:02:03Z",
    started_at: null,
    cancel_requested_at: null,
    finished_at: null,
    result_ref: null,
    artifact_ref: null,
    failure: null
};

const runSummary = (() => {
    const { specification, ...summaryValue } = run;
    void specification;
    return summaryValue;
})();

beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
});
afterEach(() => {
    server.resetHandlers();
});
afterAll(() => {
    server.close();
});

describe("Research API admission", () => {
    it("discovers capabilities and sends Definition transport unchanged", async () => {
        const authored = { schema_version: 1 } as unknown as ResearchDefinitionTransport;
        const resolution = {
            schema_version: 2 as const,
            authoring_definition_fingerprint: "1".repeat(64),
            resolved_definition_fingerprint: "2".repeat(64),
            dataset_snapshot_fingerprint: "3".repeat(64),
            specification_fingerprint: "4".repeat(64),
            resolved_dataset_definition: { schema_version: 1 },
            instrument_count: 2,
            candidate_count: 1,
            candidates: [
                {
                    ordinal: 0,
                    candidate_fingerprint: "5".repeat(64),
                    assignment: {},
                    calculation_fingerprint: "6".repeat(64),
                    graph_fingerprint: "7".repeat(64)
                }
            ],
            published_variables: [],
            exact_specification: { schema_version: 1 },
            diagnostics: []
        };
        server.use(
            http.get("*/api/v2/research/catalog/calculations", () =>
                HttpResponse.json({ schema_version: 2, calculations: [] })
            ),
            http.get("*/api/v2/research/catalog/universes", () =>
                HttpResponse.json({
                    schema_version: 2,
                    selection_kinds: ["SINGLE_INSTRUMENT"],
                    registered_universes: []
                })
            ),
            http.get("*/api/v2/research/catalog/statistics", () =>
                HttpResponse.json({ schema_version: 2, statistics: [] })
            ),
            http.get("*/api/v2/research/catalog/dataset-fields", () =>
                HttpResponse.json({ schema_version: 2, dataset_fields: [] })
            ),
            http.post("*/api/v2/research/definitions/resolve", async ({ request }) => {
                expect(await request.json()).toEqual(authored);
                return HttpResponse.json(resolution);
            })
        );
        const client = new FetchResearchApiClient();
        expect((await client.getCalculationCatalog()).calculations).toEqual([]);
        expect((await client.getUniverseCatalog()).registered_universes).toEqual([]);
        expect((await client.getStatisticsCapabilityCatalog()).statistics).toEqual([]);
        expect((await client.getDatasetFieldCatalog()).dataset_fields).toEqual([]);
        expect((await client.resolveDefinition(authored)).exact_specification).toEqual({
            schema_version: 1
        });
        expect(researchCalculationCatalogSchema.safeParse({ calculations: [] }).success).toBe(
            false
        );
        expect(researchDefinitionResolutionSchema.parse(resolution).candidate_count).toBe(1);
    });

    it("maps exact time and Decimal without Number conversion", () => {
        const mapped = mapStatisticSeriesPage(statisticSeriesPageSchema.parse(page));
        expect(mapped.points[0]?.tsEventNs).toBe(1_780_000_000_000_000_123n);
        expect(mapped.points[0]?.statisticValue).toBe("0.123400");
        expect(mapped.nextAfterTsEventNs).toBe(1_780_000_000_000_000_123n);
        expect(
            mapStatisticSeriesPage(
                statisticSeriesPageSchema.parse({
                    ...page,
                    points: [{ ...point, statistic_value: null }]
                })
            ).points[0]?.statisticValue
        ).toBeNull();
    });

    it("rejects invalid integers, Decimals, fingerprints, and extra fields", () => {
        expect(
            statisticSeriesPageSchema.safeParse({
                ...page,
                points: [{ ...point, ts_event_ns: "01" }]
            }).success
        ).toBe(false);
        expect(
            statisticSeriesPageSchema.safeParse({
                ...page,
                points: [{ ...point, statistic_value: "NaN" }]
            }).success
        ).toBe(false);
        expect(
            statisticSeriesPageSchema.safeParse({ ...page, statistics_fingerprint: "BAD" }).success
        ).toBe(false);
        expect(statisticSeriesPageSchema.safeParse({ ...page, unexpected: true }).success).toBe(
            false
        );
        expect(
            researchErrorSchema.safeParse({ schema_version: 2, code: "OTHER", detail: "x" }).success
        ).toBe(false);
        expect(artifactSummarySchema.safeParse({}).success).toBe(false);
        expect(
            artifactSummarySchema.safeParse({ ...summary, instrument_ids: ["B", "A"] }).success
        ).toBe(false);
        expect(
            statisticSeriesPageSchema.safeParse({
                ...page,
                points: [point, { ...point, ts_event_ns: "1780000000000000124" }],
                has_more: false,
                next_after_ts_event_ns: null
            }).success
        ).toBe(true);
        for (const malformed of [
            {
                ...page,
                points: [
                    { ...point, ts_event_ns: "2" },
                    { ...point, ts_event_ns: "1" }
                ]
            },
            { ...page, points: [], has_more: true, next_after_ts_event_ns: null },
            { ...page, has_more: false, next_after_ts_event_ns: point.ts_event_ns }
        ])
            expect(statisticSeriesPageSchema.safeParse(malformed).success).toBe(false);
    });

    it("sends an exact cursor and admits a successful page", async () => {
        server.use(
            http.get(
                `*/api/v2/research/artifacts/${result}/statistics/${statistics}/series`,
                ({ request }) => {
                    expect(new URL(request.url).searchParams.get("after_ts_event_ns")).toBe(
                        "1780000000000000123"
                    );
                    return HttpResponse.json(page);
                }
            )
        );
        const response = await new FetchResearchApiClient().getStatisticSeries({
            researchResultFingerprint: result,
            statisticsFingerprint: statistics,
            afterTsEventNs: parseUnixNanoseconds("1780000000000000123"),
            fromTsEventNs: parseUnixNanoseconds("0"),
            toTsEventNs: parseUnixNanoseconds("1780000000000000124"),
            limit: 1
        });
        expect(response.nextAfterTsEventNs?.toString()).toBe("1780000000000000123");
    });

    it("submits with an idempotency key and preserves exact Run revision", async () => {
        server.use(
            http.post("*/api/v2/research/runs", async ({ request }) => {
                expect(request.headers.get("Idempotency-Key")).toBe(submissionKey);
                expect(await request.json()).toEqual({ specification: run.specification });
                return HttpResponse.json(
                    { submission_disposition: "CREATED", run },
                    { status: 202 }
                );
            })
        );
        const submitted = await new FetchResearchApiClient().submitRun(
            run.specification,
            submissionKey
        );
        expect(submitted.run.runId).toBe(runId);
        expect(submitted.run.revision).toBe(9_007_199_254_740_993n);
        expect(mapResearchRun(researchRunSchema.parse(run)).revision).toBe(9_007_199_254_740_993n);
        expect(researchQueryKeys.run(runId)).toEqual(["research", "run", runId]);
        expect(researchQueryKeys.runs()).toEqual(["research", "runs"]);
    });

    it("gets, pages and cancels Runs through strict contracts", async () => {
        server.use(
            http.get(`*/api/v2/research/runs/${runId}`, () => HttpResponse.json(run)),
            http.get("*/api/v2/research/runs", ({ request }) => {
                expect(new URL(request.url).searchParams.get("cursor")).toBe("cursor-v1");
                return HttpResponse.json({
                    schema_version: 2,
                    runs: [runSummary],
                    has_more: false,
                    next_cursor: null
                });
            }),
            http.post(`*/api/v2/research/runs/${runId}/cancellation`, () =>
                HttpResponse.json({
                    ...run,
                    revision: "9007199254740994",
                    state: "CANCELLED",
                    finished_at: "2026-08-18T01:02:04Z"
                })
            )
        );
        const client = new FetchResearchApiClient();
        expect((await client.getRun(runId)).runId).toBe(runId);
        expect((await client.listRuns(50, "cursor-v1")).nextCursor).toBeNull();
        expect((await client.cancelRun(runId)).state).toBe("CANCELLED");
    });

    it("decodes stable Run errors and rejects noncanonical Run identity", async () => {
        server.use(
            http.get(`*/api/v2/research/runs/${runId}`, () =>
                HttpResponse.json(
                    {
                        error: {
                            phase: "QUERY",
                            code: "RESEARCH_RUN_NOT_FOUND",
                            detail: "missing"
                        }
                    },
                    { status: 404 }
                )
            )
        );
        await expect(new FetchResearchApiClient().getRun(runId)).rejects.toMatchObject({
            code: "RESEARCH_RUN_NOT_FOUND",
            status: 404
        });
        expect(() => parseResearchRunId("BAD")).toThrow("canonical UUID4");
        expect(
            statisticSeriesPageSchema.safeParse({ ...page, next_after_ts_event_ns: null }).success
        ).toBe(false);
    });

    it("admits and maps summary and catalog operations", async () => {
        server.use(
            http.get(`*/api/v2/research/artifacts/${result}`, () => HttpResponse.json(summary)),
            http.get(`*/api/v2/research/artifacts/${result}/statistics`, () =>
                HttpResponse.json({
                    schema_version: 2,
                    research_result_fingerprint: result,
                    statistics: [descriptor]
                })
            )
        );
        const client = new FetchResearchApiClient();
        expect((await client.getArtifactSummary(result)).artifactProfile).toBe(
            "research-statistics-v1"
        );
        expect(
            (await client.getStatisticsCatalog(result)).statistics[0]?.definition.numeric
                .outputQuantum
        ).toBe("0.0001");
    });

    it("admits artifact-only scientific catalogs, exact series and graph", async () => {
        const candidate = "9".repeat(64);
        const calculation = "8".repeat(64);
        const node = "7".repeat(64);
        const catalog = {
            schema_version: 2,
            research_result_fingerprint: result,
            candidates: [
                {
                    candidate_fingerprint: candidate,
                    candidate_calculation_id: "decision",
                    assignment: {
                        missing: null,
                        enabled: true,
                        period: 14,
                        quantum: "0.1",
                        label: "RSI"
                    },
                    assignment_types: {
                        missing: "NULL",
                        enabled: "BOOLEAN",
                        period: "INTEGER",
                        quantum: "DECIMAL",
                        label: "STRING"
                    },
                    calculation_fingerprint: calculation,
                    graph_fingerprint: "6".repeat(64),
                    statistics_fingerprints: [statistics],
                    signal_roles: ["ENTRY_SIGNAL", "EXIT_SIGNAL"]
                }
            ]
        };
        const variables = {
            schema_version: 2,
            research_result_fingerprint: result,
            series: [
                {
                    candidate_fingerprint: candidate,
                    calculation_fingerprint: calculation,
                    node_fingerprint: node,
                    output_name: "value",
                    value_kind: "DECIMAL"
                },
                {
                    candidate_fingerprint: null,
                    calculation_fingerprint: calculation,
                    node_fingerprint: node,
                    output_name: "global_value",
                    value_kind: "DECIMAL"
                }
            ]
        };
        const marketPage = {
            schema_version: 2,
            research_result_fingerprint: result,
            points: [
                {
                    instrument_id: "TEST",
                    ts_event_ns: "1780000000000000123",
                    open: "1.0",
                    high: "2.0",
                    low: "0.5",
                    close: "1.5",
                    volume: "10.0"
                }
            ],
            has_more: false,
            next_after_ts_event_ns: null
        };
        const variablePage = {
            ...marketPage,
            points: [
                {
                    instrument_id: "TEST",
                    ts_event_ns: "1780000000000000123",
                    value_kind: "DECIMAL",
                    decimal_value: "0.123400",
                    integer_value: null,
                    boolean_value: null,
                    string_value: null
                }
            ]
        };
        const signalPage = {
            ...marketPage,
            points: [
                {
                    instrument_id: "TEST",
                    ts_event_ns: "1780000000000000123",
                    value: null
                }
            ]
        };
        const graph = {
            schema_version: 1 as const,
            nodes: [
                {
                    node_fingerprint: node,
                    alias: "rsi",
                    definition: {
                        schema_version: 2 as const,
                        kind: "INDICATOR" as const,
                        type_id: "onlyalpha.indicator.rsi",
                        semantic_version: "1",
                        parameters: {
                            period: { type: "INTEGER" as const, value: 14 },
                            threshold: { type: "DECIMAL" as const, value: "30.0" },
                            enabled: { type: "BOOLEAN" as const, value: true },
                            label: { type: "STRING" as const, value: "entry" },
                            missing: { type: "NULL" as const, value: null }
                        },
                        inputs: [
                            {
                                name: "price",
                                data_type: "DECIMAL" as const,
                                nullable: false,
                                dimensions: ["INSTRUMENT", "TIME"],
                                semantic_type: "PRICE",
                                unit: "PRICE"
                            }
                        ],
                        input_bindings: {
                            price: {
                                node_fingerprint: null,
                                output_name: "close",
                                source: "bar.close"
                            }
                        },
                        outputs: [
                            {
                                name: "value",
                                data_type: "DECIMAL" as const,
                                nullable: true,
                                dimensions: ["INSTRUMENT", "TIME"],
                                semantic_type: "INDICATOR_VALUE",
                                unit: null
                            }
                        ],
                        warmup: {
                            minimum_observations: 14,
                            ready_condition: "COUNT_GTE_MINIMUM",
                            pre_ready_output: "NULL" as const,
                            initialization: "FIRST_WINDOW"
                        },
                        missing_values: "PROPAGATE" as const,
                        timestamp: "EVENT_TIME" as const,
                        numeric: {
                            representation: "DECIMAL",
                            precision: 38,
                            output_quantum: null,
                            rounding: "ROUND_HALF_EVEN"
                        },
                        factor_kind: null,
                        extensions: { note: { type: "STRING" as const, value: "exact" } }
                    }
                }
            ]
        };
        server.use(
            http.get(`*/api/v2/research/artifacts/${result}/candidates`, () =>
                HttpResponse.json(catalog)
            ),
            http.get(`*/api/v2/research/artifacts/${result}/variables`, () =>
                HttpResponse.json(variables)
            ),
            http.get(`*/api/v2/research/artifacts/${result}/market/series`, () =>
                HttpResponse.json(marketPage)
            ),
            http.get(
                `*/api/v2/research/artifacts/${result}/variables/${calculation}/${node}/value/series`,
                () => HttpResponse.json(variablePage)
            ),
            http.get(
                `*/api/v2/research/artifacts/${result}/signals/${candidate}/ENTRY_SIGNAL/series`,
                () => HttpResponse.json(signalPage)
            ),
            http.get(`*/api/v2/research/artifacts/${result}/candidates/${candidate}/graph`, () =>
                HttpResponse.json({
                    schema_version: 2,
                    research_result_fingerprint: result,
                    candidate_fingerprint: candidate,
                    calculation_fingerprint: calculation,
                    graph_fingerprint: "6".repeat(64),
                    graph
                })
            )
        );
        const client = new FetchResearchApiClient();
        expect((await client.getCandidateCatalog(result)).candidates).toHaveLength(1);
        expect((await client.getPublishedSeriesCatalog(result)).series).toHaveLength(2);
        expect((await client.getMarketSeries(result, "TEST")).points).toHaveLength(1);
        expect(
            (
                await client.getVariableSeries({
                    researchResultFingerprint: result,
                    instrumentId: "TEST",
                    candidateFingerprint: candidate,
                    calculationFingerprint: calculation,
                    nodeFingerprint: node,
                    outputName: "value"
                })
            ).points
        ).toHaveLength(1);
        expect(
            (
                await client.getSignalSeries({
                    researchResultFingerprint: result,
                    instrumentId: "TEST",
                    candidateFingerprint: candidate,
                    role: "ENTRY_SIGNAL"
                })
            ).points[0]
        ).toMatchObject({ value: null });
        const admittedGraph = await client.getCandidateGraph(result, candidate);
        expect(admittedGraph.graph.schemaVersion).toBe(1);
        expect(admittedGraph.graph.nodes[0]).toMatchObject({
            nodeFingerprint: node,
            alias: "rsi",
            definition: {
                typeId: "onlyalpha.indicator.rsi",
                parameters: {
                    period: { type: "INTEGER", value: 14 },
                    threshold: { type: "DECIMAL", value: "30.0" }
                },
                numeric: { outputQuantum: null },
                extensions: { note: { type: "STRING", value: "exact" } }
            }
        });
        expect(
            researchCandidateGraphSchema.safeParse({
                schema_version: 2,
                research_result_fingerprint: result,
                candidate_fingerprint: candidate,
                calculation_fingerprint: calculation,
                graph_fingerprint: "6".repeat(64),
                graph: { ...graph, unexpected: true }
            }).success
        ).toBe(false);
        expect(researchCandidateCatalogSchema.parse(catalog).candidates[0]?.assignment).toEqual(
            catalog.candidates[0]?.assignment
        );
        for (const malformed of [
            {
                ...catalog,
                candidates: [{ ...catalog.candidates[0], assignment_types: { period: "INTEGER" } }]
            },
            {
                ...catalog,
                candidates: [
                    {
                        ...catalog.candidates[0],
                        assignment: { period: "14" },
                        assignment_types: { period: "INTEGER" }
                    }
                ]
            },
            {
                ...catalog,
                candidates: [
                    {
                        ...catalog.candidates[0],
                        statistics_fingerprints: [statistics, statistics]
                    }
                ]
            },
            {
                ...catalog,
                candidates: [
                    {
                        ...catalog.candidates[0],
                        signal_roles: ["ENTRY_SIGNAL", "ENTRY_SIGNAL"]
                    }
                ]
            },
            { ...catalog, candidates: [catalog.candidates[0], catalog.candidates[0]] }
        ])
            expect(researchCandidateCatalogSchema.safeParse(malformed).success).toBe(false);
        expect(
            researchPublishedSeriesCatalogSchema.safeParse({
                ...variables,
                series: [variables.series[0], variables.series[0]]
            }).success
        ).toBe(false);
        expect(
            researchScientificSeriesPageSchema.safeParse({
                ...variablePage,
                points: [
                    {
                        ...variablePage.points[0],
                        boolean_value: true
                    }
                ]
            }).success
        ).toBe(false);
        expect(
            researchScientificSeriesPageSchema.safeParse({
                ...marketPage,
                points: [
                    marketPage.points[0],
                    { ...marketPage.points[0], ts_event_ns: "1780000000000000124" }
                ],
                has_more: true,
                next_after_ts_event_ns: "1780000000000000124"
            }).success
        ).toBe(true);
        for (const malformed of [
            { ...marketPage, points: [], has_more: true, next_after_ts_event_ns: null },
            {
                ...marketPage,
                points: [
                    { ...marketPage.points[0], ts_event_ns: "1780000000000000124" },
                    marketPage.points[0]
                ]
            },
            { ...marketPage, next_after_ts_event_ns: "1780000000000000123" }
        ])
            expect(researchScientificSeriesPageSchema.safeParse(malformed).success).toBe(false);
        const graphEnvelope = {
            schema_version: 2,
            research_result_fingerprint: result,
            candidate_fingerprint: candidate,
            calculation_fingerprint: calculation,
            graph_fingerprint: "6".repeat(64)
        };
        expect(
            researchCandidateGraphSchema.safeParse({
                ...graphEnvelope,
                graph: { ...graph, nodes: [graph.nodes[0], graph.nodes[0]] }
            }).success
        ).toBe(false);
        expect(
            researchCandidateGraphSchema.safeParse({
                ...graphEnvelope,
                graph: {
                    ...graph,
                    nodes: [
                        {
                            ...graph.nodes[0],
                            definition: { ...graph.nodes[0]?.definition, input_bindings: {} }
                        }
                    ]
                }
            }).success
        ).toBe(false);
        expect(
            researchCandidateGraphSchema.safeParse({
                ...graphEnvelope,
                graph: {
                    ...graph,
                    nodes: [
                        {
                            ...graph.nodes[0],
                            definition: {
                                ...graph.nodes[0]?.definition,
                                input_bindings: {
                                    price: {
                                        node_fingerprint: "f".repeat(64),
                                        output_name: "close",
                                        source: null
                                    }
                                }
                            }
                        }
                    ]
                }
            }).success
        ).toBe(false);
        expect(
            researchCandidateGraphSchema.safeParse({
                schema_version: 2,
                research_result_fingerprint: result,
                candidate_fingerprint: candidate,
                calculation_fingerprint: calculation,
                graph_fingerprint: "6".repeat(64),
                graph: {
                    ...graph,
                    nodes: [
                        {
                            ...graph.nodes[0],
                            definition: {
                                ...graph.nodes[0]?.definition,
                                parameters: { period: { type: "INTEGER", value: "14" } }
                            }
                        }
                    ]
                }
            }).success
        ).toBe(false);
        await expect(
            client.getVariableSeries({ researchResultFingerprint: result, instrumentId: "TEST" })
        ).rejects.toMatchObject({ code: "CONTRACT_ERROR" });
        await expect(
            client.getSignalSeries({ researchResultFingerprint: result, instrumentId: "TEST" })
        ).rejects.toMatchObject({ code: "CONTRACT_ERROR" });
    });

    it.each([
        [404, "RESEARCH_ARTIFACT_NOT_FOUND"],
        [500, "RESEARCH_ARTIFACT_CORRUPT"]
    ])("formally decodes API error %s", async (status, code) => {
        server.use(
            http.get(`*/api/v2/research/artifacts/${result}`, () =>
                HttpResponse.json({ schema_version: 2, code, detail: "exact failure" }, { status })
            )
        );
        await expect(new FetchResearchApiClient().getArtifactSummary(result)).rejects.toMatchObject(
            { code, status }
        );
    });

    it("distinguishes contract and transport failures", async () => {
        server.use(
            http.get(`*/api/v2/research/artifacts/${result}`, () =>
                HttpResponse.json({ bad: true })
            )
        );
        await expect(new FetchResearchApiClient().getArtifactSummary(result)).rejects.toMatchObject(
            { code: "CONTRACT_ERROR" }
        );
        server.use(
            http.get(`*/api/v2/research/artifacts/${result}`, () => HttpResponse.text("bad json"))
        );
        await expect(new FetchResearchApiClient().getArtifactSummary(result)).rejects.toMatchObject(
            { code: "CONTRACT_ERROR" }
        );
        server.use(http.get(`*/api/v2/research/artifacts/${result}`, () => HttpResponse.error()));
        await expect(new FetchResearchApiClient().getArtifactSummary(result)).rejects.toMatchObject(
            { code: "TRANSPORT_ERROR" }
        );
        server.use(
            http.get(`*/api/v2/research/artifacts/${result}`, () =>
                HttpResponse.json({ bad: true }, { status: 404 })
            )
        );
        await expect(new FetchResearchApiClient().getArtifactSummary(result)).rejects.toMatchObject(
            { code: "CONTRACT_ERROR", status: 404 }
        );
    });

    it("decodes strict Definition validation failures", async () => {
        server.use(
            http.post("*/api/v2/research/definitions/resolve", () =>
                HttpResponse.json(
                    {
                        error: {
                            phase: "ADMISSION",
                            code: "RESEARCH_DEFINITION_INVALID",
                            detail: "invalid exact definition",
                            path: "calculations[0]"
                        }
                    },
                    { status: 422 }
                )
            )
        );
        await expect(
            new FetchResearchApiClient().resolveDefinition({
                schema_version: 1
            } as unknown as ResearchDefinitionTransport)
        ).rejects.toMatchObject({
            code: "RESEARCH_DEFINITION_INVALID",
            phase: "ADMISSION",
            path: "calculations[0]"
        });
    });

    it("preserves AbortError instead of relabeling cancellation", async () => {
        const aborted = vi
            .spyOn(globalThis, "fetch")
            .mockRejectedValueOnce(new DOMException("aborted", "AbortError"));
        await expect(
            new FetchResearchApiClient().getArtifactSummary(result, new AbortController().signal)
        ).rejects.toMatchObject({ name: "AbortError" });
        aborted.mockRestore();
    });

    it("uses exact identity and range in deterministic query keys", () => {
        expect(
            researchQueryKeys.series(
                result,
                statistics,
                parseUnixNanoseconds("1"),
                parseUnixNanoseconds("2")
            )
        ).toEqual(["research", "series", result, statistics, "1", "2"]);
        expect(researchQueryKeys.artifact(result)).toEqual(["research", "artifact", result]);
        expect(researchQueryKeys.statistics(result)).toEqual(["research", "statistics", result]);
    });

    it("keeps typed Research errors machine readable", () => {
        const error = new ResearchWebError("INVALID_QUERY", "invalid", 400);
        expect(error.name).toBe("ResearchWebError");
        expect(error.status).toBe(400);
        expect(errorMessage(error)).toBe("INVALID_QUERY: invalid");
        expect(errorMessage(new Error("other"))).toBe("Unexpected error");
    });
});
