import type {
    ResearchResultFingerprint,
    ResearchRunId,
    ResearchSubmissionKey,
    StatisticsFingerprint
} from "../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchCandidateCatalog,
    ResearchCandidateGraph,
    ResearchPublishedSeriesCatalog,
    ResearchRun,
    ResearchRunPage,
    ResearchRunSubmission,
    ResearchScientificSeriesPage,
    ResearchStatisticSeriesPage,
    ResearchStatisticsCatalog
} from "../../domain/research/model";
import type { UnixNanoseconds } from "../../domain/research/time";
import { nanosecondsToRequestText } from "../../domain/research/time";
import { ResearchWebError } from "./errors";
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
import {
    artifactSummarySchema,
    researchCalculationCatalogSchema,
    researchCandidateCatalogSchema,
    researchCandidateGraphSchema,
    researchDatasetFieldCatalogSchema,
    researchDefinitionErrorSchema,
    researchDefinitionResolutionSchema,
    researchErrorSchema,
    researchRunErrorSchema,
    researchRunPageSchema,
    researchRunSchema,
    researchRunSubmissionSchema,
    researchStatisticsCapabilityCatalogSchema,
    researchPublishedSeriesCatalogSchema,
    researchScientificSeriesPageSchema,
    researchUniverseCatalogSchema,
    statisticSeriesPageSchema,
    statisticsCatalogSchema
} from "./schemas";
import type {
    ResearchCalculationCatalogTransport,
    ResearchDatasetFieldCatalogTransport,
    ResearchDefinitionResolutionTransport,
    ResearchDefinitionTransport,
    ResearchStatisticsCapabilityCatalogTransport,
    ResearchUniverseCatalogTransport
} from "./schemas";

export interface StatisticSeriesRequest {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly statisticsFingerprint: StatisticsFingerprint;
    readonly fromTsEventNs?: UnixNanoseconds;
    readonly toTsEventNs?: UnixNanoseconds;
    readonly afterTsEventNs?: UnixNanoseconds;
    readonly limit: number;
}

export interface ScientificSeriesRequest {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly instrumentId: string;
    readonly candidateFingerprint?: string;
    readonly calculationFingerprint?: string;
    readonly nodeFingerprint?: string;
    readonly outputName?: string;
    readonly role?: string;
    readonly fromTsEventNs?: UnixNanoseconds;
    readonly toTsEventNs?: UnixNanoseconds;
    readonly afterTsEventNs?: UnixNanoseconds;
    readonly limit?: number;
}

export type ScientificPageRequest = Pick<
    ScientificSeriesRequest,
    "fromTsEventNs" | "toTsEventNs" | "afterTsEventNs" | "limit"
>;

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

export interface ResearchScientificArtifactApiClient {
    getCandidateCatalog(
        id: ResearchResultFingerprint,
        signal?: AbortSignal
    ): Promise<ResearchCandidateCatalog>;
    getPublishedSeriesCatalog(
        id: ResearchResultFingerprint,
        signal?: AbortSignal
    ): Promise<ResearchPublishedSeriesCatalog>;
    getMarketSeries(
        id: ResearchResultFingerprint,
        instrumentId: string,
        page?: ScientificPageRequest,
        signal?: AbortSignal
    ): Promise<ResearchScientificSeriesPage>;
    getCandidateGraph(
        id: ResearchResultFingerprint,
        candidateFingerprint: string,
        signal?: AbortSignal
    ): Promise<ResearchCandidateGraph>;
    getVariableSeries(
        request: ScientificSeriesRequest,
        signal?: AbortSignal
    ): Promise<ResearchScientificSeriesPage>;
    getSignalSeries(
        request: ScientificSeriesRequest,
        signal?: AbortSignal
    ): Promise<ResearchScientificSeriesPage>;
}

export interface ResearchDiscoveryApiClient {
    getCalculationCatalog(signal?: AbortSignal): Promise<ResearchCalculationCatalogTransport>;
    getUniverseCatalog(signal?: AbortSignal): Promise<ResearchUniverseCatalogTransport>;
    getStatisticsCapabilityCatalog(
        signal?: AbortSignal
    ): Promise<ResearchStatisticsCapabilityCatalogTransport>;
    getDatasetFieldCatalog(signal?: AbortSignal): Promise<ResearchDatasetFieldCatalogTransport>;
}

export interface ResearchDefinitionApiClient {
    resolveDefinition(
        definition: ResearchDefinitionTransport,
        signal?: AbortSignal
    ): Promise<ResearchDefinitionResolutionTransport>;
}

export interface ResearchApiClient
    extends
        ResearchRunApiClient,
        ResearchArtifactApiClient,
        ResearchScientificArtifactApiClient,
        ResearchDiscoveryApiClient,
        ResearchDefinitionApiClient {}

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
        const definitionFailure = researchDefinitionErrorSchema.safeParse(body);
        if (definitionFailure.success) {
            const error = definitionFailure.data.error;
            throw new ResearchWebError(
                error.code as `RESEARCH_${string}`,
                error.detail,
                response.status,
                error.phase,
                error.path
            );
        }
        const runFailure = researchRunErrorSchema.safeParse(body);
        if (runFailure.success) {
            const error = runFailure.data.error;
            throw new ResearchWebError(
                error.code as `RESEARCH_${string}`,
                error.detail,
                response.status,
                error.phase
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
    async getCalculationCatalog(signal?: AbortSignal) {
        return admitted(
            researchCalculationCatalogSchema,
            await request("/api/v2/research/catalog/calculations", { method: "GET" }, signal)
        );
    }

    async getUniverseCatalog(signal?: AbortSignal) {
        return admitted(
            researchUniverseCatalogSchema,
            await request("/api/v2/research/catalog/universes", { method: "GET" }, signal)
        );
    }

    async getStatisticsCapabilityCatalog(signal?: AbortSignal) {
        return admitted(
            researchStatisticsCapabilityCatalogSchema,
            await request("/api/v2/research/catalog/statistics", { method: "GET" }, signal)
        );
    }

    async getDatasetFieldCatalog(signal?: AbortSignal) {
        return admitted(
            researchDatasetFieldCatalogSchema,
            await request("/api/v2/research/catalog/dataset-fields", { method: "GET" }, signal)
        );
    }

    async resolveDefinition(definition: ResearchDefinitionTransport, signal?: AbortSignal) {
        return admitted(
            researchDefinitionResolutionSchema,
            await request(
                "/api/v2/research/definitions/resolve",
                {
                    method: "POST",
                    headers: {
                        Accept: "application/json",
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(definition)
                },
                signal
            )
        );
    }

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

    async getCandidateCatalog(id: ResearchResultFingerprint, signal?: AbortSignal) {
        return mapCandidateCatalog(
            admitted(
                researchCandidateCatalogSchema,
                await request(`${base(id)}/candidates`, { method: "GET" }, signal)
            )
        );
    }

    async getPublishedSeriesCatalog(id: ResearchResultFingerprint, signal?: AbortSignal) {
        return mapPublishedSeriesCatalog(
            admitted(
                researchPublishedSeriesCatalogSchema,
                await request(`${base(id)}/variables`, { method: "GET" }, signal)
            )
        );
    }

    async getMarketSeries(
        id: ResearchResultFingerprint,
        instrumentId: string,
        page: ScientificPageRequest = {},
        signal?: AbortSignal
    ) {
        const query = new URLSearchParams({ instrument_id: instrumentId });
        appendScientificPageQuery(query, page);
        return mapScientificSeriesPage(
            admitted(
                researchScientificSeriesPageSchema,
                await request(
                    `${base(id)}/market/series?${query.toString()}`,
                    { method: "GET" },
                    signal
                )
            )
        );
    }

    async getCandidateGraph(
        id: ResearchResultFingerprint,
        candidateFingerprint: string,
        signal?: AbortSignal
    ) {
        return mapCandidateGraph(
            admitted(
                researchCandidateGraphSchema,
                await request(
                    `${base(id)}/candidates/${encodeURIComponent(candidateFingerprint)}/graph`,
                    { method: "GET" },
                    signal
                )
            )
        );
    }

    async getVariableSeries(requestValue: ScientificSeriesRequest, signal?: AbortSignal) {
        if (
            requestValue.calculationFingerprint === undefined ||
            requestValue.nodeFingerprint === undefined ||
            requestValue.outputName === undefined
        )
            throw new ResearchWebError("CONTRACT_ERROR", "Exact Variable selector is required");
        const query = new URLSearchParams({ instrument_id: requestValue.instrumentId });
        if (requestValue.candidateFingerprint !== undefined)
            query.set("candidate_fingerprint", requestValue.candidateFingerprint);
        appendScientificPageQuery(query, requestValue);
        const path = `${base(requestValue.researchResultFingerprint)}/variables/${encodeURIComponent(requestValue.calculationFingerprint)}/${encodeURIComponent(requestValue.nodeFingerprint)}/${encodeURIComponent(requestValue.outputName)}/series?${query.toString()}`;
        return mapScientificSeriesPage(
            admitted(
                researchScientificSeriesPageSchema,
                await request(path, { method: "GET" }, signal)
            )
        );
    }

    async getSignalSeries(requestValue: ScientificSeriesRequest, signal?: AbortSignal) {
        if (requestValue.candidateFingerprint === undefined || requestValue.role === undefined)
            throw new ResearchWebError("CONTRACT_ERROR", "Exact Signal selector is required");
        const query = new URLSearchParams({ instrument_id: requestValue.instrumentId });
        appendScientificPageQuery(query, requestValue);
        const path = `${base(requestValue.researchResultFingerprint)}/signals/${encodeURIComponent(requestValue.candidateFingerprint)}/${encodeURIComponent(requestValue.role)}/series?${query.toString()}`;
        return mapScientificSeriesPage(
            admitted(
                researchScientificSeriesPageSchema,
                await request(path, { method: "GET" }, signal)
            )
        );
    }
}

function appendScientificPageQuery(query: URLSearchParams, value: ScientificPageRequest): void {
    const optional = [
        ["from_ts_event_ns", value.fromTsEventNs],
        ["to_ts_event_ns", value.toTsEventNs],
        ["after_ts_event_ns", value.afterTsEventNs]
    ] as const;
    for (const [name, exact] of optional)
        if (exact !== undefined) query.set(name, nanosecondsToRequestText(exact));
    if (value.limit !== undefined) query.set("limit", value.limit.toString(10));
}
