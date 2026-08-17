import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { useResearchApi } from "../../../app/providers";
import { projectResearchSeries } from "../../../charts/researchSeriesProjection";
import { ResearchSeriesChart } from "../../../charts/lightweight/ResearchSeriesChart";
import {
    parseResearchResultFingerprint,
    parseStatisticsFingerprint
} from "../../../domain/research/identity";
import { formatUtcNanoseconds } from "../../../domain/research/time";
import { QueryError } from "../../../shared/components/QueryState";
import { catalogOptions, seriesOptions } from "../queries";
import { mergeSeriesPages } from "../series/pagination";

export function StatisticsDetailPage() {
    const params = useParams();
    let result: ReturnType<typeof parseResearchResultFingerprint> | null = null;
    let statistics: ReturnType<typeof parseStatisticsFingerprint> | null = null;
    try {
        result = parseResearchResultFingerprint(params.researchResultFingerprint ?? "");
        statistics = parseStatisticsFingerprint(params.statisticsFingerprint ?? "");
    } catch {
        // Admission is rendered below, before any API consumer is mounted.
    }
    return result === null || statistics === null ? (
        <main className="page">
            <div className="error" role="alert">
                INVALID_QUERY: route identity is invalid
            </div>
        </main>
    ) : (
        <ValidStatisticsDetailPage result={result} statistics={statistics} />
    );
}

function ValidStatisticsDetailPage({
    result,
    statistics
}: {
    readonly result: ReturnType<typeof parseResearchResultFingerprint>;
    readonly statistics: ReturnType<typeof parseStatisticsFingerprint>;
}) {
    const client = useResearchApi();
    const catalog = useQuery(catalogOptions(client, result));
    const series = useInfiniteQuery(seriesOptions(client, result, statistics));
    if (catalog.isPending || series.isPending)
        return (
            <main className="page">
                <p role="status">Loading exact Statistics series…</p>
            </main>
        );
    if (catalog.isError)
        return (
            <main className="page">
                <QueryError error={catalog.error} retry={() => void catalog.refetch()} />
            </main>
        );
    if (series.isError)
        return (
            <main className="page">
                <QueryError error={series.error} retry={() => void series.refetch()} />
            </main>
        );
    const descriptor = catalog.data.statistics.find(
        (item) => item.statisticsFingerprint === statistics
    );
    if (descriptor === undefined)
        return (
            <main className="page">
                <div className="error" role="alert">
                    STATISTICS_NOT_FOUND: exact Statistics is not a member of this Artifact
                </div>
            </main>
        );

    let points;
    try {
        points = mergeSeriesPages(series.data.pages);
    } catch {
        return (
            <main className="page">
                <div className="error" role="alert">
                    CONTRACT_ERROR: paginated series is inconsistent
                </div>
            </main>
        );
    }
    const chart = projectResearchSeries(points);

    return (
        <main className="page">
            <nav>
                <Link to={`/research/${result}`}>← Artifact overview</Link>
            </nav>
            <p className="eyebrow">Exact Statistics member</p>
            <h1>{descriptor.definition.method}</h1>
            <dl className="facts">
                <dt>Statistics fingerprint</dt>
                <dd>{descriptor.statisticsFingerprint}</dd>
                <dt>Feature</dt>
                <dd>
                    {descriptor.feature.calculationFingerprint} /{" "}
                    {descriptor.feature.nodeFingerprint} / {descriptor.feature.outputName}
                </dd>
                <dt>Target</dt>
                <dd>
                    {descriptor.target.calculationFingerprint} / {descriptor.target.nodeFingerprint}{" "}
                    / {descriptor.target.outputName}
                </dd>
                <dt>Numeric</dt>
                <dd>
                    {descriptor.definition.numeric.representation}; precision{" "}
                    {descriptor.definition.numeric.precision}; quantum{" "}
                    {descriptor.definition.numeric.outputQuantum};{" "}
                    {descriptor.definition.numeric.rounding}
                </dd>
                <dt>Definition</dt>
                <dd>
                    minimum {descriptor.definition.minimumObservations};{" "}
                    {descriptor.definition.pairingPolicy}; {descriptor.definition.universePolicy};
                    ties {descriptor.definition.rankTieMethod}; {descriptor.definition.weighting}
                </dd>
                <dt>Loaded / total rows</dt>
                <dd>
                    {points.length} / {descriptor.rowCount}
                </dd>
            </dl>
            <section>
                <h2>Visualization projection</h2>
                {chart.ok ? (
                    <ResearchSeriesChart points={chart.points} />
                ) : (
                    <div className="warning" role="status">
                        <strong>{chart.code}</strong>: {chart.detail}. Exact table remains
                        available.
                    </div>
                )}
            </section>
            <section>
                <div className="section-heading">
                    <h2>Exact series table</h2>
                    <span>
                        {points.length} loaded ·{" "}
                        {series.hasNextPage ? "more available" : "complete"}
                    </span>
                </div>
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
                {series.hasNextPage ? (
                    <button
                        type="button"
                        disabled={series.isFetchingNextPage}
                        onClick={() => void series.fetchNextPage()}
                    >
                        {series.isFetchingNextPage ? "Loading…" : "Load more"}
                    </button>
                ) : null}
            </section>
        </main>
    );
}
