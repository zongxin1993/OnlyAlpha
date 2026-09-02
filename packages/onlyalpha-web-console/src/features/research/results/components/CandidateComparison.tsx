import { useQueries } from "@tanstack/react-query";
import { useResearchApi } from "../../../../app/providers";
import type { ResearchCandidate } from "../../../../domain/research/model";
import { parseUnixNanoseconds } from "../../../../domain/research/time";
import { ScientificEvidenceChart } from "../../../../visualization/scientific/echarts/ScientificEvidenceChart";
import { QueryError } from "../../../../shared/components/QueryState";
import {
    commonExactTimestamps,
    projectCandidateSurface
} from "../../../../visualization/projection/scientificProjection";
import { useResultWorkspace } from "../ResultWorkspaceContext";

export function CandidateComparison({
    candidates
}: {
    readonly candidates: readonly ResearchCandidate[];
}) {
    const { summary, statistics, selection, dispatch } = useResultWorkspace();
    const client = useResearchApi();
    const selectedCandidate = candidates.find(
        (candidate) => candidate.candidateFingerprint === selection.candidateFingerprint
    );
    const selectedDescriptor =
        statistics.statistics.find(
            (descriptor) => descriptor.statisticsFingerprint === selection.statisticsFingerprint
        ) ??
        statistics.statistics.find((descriptor) =>
            selectedCandidate?.statisticsFingerprints.includes(descriptor.statisticsFingerprint)
        );
    const comparisonChoices = statistics.statistics.filter((descriptor) =>
        selectedCandidate?.statisticsFingerprints.includes(descriptor.statisticsFingerprint)
    );
    const entries =
        selectedDescriptor === undefined
            ? []
            : candidates.flatMap((candidate) => {
                  const descriptor = statistics.statistics.find(
                      (item) =>
                          candidate.statisticsFingerprints.includes(item.statisticsFingerprint) &&
                          item.definition.method === selectedDescriptor.definition.method &&
                          item.target.outputName === selectedDescriptor.target.outputName
                  );
                  return descriptor === undefined ? [] : [{ candidate, descriptor }];
              });
    const queries = useQueries({
        queries: entries.map(({ descriptor }) => ({
            queryKey: [
                "research",
                "candidate-surface",
                summary.researchResultFingerprint,
                descriptor.statisticsFingerprint
            ],
            queryFn: ({ signal }: { signal: AbortSignal }) =>
                client.getStatisticSeries(
                    {
                        researchResultFingerprint: summary.researchResultFingerprint,
                        statisticsFingerprint: descriptor.statisticsFingerprint,
                        limit: 5000
                    },
                    signal
                ),
            staleTime: Infinity
        }))
    });
    const evidence = new Map(
        entries.map(({ candidate }, index) => [
            candidate.candidateFingerprint,
            queries[index]?.data?.points ?? []
        ])
    );
    const timestamps = commonExactTimestamps(
        entries.map((entry) => entry.candidate),
        evidence
    );
    const selectedTimestamp =
        selection.exactTsEventNs === null
            ? timestamps.at(-1)
            : timestamps.find((timestamp) => timestamp.toString() === selection.exactTsEventNs);
    if (selectedDescriptor === undefined || entries.length !== candidates.length)
        return (
            <p className="warning">
                A common authoritative Statistics selector is unavailable for every Candidate;
                comparison remains table-only.
            </p>
        );
    if (queries.some((query) => query.isPending))
        return <p role="status">Loading bounded Candidate Statistics evidence…</p>;
    const failed = queries.find((query) => query.isError);
    if (failed?.error !== undefined)
        return <QueryError error={failed.error} retry={() => void failed.refetch()} />;
    if (selectedTimestamp === undefined)
        return <p>No common exact Statistics timestamp exists across Candidates.</p>;
    const projected = projectCandidateSurface(
        entries.map((entry) => entry.candidate),
        evidence,
        parseUnixNanoseconds(selectedTimestamp.toString())
    );
    if (!projected.ok)
        return <p className="warning">CANDIDATE_PROJECTION_ERROR: {projected.detail}</p>;
    return (
        <section aria-labelledby="candidate-comparison-heading">
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Exact Statistics time slice</p>
                    <h3 id="candidate-comparison-heading">Candidate comparison</h3>
                </div>
                <div>
                    <label className="compact-selector">
                        Comparison Statistics
                        <select
                            value={selectedDescriptor.statisticsFingerprint}
                            onChange={(event) => {
                                dispatch({ type: "STATISTICS", value: event.target.value });
                            }}
                        >
                            {comparisonChoices.map((descriptor) => (
                                <option
                                    key={descriptor.statisticsFingerprint}
                                    value={descriptor.statisticsFingerprint}
                                >
                                    {descriptor.definition.method} · {descriptor.target.outputName}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="compact-selector">
                        Exact ts_event_ns
                        <select
                            value={selectedTimestamp.toString()}
                            onChange={(event) => {
                                dispatch({ type: "EXACT_TIME", value: event.target.value });
                            }}
                        >
                            {timestamps.map((timestamp) => (
                                <option key={timestamp.toString()} value={timestamp.toString()}>
                                    {timestamp.toString()}
                                </option>
                            ))}
                        </select>
                    </label>
                </div>
            </div>
            <p className="muted">
                {selectedDescriptor.definition.method} at exact timestamp{" "}
                {selectedTimestamp.toString()}. No mean, median, rolling value, or browser score is
                calculated.
            </p>
            {projected.surface.mode === "TABLE_ONLY" ? (
                <p>
                    Non-numeric or zero-dimensional assignments are shown in the exact Candidate
                    table only.
                </p>
            ) : (
                <ScientificEvidenceChart
                    evidence={{ kind: "CANDIDATE_SURFACE", surface: projected.surface }}
                />
            )}
            {queries.some((query) => query.data?.hasMore) ? (
                <p className="warning">
                    Comparison uses the visible bounded evidence window; more exact rows are
                    available through Statistics pagination.
                </p>
            ) : null}
        </section>
    );
}
