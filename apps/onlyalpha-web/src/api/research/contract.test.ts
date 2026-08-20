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
    researchDefinitionResolutionSchema,
    researchErrorSchema,
    researchRunSchema,
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
            mapStatisticSeriesPage(
                statisticSeriesPageSchema.parse({ ...page, next_after_ts_event_ns: null })
            ).nextAfterTsEventNs
        ).toBeNull();
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
