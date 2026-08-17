import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import type { ResearchApiClient } from "../../api/research/client";
import { researchQueryKeys } from "../../api/research/queryKeys";
import type {
    ResearchResultFingerprint,
    StatisticsFingerprint
} from "../../domain/research/identity";
import type { UnixNanoseconds } from "../../domain/research/time";

export const artifactOptions = (client: ResearchApiClient, result: ResearchResultFingerprint) =>
    queryOptions({
        queryKey: researchQueryKeys.artifact(result),
        queryFn: ({ signal }) => client.getArtifactSummary(result, signal),
        staleTime: Infinity
    });

export const catalogOptions = (client: ResearchApiClient, result: ResearchResultFingerprint) =>
    queryOptions({
        queryKey: researchQueryKeys.statistics(result),
        queryFn: ({ signal }) => client.getStatisticsCatalog(result, signal),
        staleTime: Infinity
    });

export const seriesOptions = (
    client: ResearchApiClient,
    result: ResearchResultFingerprint,
    statistics: StatisticsFingerprint,
    limit = 2
) =>
    infiniteQueryOptions({
        queryKey: researchQueryKeys.series(result, statistics),
        queryFn: ({ pageParam, signal }) =>
            client.getStatisticSeries(
                {
                    researchResultFingerprint: result,
                    statisticsFingerprint: statistics,
                    limit,
                    ...(pageParam === null ? {} : { afterTsEventNs: pageParam })
                },
                signal
            ),
        initialPageParam: null as UnixNanoseconds | null,
        getNextPageParam: (page) => (page.hasMore ? page.nextAfterTsEventNs : null),
        staleTime: Infinity
    });
