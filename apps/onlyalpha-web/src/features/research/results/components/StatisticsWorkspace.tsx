import { useInfiniteQuery } from "@tanstack/react-query";
import { useResearchApi } from "../../../../app/providers";
import { formatUtcNanoseconds } from "../../../../domain/research/time";
import { QueryError } from "../../../../shared/components/QueryState";
import { ScientificEvidenceChart } from "../../../../visualization/scientific/echarts/ScientificEvidenceChart";
import { projectStatisticsEvidence } from "../../../../visualization/projection/scientificProjection";
import { seriesOptions } from "../../queries";
import { mergeSeriesPages } from "../../series/pagination";
import { useResultWorkspace } from "../ResultWorkspaceContext";
import { admitPresentation } from "../model/presentationAdmission";

export function StatisticsWorkspace() {
    const { summary, candidates, statistics, selection, dispatch } = useResultWorkspace();
    const candidate = candidates?.candidates.find(
        (item) => item.candidateFingerprint === selection.candidateFingerprint
    );
    const compatible = statistics.statistics.filter(
        (descriptor) =>
            candidate === undefined ||
            candidate.statisticsFingerprints.includes(descriptor.statisticsFingerprint)
    );
    const descriptor =
        compatible.find((item) => item.statisticsFingerprint === selection.statisticsFingerprint) ??
        compatible[0];
    if (descriptor === undefined)
        return <p>No Statistics evidence is a member of this Candidate.</p>;
    return (
        <section aria-labelledby="statistics-workspace-heading">
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Existing Statistics authority</p>
                    <h2 id="statistics-workspace-heading">Statistics</h2>
                </div>
            </div>
            <label className="compact-selector">
                Statistics evidence
                <select
                    value={descriptor.statisticsFingerprint}
                    onChange={(event) => {
                        dispatch({ type: "STATISTICS", value: event.target.value });
                    }}
                >
                    {compatible.map((item) => (
                        <option key={item.statisticsFingerprint} value={item.statisticsFingerprint}>
                            {item.definition.method} · {item.feature.outputName} →{" "}
                            {item.target.outputName}
                        </option>
                    ))}
                </select>
            </label>
            <StatisticsEvidence
                result={summary.researchResultFingerprint}
                descriptor={descriptor}
            />
        </section>
    );
}

function StatisticsEvidence({
    result,
    descriptor
}: {
    readonly result: ReturnType<typeof useResultWorkspace>["summary"]["researchResultFingerprint"];
    readonly descriptor: ReturnType<typeof useResultWorkspace>["statistics"]["statistics"][number];
}) {
    const client = useResearchApi();
    const query = useInfiniteQuery(
        seriesOptions(client, result, descriptor.statisticsFingerprint, 500)
    );
    if (query.isPending) return <p role="status">Loading bounded exact Statistics evidence…</p>;
    if (query.isError) return <QueryError error={query.error} retry={() => void query.refetch()} />;
    const admission = admitPresentation(() => mergeSeriesPages(query.data.pages));
    if (!admission.ok)
        return (
            <p className="error" role="alert">
                CONTRACT_ERROR: paginated Statistics evidence is inconsistent
            </p>
        );
    const points = admission.value;
    const projected = projectStatisticsEvidence(points);
    return (
        <>
            <details className="identity-inspector">
                <summary>Inspect Statistics definition and identity</summary>
                <dl className="facts">
                    <dt>Statistics fingerprint</dt>
                    <dd>{descriptor.statisticsFingerprint}</dd>
                    <dt>Method</dt>
                    <dd>{descriptor.definition.method}</dd>
                    <dt>Feature / Target</dt>
                    <dd>
                        {descriptor.feature.outputName} → {descriptor.target.outputName}
                    </dd>
                    <dt>Admission</dt>
                    <dd>
                        minimum {descriptor.definition.minimumObservations};{" "}
                        {descriptor.definition.pairingPolicy};{" "}
                        {descriptor.definition.universePolicy}
                    </dd>
                </dl>
            </details>
            {projected.ok ? (
                <ScientificEvidenceChart
                    evidence={{
                        kind: "TIME_SERIES",
                        name: descriptor.definition.method,
                        points: projected.points
                    }}
                />
            ) : (
                <p className="warning">STATISTICS_PROJECTION_ERROR: {projected.detail}</p>
            )}
            <div className="table-scroll">
                <table>
                    <thead>
                        <tr>
                            <th>UTC time</th>
                            <th>Raw ts_event_ns</th>
                            <th>Exact value</th>
                            <th>Samples</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {points.map((point) => (
                            <tr key={point.tsEventNs.toString()}>
                                <td>{formatUtcNanoseconds(point.tsEventNs)}</td>
                                <td>
                                    <code>{point.tsEventNs.toString()}</code>
                                </td>
                                <td>{point.statisticValue ?? "NULL"}</td>
                                <td>{point.sampleCount}</td>
                                <td>{point.status}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {query.hasNextPage ? (
                <button
                    type="button"
                    onClick={() => void query.fetchNextPage()}
                    disabled={query.isFetchingNextPage}
                >
                    {query.isFetchingNextPage ? "Loading…" : "Load next exact page"}
                </button>
            ) : null}
        </>
    );
}
