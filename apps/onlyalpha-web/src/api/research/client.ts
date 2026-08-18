import type {
    ResearchResultFingerprint,
    ResearchRunId,
    ResearchSubmissionKey,
    StatisticsFingerprint
} from "../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchRun,
    ResearchRunPage,
    ResearchRunSubmission,
    ResearchStatisticSeriesPage,
    ResearchStatisticsCatalog
} from "../../domain/research/model";
import type { UnixNanoseconds } from "../../domain/research/time";
import { nanosecondsToRequestText } from "../../domain/research/time";
import { ResearchWebError } from "./errors";
import {
    mapArtifactSummary,
    mapResearchRun,
    mapResearchRunPage,
    mapResearchRunSubmission,
    mapStatisticSeriesPage,
    mapStatisticsCatalog
} from "./mapper";
import {
    artifactSummarySchema,
    researchErrorSchema,
    researchRunErrorSchema,
    researchRunPageSchema,
    researchRunSchema,
    researchRunSubmissionSchema,
    statisticSeriesPageSchema,
    statisticsCatalogSchema
} from "./schemas";

export interface StatisticSeriesRequest {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly statisticsFingerprint: StatisticsFingerprint;
    readonly fromTsEventNs?: UnixNanoseconds;
    readonly toTsEventNs?: UnixNanoseconds;
    readonly afterTsEventNs?: UnixNanoseconds;
    readonly limit: number;
}

export interface ResearchRunApiClient {
    submitRun(
        specification: Readonly<Record<string, unknown>>,
        submissionKey: ResearchSubmissionKey,
        signal?: AbortSignal
    ): Promise<ResearchRunSubmission>;
    getRun(id: ResearchRunId, signal?: AbortSignal): Promise<ResearchRun>;
    listRuns(limit: number, cursor?: string, signal?: AbortSignal): Promise<ResearchRunPage>;
    cancelRun(id: ResearchRunId, signal?: AbortSignal): Promise<ResearchRun>;
}

export interface ResearchArtifactApiClient {
    getArtifactSummary(
        id: ResearchResultFingerprint,
        signal?: AbortSignal
    ): Promise<ResearchArtifactSummary>;
    getStatisticsCatalog(
        id: ResearchResultFingerprint,
        signal?: AbortSignal
    ): Promise<ResearchStatisticsCatalog>;
    getStatisticSeries(
        request: StatisticSeriesRequest,
        signal?: AbortSignal
    ): Promise<ResearchStatisticSeriesPage>;
}

export interface ResearchApiClient extends ResearchRunApiClient, ResearchArtifactApiClient {}

async function decode(response: Response): Promise<unknown> {
    try {
        return await response.json();
    } catch {
        throw new ResearchWebError(
            "CONTRACT_ERROR",
            "Server response is not valid JSON",
            response.status
        );
    }
}

async function request(url: string, init: RequestInit, signal?: AbortSignal): Promise<unknown> {
    let response: Response;
    try {
        response = await fetch(url, {
            headers: { Accept: "application/json" },
            ...init,
            ...(signal === undefined ? {} : { signal })
        });
    } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") throw error;
        throw new ResearchWebError("TRANSPORT_ERROR", "Research API is unavailable");
    }
    const body = await decode(response);
    if (!response.ok) {
        const runFailure = researchRunErrorSchema.safeParse(body);
        if (runFailure.success) {
            const error = runFailure.data.error;
            throw new ResearchWebError(
                error.code as `RESEARCH_${string}`,
                error.detail,
                response.status
            );
        }
        const admitted = researchErrorSchema.safeParse(body);
        if (!admitted.success)
            throw new ResearchWebError(
                "CONTRACT_ERROR",
                "API error response violates schema",
                response.status
            );
        throw new ResearchWebError(admitted.data.code, admitted.data.detail, response.status);
    }
    return body;
}

function admitted<T>(schema: { parse(value: unknown): T }, value: unknown): T {
    try {
        return schema.parse(value);
    } catch {
        throw new ResearchWebError("CONTRACT_ERROR", "API success response violates schema");
    }
}

const base = (id: ResearchResultFingerprint): string =>
    `/api/v2/research/artifacts/${encodeURIComponent(id)}`;

export class FetchResearchApiClient implements ResearchApiClient {
    async submitRun(
        specification: Readonly<Record<string, unknown>>,
        submissionKey: ResearchSubmissionKey,
        signal?: AbortSignal
    ) {
        const value = await request(
            "/api/v2/research/runs",
            {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "Idempotency-Key": submissionKey
                },
                body: JSON.stringify({ specification })
            },
            signal
        );
        return mapResearchRunSubmission(admitted(researchRunSubmissionSchema, value));
    }

    async getRun(id: ResearchRunId, signal?: AbortSignal) {
        return mapResearchRun(
            admitted(
                researchRunSchema,
                await request(
                    `/api/v2/research/runs/${encodeURIComponent(id)}`,
                    { method: "GET" },
                    signal
                )
            )
        );
    }

    async listRuns(limit: number, cursor?: string, signal?: AbortSignal) {
        const query = new URLSearchParams({ limit: limit.toString(10) });
        if (cursor !== undefined) query.set("cursor", cursor);
        return mapResearchRunPage(
            admitted(
                researchRunPageSchema,
                await request(
                    `/api/v2/research/runs?${query.toString()}`,
                    { method: "GET" },
                    signal
                )
            )
        );
    }

    async cancelRun(id: ResearchRunId, signal?: AbortSignal) {
        return mapResearchRun(
            admitted(
                researchRunSchema,
                await request(
                    `/api/v2/research/runs/${encodeURIComponent(id)}/cancellation`,
                    { method: "POST" },
                    signal
                )
            )
        );
    }

    async getArtifactSummary(id: ResearchResultFingerprint, signal?: AbortSignal) {
        return mapArtifactSummary(
            admitted(artifactSummarySchema, await request(base(id), { method: "GET" }, signal))
        );
    }

    async getStatisticsCatalog(id: ResearchResultFingerprint, signal?: AbortSignal) {
        return mapStatisticsCatalog(
            admitted(
                statisticsCatalogSchema,
                await request(`${base(id)}/statistics`, { method: "GET" }, signal)
            )
        );
    }

    async getStatisticSeries(requestValue: StatisticSeriesRequest, signal?: AbortSignal) {
        const query = new URLSearchParams({ limit: requestValue.limit.toString(10) });
        const optional = [
            ["from_ts_event_ns", requestValue.fromTsEventNs],
            ["to_ts_event_ns", requestValue.toTsEventNs],
            ["after_ts_event_ns", requestValue.afterTsEventNs]
        ] as const;
        for (const [name, value] of optional) {
            if (value !== undefined) query.set(name, nanosecondsToRequestText(value));
        }
        const url = `${base(requestValue.researchResultFingerprint)}/statistics/${encodeURIComponent(requestValue.statisticsFingerprint)}/series?${query.toString()}`;
        return mapStatisticSeriesPage(
            admitted(statisticSeriesPageSchema, await request(url, { method: "GET" }, signal))
        );
    }
}
