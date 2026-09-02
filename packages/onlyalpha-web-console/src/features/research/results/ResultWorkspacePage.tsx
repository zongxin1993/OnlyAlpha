import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useReducer } from "react";
import { Link, useParams } from "react-router-dom";
import { useResearchApi } from "../../../app/providers";
import { ResearchWebError } from "../../../api/research/errors";
import { parseResearchResultFingerprint } from "../../../domain/research/identity";
import { QueryError } from "../../../shared/components/QueryState";
import {
    artifactOptions,
    candidateCatalogOptions,
    catalogOptions,
    publishedSeriesOptions
} from "../queries";
import { CandidateWorkspace } from "./components/CandidateWorkspace";
import { MarketWorkspace } from "./components/MarketWorkspace";
import { StatisticsWorkspace } from "./components/StatisticsWorkspace";
import { GraphInspector } from "./components/GraphInspector";
import { ExactDataWorkspace } from "./components/ExactDataWorkspace";
import { ResultOverview } from "./components/ResultOverview";
import { ResultWorkspaceProvider, useResultWorkspace } from "./ResultWorkspaceContext";
import {
    initialResultWorkspaceSelection,
    reduceResultWorkspace,
    type ResultWorkspaceTab
} from "./model/resultWorkspace";
import { publishedSeriesKey } from "./model/selectors";

const tabs: readonly { readonly id: ResultWorkspaceTab; readonly label: string }[] = [
    { id: "OVERVIEW", label: "Overview" },
    { id: "MARKET", label: "Market" },
    { id: "STATISTICS", label: "Statistics" },
    { id: "CANDIDATES", label: "Candidates" },
    { id: "GRAPH", label: "Graph" },
    { id: "EXACT_DATA", label: "Exact Data" }
];

export function ResultWorkspacePage() {
    const raw = useParams().researchResultFingerprint ?? "";
    let result: ReturnType<typeof parseResearchResultFingerprint> | null = null;
    try {
        result = parseResearchResultFingerprint(raw);
    } catch {
        // Rendered below before mounting API consumers.
    }
    if (result !== null) return <AdmittedResultWorkspace result={result} />;
    return (
        <main className="page">
            <div className="error" role="alert">
                INVALID_QUERY: route fingerprint is invalid
            </div>
        </main>
    );
}

function AdmittedResultWorkspace({
    result
}: {
    readonly result: ReturnType<typeof parseResearchResultFingerprint>;
}) {
    const client = useResearchApi();
    const summary = useQuery(artifactOptions(client, result));
    const statistics = useQuery(catalogOptions(client, result));
    const candidates = useQuery(candidateCatalogOptions(client, result));
    const published = useQuery({
        ...publishedSeriesOptions(client, result),
        enabled: candidates.isSuccess
    });
    const [selection, dispatch] = useReducer(
        reduceResultWorkspace,
        initialResultWorkspaceSelection
    );
    const scientificUnavailable =
        candidates.error instanceof ResearchWebError &&
        candidates.error.code === "SCIENTIFIC_EVIDENCE_NOT_AVAILABLE";
    const selectedCandidate = candidates.data?.candidates.find(
        (candidate) => candidate.candidateFingerprint === selection.candidateFingerprint
    );
    const compatibleSeries = useMemo(
        () =>
            (published.data?.series ?? []).filter(
                (series) =>
                    series.candidateFingerprint === null ||
                    series.candidateFingerprint === selectedCandidate?.candidateFingerprint
            ),
        [published.data, selectedCandidate]
    );
    const compatibleStatistics = useMemo(
        () =>
            (statistics.data?.statistics ?? []).filter((descriptor) =>
                selectedCandidate?.statisticsFingerprints.includes(descriptor.statisticsFingerprint)
            ),
        [selectedCandidate, statistics.data]
    );
    useEffect(() => {
        dispatch({
            type: "ADMIT_DEFAULTS",
            candidateFingerprint: candidates.data?.candidates[0]?.candidateFingerprint ?? null,
            instrumentId: summary.data?.instrumentIds[0] ?? null,
            seriesKey: compatibleSeries[0] ? publishedSeriesKey(compatibleSeries[0]) : null,
            statisticsFingerprint:
                compatibleStatistics[0]?.statisticsFingerprint ??
                statistics.data?.statistics[0]?.statisticsFingerprint ??
                null
        });
    }, [candidates.data, compatibleSeries, compatibleStatistics, statistics.data, summary.data]);

    if (summary.isPending || statistics.isPending || candidates.isPending)
        return (
            <main className="page">
                <p role="status">Loading verified Scientific Workstation…</p>
            </main>
        );
    if (summary.isError)
        return (
            <main className="page">
                <QueryError error={summary.error} retry={() => void summary.refetch()} />
            </main>
        );
    if (statistics.isError)
        return (
            <main className="page">
                <QueryError error={statistics.error} retry={() => void statistics.refetch()} />
            </main>
        );
    if (candidates.isError && !scientificUnavailable)
        return (
            <main className="page">
                <QueryError error={candidates.error} retry={() => void candidates.refetch()} />
            </main>
        );
    if (published.isError)
        return (
            <main className="page">
                <QueryError error={published.error} retry={() => void published.refetch()} />
            </main>
        );

    const value = {
        summary: summary.data,
        candidates: candidates.data ?? null,
        published: published.data ?? null,
        statistics: statistics.data,
        selection,
        dispatch,
        scientificUnavailable
    };
    return (
        <ResultWorkspaceProvider value={value}>
            <main className="page result-workspace">
                <nav>
                    <Link to="/research/results">← Open another exact result</Link>
                </nav>
                <p className="eyebrow">Verified immutable Research Artifact</p>
                <h1>Scientific Workstation</h1>
                <p className="result-identity">
                    <span>Exact Result</span>
                    <code>{result}</code>
                </p>
                <div className="result-tabs" role="tablist" aria-label="Scientific Result views">
                    {tabs.map((tab) => (
                        <button
                            key={tab.id}
                            type="button"
                            role="tab"
                            aria-selected={selection.tab === tab.id}
                            onClick={() => {
                                dispatch({ type: "TAB", value: tab.id });
                            }}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
                <ResultTab />
            </main>
        </ResultWorkspaceProvider>
    );
}

function ResultTab() {
    const { selection } = useResultWorkspace();
    if (selection.tab === "OVERVIEW") return <ResultOverview />;
    if (selection.tab === "MARKET") return <MarketWorkspace />;
    if (selection.tab === "STATISTICS") return <StatisticsWorkspace />;
    if (selection.tab === "CANDIDATES") return <CandidateWorkspace />;
    if (selection.tab === "GRAPH") return <GraphInspector />;
    return <ExactDataWorkspace />;
}
