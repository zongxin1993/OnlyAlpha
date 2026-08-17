import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import {
    parseResearchResultFingerprint,
    parseStatisticsFingerprint
} from "../../domain/research/identity";
import { parseUnixNanoseconds } from "../../domain/research/time";
import { FetchResearchApiClient } from "./client";
import { errorMessage, ResearchWebError } from "./errors";
import { mapStatisticSeriesPage } from "./mapper";
import { researchQueryKeys } from "./queryKeys";
import { artifactSummarySchema, researchErrorSchema, statisticSeriesPageSchema } from "./schemas";

const result = parseResearchResultFingerprint("a".repeat(64));
const statistics = parseStatisticsFingerprint("b".repeat(64));
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
