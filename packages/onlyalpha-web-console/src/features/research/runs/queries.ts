import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import type { ResearchApiClient } from "../../../api/research/client";
import { researchQueryKeys } from "../../../api/research/queryKeys";
import type { ResearchRunId } from "../../../domain/research/identity";

const terminal = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

export const runOptions = (client: ResearchApiClient, runId: ResearchRunId) =>
    queryOptions({
        queryKey: researchQueryKeys.run(runId),
        queryFn: ({ signal }) => client.getRun(runId, signal),
        refetchInterval: (query) => {
            const state = query.state.data?.state;
            return state === undefined || terminal.has(state) ? false : 2_000;
        }
    });

export const runsOptions = (client: ResearchApiClient) =>
    infiniteQueryOptions({
        queryKey: researchQueryKeys.runs(),
        queryFn: ({ pageParam, signal }) => client.listRuns(50, pageParam ?? undefined, signal),
        initialPageParam: null as string | null,
        getNextPageParam: (page) => (page.hasMore ? page.nextCursor : null)
    });

export const shouldPollRunState = (state: string): boolean => !terminal.has(state);
