import { useInfiniteQuery } from "@tanstack/react-query";
import { useResearchApi } from "../../../../app/providers";
import type {
    ResearchMarketPoint,
    ResearchSignalPoint,
    ResearchVariablePoint
} from "../../../../domain/research/model";
import { formatUtcNanoseconds } from "../../../../domain/research/time";
import { QueryError } from "../../../../shared/components/QueryState";
import {
    marketSeriesOptions,
    seriesOptions,
    signalSeriesOptions,
    variableSeriesOptions
} from "../../queries";
import { mergeScientificSeriesPages, mergeSeriesPages } from "../../series/pagination";
import { useResultWorkspace } from "../ResultWorkspaceContext";
import { publishedSeriesKey } from "../model/selectors";
import { admitPresentation } from "../model/presentationAdmission";

export function ExactDataWorkspace() {
    const { summary, candidates, published, statistics, selection, scientificUnavailable } =
        useResultWorkspace();
    if (scientificUnavailable)
        return (
            <p className="warning">
                Scientific exact data is unavailable for this Artifact profile. Statistics exact
                evidence remains available from its dedicated route.
            </p>
        );
    const candidate = candidates?.candidates.find(
        (item) => item.candidateFingerprint === selection.candidateFingerprint
    );
    const series = published?.series.find(
        (item) => publishedSeriesKey(item) === selection.seriesKey
    );
    const statistic = statistics.statistics.find(
        (item) => item.statisticsFingerprint === selection.statisticsFingerprint
    );
    if (candidate === undefined || selection.instrumentId === null)
        return <p role="status">Loading exact evidence selectors…</p>;
    const instrumentId = selection.instrumentId;
    return (
        <section aria-labelledby="exact-data-heading">
            <p className="eyebrow">Query API evidence only</p>
            <h2 id="exact-data-heading">Exact Data Inspector</h2>
            <p className="muted">
                Values below retain exact nanoseconds, Decimal strings, nullable Boolean, status,
                sample count, and selectors. No browser Parquet access is used.
            </p>
            <MarketExactTable instrumentId={instrumentId} />
            {series === undefined ? (
                <p>No Published Variable is selected.</p>
            ) : (
                <VariableExactTable instrumentId={instrumentId} series={series} />
            )}
            {candidate.signalRoles.map((role) => (
                <SignalExactTable
                    key={role}
                    instrumentId={instrumentId}
                    candidate={candidate.candidateFingerprint}
                    role={role}
                />
            ))}
            {statistic === undefined ? (
                <p>No Statistics evidence is selected.</p>
            ) : (
                <StatisticsExactTable descriptor={statistic} />
            )}
            <details className="identity-inspector">
                <summary>Inspect exact selectors</summary>
                <code>{summary.researchResultFingerprint}</code>
                <code>{candidate.candidateFingerprint}</code>
                <code>{selection.instrumentId}</code>
                {series === undefined ? null : <code>{publishedSeriesKey(series)}</code>}
                {statistic === undefined ? null : <code>{statistic.statisticsFingerprint}</code>}
            </details>
        </section>
    );
}

function MarketExactTable({ instrumentId }: { readonly instrumentId: string }) {
    const { summary } = useResultWorkspace();
    const query = useInfiniteQuery(
        marketSeriesOptions(useResearchApi(), summary.researchResultFingerprint, instrumentId, 100)
    );
    if (query.isPending) return <p role="status">Loading exact Market rows…</p>;
    if (query.isError) return <QueryError error={query.error} retry={() => void query.refetch()} />;
    const admission = admitPresentation(() =>
        mergeScientificSeriesPages(query.data.pages).filter(
            (point): point is ResearchMarketPoint => point.kind === "MARKET"
        )
    );
    if (!admission.ok) return <ContractFailure />;
    return (
        <ExactSection
            title="Market"
            query={query}
            rows={admission.value.map((point) => [
                formatUtcNanoseconds(point.tsEventNs),
                point.tsEventNs.toString(),
                point.instrumentId,
                point.open,
                point.high,
                point.low,
                point.close,
                point.volume
            ])}
            headings={[
                "UTC",
                "ts_event_ns",
                "Instrument",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume"
            ]}
        />
    );
}

function VariableExactTable({
    instrumentId,
    series
}: {
    readonly instrumentId: string;
    readonly series: NonNullable<
        ReturnType<typeof useResultWorkspace>["published"]
    >["series"][number];
}) {
    const { summary } = useResultWorkspace();
    const query = useInfiniteQuery(
        variableSeriesOptions(
            useResearchApi(),
            summary.researchResultFingerprint,
            instrumentId,
            series,
            100
        )
    );
    if (query.isPending) return <p role="status">Loading exact Variable rows…</p>;
    if (query.isError) return <QueryError error={query.error} retry={() => void query.refetch()} />;
    const admission = admitPresentation(() =>
        mergeScientificSeriesPages(query.data.pages).filter(
            (point): point is ResearchVariablePoint => point.kind === "VARIABLE"
        )
    );
    if (!admission.ok) return <ContractFailure />;
    return (
        <ExactSection
            title={`Variable · ${series.outputName}`}
            query={query}
            rows={admission.value.map((point) => [
                point.tsEventNs.toString(),
                point.instrumentId,
                point.valueKind,
                exactVariableValue(point)
            ])}
            headings={["ts_event_ns", "Instrument", "Kind", "Exact value"]}
        />
    );
}

function SignalExactTable({
    instrumentId,
    candidate,
    role
}: {
    readonly instrumentId: string;
    readonly candidate: NonNullable<
        ReturnType<typeof useResultWorkspace>["candidates"]
    >["candidates"][number]["candidateFingerprint"];
    readonly role: string;
}) {
    const { summary } = useResultWorkspace();
    const query = useInfiniteQuery(
        signalSeriesOptions(
            useResearchApi(),
            summary.researchResultFingerprint,
            instrumentId,
            candidate,
            role,
            100
        )
    );
    if (query.isPending) return <p role="status">Loading exact {role} rows…</p>;
    if (query.isError) return <QueryError error={query.error} retry={() => void query.refetch()} />;
    const admission = admitPresentation(() =>
        mergeScientificSeriesPages(query.data.pages).filter(
            (point): point is ResearchSignalPoint => point.kind === "SIGNAL"
        )
    );
    if (!admission.ok) return <ContractFailure />;
    return (
        <ExactSection
            title={`Signal · ${role}`}
            query={query}
            rows={admission.value.map((point) => [
                point.tsEventNs.toString(),
                point.instrumentId,
                point.value === null ? "NULL" : String(point.value)
            ])}
            headings={["ts_event_ns", "Instrument", "Nullable Boolean"]}
        />
    );
}

function StatisticsExactTable({
    descriptor
}: {
    readonly descriptor: ReturnType<typeof useResultWorkspace>["statistics"]["statistics"][number];
}) {
    const { summary } = useResultWorkspace();
    const query = useInfiniteQuery(
        seriesOptions(
            useResearchApi(),
            summary.researchResultFingerprint,
            descriptor.statisticsFingerprint,
            100
        )
    );
    if (query.isPending) return <p role="status">Loading exact Statistics rows…</p>;
    if (query.isError) return <QueryError error={query.error} retry={() => void query.refetch()} />;
    const admission = admitPresentation(() => mergeSeriesPages(query.data.pages));
    if (!admission.ok) return <ContractFailure />;
    return (
        <ExactSection
            title={`Statistics · ${descriptor.definition.method}`}
            query={query}
            rows={admission.value.map((point) => [
                point.tsEventNs.toString(),
                point.statisticValue ?? "NULL",
                String(point.sampleCount),
                point.status
            ])}
            headings={["ts_event_ns", "Exact value", "Samples", "Status"]}
        />
    );
}

function ExactSection({
    title,
    headings,
    rows,
    query
}: {
    readonly title: string;
    readonly headings: readonly string[];
    readonly rows: readonly (readonly string[])[];
    readonly query: {
        readonly hasNextPage: boolean;
        readonly isFetchingNextPage: boolean;
        fetchNextPage(): Promise<unknown>;
    };
}) {
    return (
        <section className="exact-section">
            <div className="section-heading">
                <h3>{title}</h3>
                <span>{rows.length} exact rows loaded</span>
            </div>
            {rows.length === 0 ? (
                <p>No exact rows match this selector.</p>
            ) : (
                <div className="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                {headings.map((heading) => (
                                    <th key={heading}>{heading}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row, index) => (
                                <tr key={`${row[0] ?? ""}:${String(index)}`}>
                                    {row.map((value, column) => (
                                        <td key={String(headings[column] ?? column)}>
                                            <code>{value}</code>
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            {query.hasNextPage ? (
                <button
                    type="button"
                    disabled={query.isFetchingNextPage}
                    onClick={() => void query.fetchNextPage()}
                >
                    Load next exact page
                </button>
            ) : null}
        </section>
    );
}

function exactVariableValue(point: ResearchVariablePoint): string {
    if (point.valueKind === "DECIMAL") return point.decimalValue ?? "NULL";
    if (point.valueKind === "INTEGER") return point.integerValue ?? "NULL";
    if (point.valueKind === "BOOLEAN")
        return point.booleanValue === null ? "NULL" : String(point.booleanValue);
    return point.stringValue ?? "NULL";
}

function ContractFailure() {
    return (
        <p className="error" role="alert">
            CONTRACT_ERROR: paginated exact evidence is inconsistent
        </p>
    );
}
