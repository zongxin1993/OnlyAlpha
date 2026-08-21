import type {
    ResearchResultFingerprint,
    ResearchRunId,
    StatisticsFingerprint
} from "../../domain/research/identity";
import type { UnixNanoseconds } from "../../domain/research/time";
import { nanosecondsToRequestText } from "../../domain/research/time";

const text = (value?: UnixNanoseconds): string | null =>
    value === undefined ? null : nanosecondsToRequestText(value);

export const researchQueryKeys = {
    artifact: (result: ResearchResultFingerprint) => ["research", "artifact", result] as const,
    statistics: (result: ResearchResultFingerprint) => ["research", "statistics", result] as const,
    candidates: (result: ResearchResultFingerprint) => ["research", "candidates", result] as const,
    publishedSeries: (result: ResearchResultFingerprint) =>
        ["research", "published-series", result] as const,
    market: (
        result: ResearchResultFingerprint,
        instrumentId: string,
        limit: number,
        from?: UnixNanoseconds,
        to?: UnixNanoseconds
    ) => ["research", "market", result, instrumentId, limit, text(from), text(to)] as const,
    variable: (
        result: ResearchResultFingerprint,
        candidate: string | null,
        calculation: string,
        node: string,
        output: string,
        instrumentId: string,
        limit: number,
        from?: UnixNanoseconds,
        to?: UnixNanoseconds
    ) =>
        [
            "research",
            "variable",
            result,
            candidate,
            calculation,
            node,
            output,
            instrumentId,
            limit,
            text(from),
            text(to)
        ] as const,
    signal: (
        result: ResearchResultFingerprint,
        candidate: string,
        role: string,
        instrumentId: string,
        limit: number,
        from?: UnixNanoseconds,
        to?: UnixNanoseconds
    ) =>
        [
            "research",
            "signal",
            result,
            candidate,
            role,
            instrumentId,
            limit,
            text(from),
            text(to)
        ] as const,
    graph: (result: ResearchResultFingerprint, candidate: string) =>
        ["research", "graph", result, candidate] as const,
    runs: () => ["research", "runs"] as const,
    run: (runId: ResearchRunId) => ["research", "run", runId] as const,
    series: (
        result: ResearchResultFingerprint,
        statistics: StatisticsFingerprint,
        limit: number,
        from?: UnixNanoseconds,
        to?: UnixNanoseconds
    ) => ["research", "series", result, statistics, limit, text(from), text(to)] as const
};
