import type { ResearchPublishedSeries } from "../../../../domain/research/model";

export function publishedSeriesKey(value: ResearchPublishedSeries): string {
    return [
        value.candidateFingerprint ?? "GLOBAL",
        value.calculationFingerprint,
        value.nodeFingerprint,
        value.outputName
    ].join(":");
}
