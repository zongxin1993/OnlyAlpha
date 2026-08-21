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
    market: (result: ResearchResultFingerprint, instrumentId: string) =>
        ["research", "market", result, instrumentId] as const,
    variable: (
        result: ResearchResultFingerprint,
        candidate: string | null,
        calculation: string,
        node: string,
        output: string,
        instrumentId: string
    ) =>
        [
            "research",
            "variable",
            result,
            candidate,
            calculation,
            node,
            output,
            instrumentId
        ] as const,
    signal: (
        result: ResearchResultFingerprint,
        candidate: string,
        role: string,
        instrumentId: string
    ) => ["research", "signal", result, candidate, role, instrumentId] as const,
    graph: (result: ResearchResultFingerprint, candidate: string) =>
        ["research", "graph", result, candidate] as const,
    runs: () => ["research", "runs"] as const,
    run: (runId: ResearchRunId) => ["research", "run", runId] as const,
    series: (
        result: ResearchResultFingerprint,
        statistics: StatisticsFingerprint,
        from?: UnixNanoseconds,
        to?: UnixNanoseconds
    ) => ["research", "series", result, statistics, text(from), text(to)] as const
};
