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
    runs: () => ["research", "runs"] as const,
    run: (runId: ResearchRunId) => ["research", "run", runId] as const,
    series: (
        result: ResearchResultFingerprint,
        statistics: StatisticsFingerprint,
        from?: UnixNanoseconds,
        to?: UnixNanoseconds
    ) => ["research", "series", result, statistics, text(from), text(to)] as const
};
