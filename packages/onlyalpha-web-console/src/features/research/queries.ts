import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import type { ResearchApiClient, ResearchArtifactApiClient } from "../../api/research/client";
import { researchQueryKeys } from "../../api/research/queryKeys";
import type {
    ResearchResultFingerprint,
    Sha256Fingerprint,
    StatisticsFingerprint
} from "../../domain/research/identity";
import type { ResearchPublishedSeries } from "../../domain/research/model";
import type { UnixNanoseconds } from "../../domain/research/time";

export const artifactOptions = (
    client: ResearchArtifactApiClient,
    result: ResearchResultFingerprint
) =>
    queryOptions({
        queryKey: researchQueryKeys.artifact(result),
        queryFn: ({ signal }) => client.getArtifactSummary(result, signal),
        staleTime: Infinity
    });

export const catalogOptions = (
    client: ResearchArtifactApiClient,
    result: ResearchResultFingerprint
) =>
    queryOptions({
        queryKey: researchQueryKeys.statistics(result),
        queryFn: ({ signal }) => client.getStatisticsCatalog(result, signal),
        staleTime: Infinity
    });

export const candidateCatalogOptions = (
    client: Pick<ResearchApiClient, "getCandidateCatalog">,
    result: ResearchResultFingerprint
) =>
    queryOptions({
        queryKey: researchQueryKeys.candidates(result),
        queryFn: ({ signal }) => client.getCandidateCatalog(result, signal),
        staleTime: Infinity,
        retry: false
    });

export const publishedSeriesOptions = (
    client: Pick<ResearchApiClient, "getPublishedSeriesCatalog">,
    result: ResearchResultFingerprint
) =>
    queryOptions({
        queryKey: researchQueryKeys.publishedSeries(result),
        queryFn: ({ signal }) => client.getPublishedSeriesCatalog(result, signal),
        staleTime: Infinity
    });

const scientificPage = {
    initialPageParam: null as UnixNanoseconds | null,
    getNextPageParam: (page: {
        readonly hasMore: boolean;
        readonly nextAfterTsEventNs: UnixNanoseconds | null;
    }) => (page.hasMore ? page.nextAfterTsEventNs : null),
    staleTime: Infinity
};

export const marketSeriesOptions = (
    client: Pick<ResearchApiClient, "getMarketSeries">,
    result: ResearchResultFingerprint,
    instrumentId: string,
    limit = 500,
    from?: UnixNanoseconds,
    to?: UnixNanoseconds
) =>
    infiniteQueryOptions({
        queryKey: researchQueryKeys.market(result, instrumentId, limit, from, to),
        queryFn: ({ pageParam, signal }) =>
            client.getMarketSeries(
                result,
                instrumentId,
                {
                    limit,
                    ...(from === undefined ? {} : { fromTsEventNs: from }),
                    ...(to === undefined ? {} : { toTsEventNs: to }),
                    ...(pageParam === null ? {} : { afterTsEventNs: pageParam })
                },
                signal
            ),
        ...scientificPage
    });

export const variableSeriesOptions = (
    client: Pick<ResearchApiClient, "getVariableSeries">,
    result: ResearchResultFingerprint,
    instrumentId: string,
    series: ResearchPublishedSeries,
    limit = 500,
    from?: UnixNanoseconds,
    to?: UnixNanoseconds
) =>
    infiniteQueryOptions({
        queryKey: researchQueryKeys.variable(
            result,
            series.candidateFingerprint,
            series.calculationFingerprint,
            series.nodeFingerprint,
            series.outputName,
            instrumentId,
            limit,
            from,
            to
        ),
        queryFn: ({ pageParam, signal }) =>
            client.getVariableSeries(
                {
                    researchResultFingerprint: result,
                    instrumentId,
                    ...(series.candidateFingerprint === null
                        ? {}
                        : { candidateFingerprint: series.candidateFingerprint }),
                    calculationFingerprint: series.calculationFingerprint,
                    nodeFingerprint: series.nodeFingerprint,
                    outputName: series.outputName,
                    limit,
                    ...(from === undefined ? {} : { fromTsEventNs: from }),
                    ...(to === undefined ? {} : { toTsEventNs: to }),
                    ...(pageParam === null ? {} : { afterTsEventNs: pageParam })
                },
                signal
            ),
        ...scientificPage
    });

export const signalSeriesOptions = (
    client: Pick<ResearchApiClient, "getSignalSeries">,
    result: ResearchResultFingerprint,
    instrumentId: string,
    candidate: Sha256Fingerprint,
    role: string,
    limit = 500,
    from?: UnixNanoseconds,
    to?: UnixNanoseconds
) =>
    infiniteQueryOptions({
        queryKey: researchQueryKeys.signal(result, candidate, role, instrumentId, limit, from, to),
        queryFn: ({ pageParam, signal }) =>
            client.getSignalSeries(
                {
                    researchResultFingerprint: result,
                    instrumentId,
                    candidateFingerprint: candidate,
                    role,
                    limit,
                    ...(from === undefined ? {} : { fromTsEventNs: from }),
                    ...(to === undefined ? {} : { toTsEventNs: to }),
                    ...(pageParam === null ? {} : { afterTsEventNs: pageParam })
                },
                signal
            ),
        ...scientificPage
    });

export const graphOptions = (
    client: Pick<ResearchApiClient, "getCandidateGraph">,
    result: ResearchResultFingerprint,
    candidate: Sha256Fingerprint
) =>
    queryOptions({
        queryKey: researchQueryKeys.graph(result, candidate),
        queryFn: ({ signal }) => client.getCandidateGraph(result, candidate, signal),
        staleTime: Infinity
    });

export const seriesOptions = (
    client: ResearchArtifactApiClient,
    result: ResearchResultFingerprint,
    statistics: StatisticsFingerprint,
    limit = 2,
    from?: UnixNanoseconds,
    to?: UnixNanoseconds
) =>
    infiniteQueryOptions({
        queryKey: researchQueryKeys.series(result, statistics, limit, from, to),
        queryFn: ({ pageParam, signal }) =>
            client.getStatisticSeries(
                {
                    researchResultFingerprint: result,
                    statisticsFingerprint: statistics,
                    limit,
                    ...(from === undefined ? {} : { fromTsEventNs: from }),
                    ...(to === undefined ? {} : { toTsEventNs: to }),
                    ...(pageParam === null ? {} : { afterTsEventNs: pageParam })
                },
                signal
            ),
        initialPageParam: null as UnixNanoseconds | null,
        getNextPageParam: (page) => (page.hasMore ? page.nextAfterTsEventNs : null),
        staleTime: Infinity
    });
