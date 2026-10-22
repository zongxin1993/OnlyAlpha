import {
    parseResearchResultFingerprint,
    parseResearchRunId,
    parseStatisticsFingerprint
} from "../../domain/research/identity";
import { parseUnixNanoseconds } from "../../domain/research/time";
import { errorMessage, ResearchWebError } from "./errors";
import {
    mapArtifactSummary,
    mapCandidateCatalog,
    mapCandidateGraph,
    mapPublishedSeriesCatalog,
    mapResearchRun,
    mapResearchRunPage,
    mapResearchRunSubmission,
    mapScientificSeriesPage,
    mapStatisticSeriesPage,
    mapStatisticsCatalog
} from "./mapper";
import { researchQueryKeys } from "./queryKeys";
import {
    artifactSummarySchema,
    researchCalculationCatalogSchema,
    researchCandidateCatalogSchema,
    researchCandidateGraphSchema,
    researchErrorSchema,
    researchPublishedSeriesCatalogSchema,
    researchRunSchema,
    researchRunPageSchema,
    researchRunSubmissionSchema,
    researchRunErrorSchema,
    statisticsCatalogSchema,
    researchScientificSeriesPageSchema,
    statisticSeriesPageSchema
} from "./schemas";

const result = parseResearchResultFingerprint("a".repeat(64));
const statistics = parseStatisticsFingerprint("b".repeat(64));
const runId = parseResearchRunId("00000000-0000-4000-8000-000000000501");
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

describe("independent immutable evidence format admission", () => {
    it("retains the active catalog's required schema version", () => {
        expect(researchCalculationCatalogSchema.safeParse({ calculations: [] }).success).toBe(
            false
        );
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

    it("preserves exact Run revisions, page observations and cancellation facts", () => {
        const submitted = mapResearchRunSubmission(
            researchRunSubmissionSchema.parse({ submission_disposition: "CREATED", run })
        );
        expect(submitted.run.runId).toBe(runId);
        expect(submitted.run.revision).toBe(9_007_199_254_740_993n);
        expect(mapResearchRun(researchRunSchema.parse(run)).revision).toBe(9_007_199_254_740_993n);
        expect(mapResearchRun(researchRunSchema.parse(run)).runId).toBe(runId);
        expect(
            mapResearchRunPage(
                researchRunPageSchema.parse({
                    schema_version: 2,
                    runs: [runSummary],
                    has_more: false,
                    next_cursor: null
                })
            ).nextCursor
        ).toBeNull();
        expect(
            mapResearchRun(
                researchRunSchema.parse({
                    ...run,
                    revision: "9007199254740994",
                    state: "CANCELLED",
                    finished_at: "2026-08-18T01:02:04Z"
                })
            ).state
        ).toBe("CANCELLED");
        expect(researchQueryKeys.run(runId)).toEqual(["research", "run", runId]);
        expect(researchQueryKeys.runs()).toEqual(["research", "runs"]);
        expect(() => parseResearchRunId("BAD")).toThrow("canonical UUID4");
        expect(
            statisticSeriesPageSchema.safeParse({ ...page, next_after_ts_event_ns: null }).success
        ).toBe(false);
        expect(
            researchRunErrorSchema.parse({
                error: { phase: "QUERY", code: "RESEARCH_RUN_NOT_FOUND", detail: "missing" }
            }).error.code
        ).toBe("RESEARCH_RUN_NOT_FOUND");
    });
    it("retains independent artifact summary and catalog numeric formats", () => {
        expect(mapArtifactSummary(artifactSummarySchema.parse(summary)).artifactProfile).toBe(
            "research-statistics-v1"
        );
        expect(
            mapStatisticsCatalog(
                statisticsCatalogSchema.parse({
                    schema_version: 2,
                    research_result_fingerprint: result,
                    statistics: [descriptor]
                })
            ).statistics[0]?.definition.numeric.outputQuantum
        ).toBe("0.0001");
    });
    it("admits artifact-only scientific catalogs, exact series and graph", () => {
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
                            period: { type: "INTEGER" as const, value: "14" },
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
        expect(
            mapCandidateCatalog(researchCandidateCatalogSchema.parse(catalog)).candidates
        ).toHaveLength(1);
        expect(
            mapPublishedSeriesCatalog(researchPublishedSeriesCatalogSchema.parse(variables)).series
        ).toHaveLength(2);
        expect(
            mapScientificSeriesPage(researchScientificSeriesPageSchema.parse(marketPage)).points
        ).toHaveLength(1);
        expect(
            mapScientificSeriesPage(researchScientificSeriesPageSchema.parse(variablePage)).points
        ).toHaveLength(1);
        expect(
            mapScientificSeriesPage(researchScientificSeriesPageSchema.parse(signalPage)).points[0]
        ).toMatchObject({ value: null });
        const admittedGraph = mapCandidateGraph(
            researchCandidateGraphSchema.parse({
                schema_version: 2,
                research_result_fingerprint: result,
                candidate_fingerprint: candidate,
                calculation_fingerprint: calculation,
                graph_fingerprint: "6".repeat(64),
                graph
            })
        );
        expect(admittedGraph.graph.schemaVersion).toBe(1);
        expect(admittedGraph.graph.nodes[0]).toMatchObject({
            nodeFingerprint: node,
            alias: "rsi",
            definition: {
                typeId: "onlyalpha.indicator.rsi",
                parameters: {
                    period: { type: "INTEGER", value: "14" },
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
            {
                ...catalog,
                candidates: [{ ...catalog.candidates[0], signal_roles: ["ENTRY_GUESSED"] }]
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
                                parameters: { period: { type: "INTEGER", value: 14 } }
                            }
                        }
                    ]
                }
            }).success
        ).toBe(false);
    });

    it("uses exact identity and range in deterministic query keys", () => {
        expect(
            researchQueryKeys.series(
                result,
                statistics,
                100,
                parseUnixNanoseconds("1"),
                parseUnixNanoseconds("2")
            )
        ).toEqual(["research", "series", result, statistics, 100, "1", "2"]);
        expect(researchQueryKeys.series(result, statistics, 100)).not.toEqual(
            researchQueryKeys.series(result, statistics, 500)
        );
        expect(researchQueryKeys.market(result, "A", 100)).toEqual(
            researchQueryKeys.market(result, "A", 100)
        );
        expect(researchQueryKeys.market(result, "A", 100)).not.toEqual(
            researchQueryKeys.market(result, "A", 500)
        );
        expect(researchQueryKeys.market(result, "A", 100)).not.toEqual(
            researchQueryKeys.market(result, "B", 100)
        );
        expect(
            researchQueryKeys.signal(result, "e".repeat(64), "ENTRY_SIGNAL", "A", 100)
        ).not.toEqual(researchQueryKeys.signal(result, "f".repeat(64), "ENTRY_SIGNAL", "A", 100));
        expect(
            researchQueryKeys.variable(
                result,
                "e".repeat(64),
                "c".repeat(64),
                "d".repeat(64),
                "score",
                "A",
                100
            )
        ).not.toEqual(
            researchQueryKeys.variable(
                result,
                "f".repeat(64),
                "c".repeat(64),
                "d".repeat(64),
                "score",
                "A",
                100
            )
        );
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
    it("retains exact graph structural rejection claims independently of retired Python HTTP", () => {
        const port = {
            name: "x",
            data_type: "DECIMAL",
            nullable: true,
            dimensions: [],
            semantic_type: "VALUE",
            unit: null
        };
        const valid = researchCandidateGraphSchema.parse({
            schema_version: 2,
            research_result_fingerprint: "a".repeat(64),
            candidate_fingerprint: "b".repeat(64),
            calculation_fingerprint: "c".repeat(64),
            graph_fingerprint: "d".repeat(64),
            graph: {
                schema_version: 1,
                nodes: [
                    {
                        node_fingerprint: "e".repeat(64),
                        alias: null,
                        definition: {
                            schema_version: 2,
                            kind: "INDICATOR",
                            type_id: "test.indicator",
                            semantic_version: "1",
                            parameters: {},
                            inputs: [port],
                            input_bindings: {
                                x: {
                                    node_fingerprint: null,
                                    output_name: "close",
                                    source: "bar.close"
                                }
                            },
                            outputs: [{ ...port, name: "value" }],
                            warmup: {
                                minimum_observations: 1,
                                ready_condition: "ready",
                                pre_ready_output: "NULL",
                                initialization: "UPSTREAM"
                            },
                            missing_values: "PROPAGATE",
                            timestamp: "EVENT_TIME",
                            numeric: {
                                representation: "DECIMAL",
                                precision: 12,
                                output_quantum: null,
                                rounding: "HALF_EVEN"
                            },
                            factor_kind: null,
                            extensions: {}
                        }
                    }
                ]
            }
        });
        type Node = (typeof valid.graph.nodes)[number];
        const cases: readonly [
            string,
            readonly string[],
            readonly (string | number)[],
            (node: Node) => void
        ][] = [
            [
                "missing reference owner",
                ["exactly one"],
                ["graph", "nodes", 0, "definition", "input_bindings", "x"],
                (node) => {
                    node.definition.input_bindings.x = {
                        node_fingerprint: null,
                        output_name: "close",
                        source: null
                    };
                }
            ],
            [
                "ambiguous reference owner",
                ["exactly one"],
                ["graph", "nodes", 0, "definition", "input_bindings", "x"],
                (node) => {
                    node.definition.input_bindings.x = {
                        node_fingerprint: "f".repeat(64),
                        output_name: "value",
                        source: "bar.close"
                    };
                }
            ],
            [
                "duplicate input port",
                ["ports must be unique", "input bindings mismatch"],
                [],
                (node) => {
                    node.definition.inputs.push({ ...port, data_type: "DECIMAL" });
                }
            ],
            [
                "duplicate output port",
                ["ports must be unique"],
                ["graph", "nodes", 0, "definition"],
                (node) => {
                    node.definition.outputs.push({ ...port, data_type: "DECIMAL", name: "value" });
                }
            ],
            [
                "non-factor with factor_kind",
                ["factor_kind"],
                ["graph", "nodes", 0, "definition"],
                (node) => {
                    node.definition.factor_kind = "TIME_SERIES";
                }
            ],
            [
                "factor missing factor_kind",
                ["factor_kind"],
                ["graph", "nodes", 0, "definition"],
                (node) => {
                    node.definition.kind = "FACTOR";
                }
            ],
            [
                "dangling dependency",
                ["dependency is missing"],
                ["graph"],
                (node) => {
                    node.definition.input_bindings.x = {
                        node_fingerprint: "f".repeat(64),
                        output_name: "value",
                        source: null
                    };
                }
            ]
        ];
        // Collect every mutation before asserting so one defect cannot hide the rest.
        const results = cases.map(([name, messages, path, mutate]) => {
            const malformed = structuredClone(valid);
            const node = malformed.graph.nodes[0];
            if (!node) throw new Error("Graph fixture requires its exact original node");
            mutate(node);
            const parsed = researchCandidateGraphSchema.safeParse(malformed);
            return {
                name,
                rejected: !parsed.success,
                owningIssue:
                    !parsed.success &&
                    parsed.error.issues.some((issue) => {
                        if (name === "duplicate input port") {
                            return (
                                (issue.message.includes("ports must be unique") &&
                                    JSON.stringify(issue.path) ===
                                        JSON.stringify(["graph", "nodes", 0, "definition"])) ||
                                (issue.message.includes("input bindings mismatch") &&
                                    JSON.stringify(issue.path) === JSON.stringify(["graph"]))
                            );
                        }
                        return (
                            messages.some((message) => issue.message.includes(message)) &&
                            JSON.stringify(issue.path) === JSON.stringify(path)
                        );
                    })
            };
        });
        const doubled = structuredClone(valid);
        const node = doubled.graph.nodes[0];
        if (!node) throw new Error("Graph fixture requires its exact original node");
        doubled.graph.nodes.push(node);
        const parsed = researchCandidateGraphSchema.safeParse(doubled);
        results.push({
            name: "duplicate node identity",
            rejected: !parsed.success,
            owningIssue:
                !parsed.success &&
                parsed.error.issues.some(
                    (issue) =>
                        issue.message.includes("nodes are duplicated") &&
                        JSON.stringify(issue.path) === JSON.stringify(["graph"])
                )
        });
        expect(results).toEqual(
            results.map(({ name }) => ({ name, rejected: true, owningIssue: true }))
        );
    });
});
