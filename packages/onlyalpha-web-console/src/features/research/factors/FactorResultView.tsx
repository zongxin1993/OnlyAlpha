import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useResearchApi } from "../../../app/providers";
import { ResearchWebError } from "../../../api/research/errors";
import type { ResearchResultFingerprint } from "../../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchCandidate,
    ResearchPublishedSeriesCatalog,
    ResearchStatisticsCatalog
} from "../../../domain/research/model";
import { QueryError } from "../../../shared/components/QueryState";
import {
    artifactOptions,
    candidateCatalogOptions,
    catalogOptions,
    graphOptions,
    publishedSeriesOptions
} from "../queries";
import { admittedFactorSeries, type FactorSeriesOption } from "./factorModel";
import { FactorEvidenceView } from "./FactorEvidenceView";

export function FactorResultView({ result }: { readonly result: ResearchResultFingerprint }) {
    const client = useResearchApi();
    const summary = useQuery(artifactOptions(client, result));
    const candidates = useQuery(candidateCatalogOptions(client, result));
    const published = useQuery({
        ...publishedSeriesOptions(client, result),
        enabled: candidates.isSuccess
    });
    const statistics = useQuery(catalogOptions(client, result));
    const [params, setParams] = useSearchParams();
    for (const query of [summary, candidates, published, statistics]) {
        if (query.isError)
            return query.error instanceof ResearchWebError &&
                query.error.code === "SCIENTIFIC_EVIDENCE_NOT_AVAILABLE" ? (
                <p className="warning">
                    This Artifact profile has no published Factor Graph evidence. No factor values
                    or correlations are inferred.
                </p>
            ) : (
                <QueryError error={query.error} retry={() => void query.refetch()} />
            );
    }
    if (
        !summary.isSuccess ||
        !candidates.isSuccess ||
        !published.isSuccess ||
        !statistics.isSuccess
    )
        return <p role="status">Loading exact Factor evidence selectors…</p>;
    if (
        summary.data.researchResultFingerprint !== result ||
        candidates.data.researchResultFingerprint !== result ||
        published.data.researchResultFingerprint !== result ||
        statistics.data.researchResultFingerprint !== result ||
        new Set(summary.data.instrumentIds).size !== summary.data.instrumentIds.length
    )
        return (
            <p className="error" role="alert">
                CONTRACT_ERROR: Result selectors contain mismatched or duplicate identities.
            </p>
        );
    const selected = params.get("candidate");
    const candidate =
        selected === null
            ? candidates.data.candidates.length === 1
                ? candidates.data.candidates[0]
                : undefined
            : candidates.data.candidates.find((item) => item.candidateFingerprint === selected);
    return (
        <div className="factor-result">
            <div className="factor-result-context">
                <div>
                    <span className="analysis-badge">IMMUTABLE ARTIFACT</span>
                    <h2>Research evidence</h2>
                    <p>
                        Created at {summary.data.createdAt} · historical evidence, not a live feed
                    </p>
                </div>
                <Link to={`/research/results/${result}`}>Full Result workspace →</Link>
            </div>
            <details className="factor-identities">
                <summary>Exact Result and Dataset identities</summary>
                <dl>
                    <dt>Result</dt>
                    <dd>
                        <code>{result}</code>
                    </dd>
                    <dt>Dataset Snapshot</dt>
                    <dd>
                        <code>{summary.data.datasetSnapshotFingerprint}</code>
                    </dd>
                    <dt>Artifact content</dt>
                    <dd>
                        <code>{summary.data.artifactContentFingerprint}</code>
                    </dd>
                    <dt>Artifact instruments</dt>
                    <dd>{summary.data.instrumentIds.join(", ") || "None"}</dd>
                </dl>
            </details>
            <label className="factor-candidate-selector">
                Exact Research Candidate
                <select
                    aria-label="Exact Research Candidate"
                    value={candidate?.candidateFingerprint ?? ""}
                    onChange={(event) => {
                        setParams((previous) => {
                            const next = new URLSearchParams(previous);
                            next.set("candidate", event.target.value);
                            next.delete("series");
                            next.delete("statistic");
                            return next;
                        });
                    }}
                >
                    <option value="">Select a Candidate</option>
                    {candidates.data.candidates.map((item) => (
                        <option key={item.candidateFingerprint} value={item.candidateFingerprint}>
                            {item.candidateCalculationId} · {item.candidateFingerprint}
                        </option>
                    ))}
                </select>
            </label>
            {candidate === undefined ? (
                <p
                    className={selected === null ? "factor-empty-message" : "error"}
                    role={selected === null ? "status" : "alert"}
                >
                    {selected === null
                        ? "Choose an exact Candidate to inspect its published Factor outputs."
                        : "INVALID_QUERY: Candidate is not a member of this Result."}
                </p>
            ) : (
                <CandidateFactorEvidence
                    key={candidate.candidateFingerprint}
                    result={result}
                    summary={summary.data}
                    candidate={candidate}
                    published={published.data}
                    statistics={statistics.data}
                />
            )}
        </div>
    );
}

function CandidateFactorEvidence({
    result,
    summary,
    candidate,
    published,
    statistics
}: {
    readonly result: ResearchResultFingerprint;
    readonly summary: ResearchArtifactSummary;
    readonly candidate: ResearchCandidate;
    readonly published: ResearchPublishedSeriesCatalog;
    readonly statistics: ResearchStatisticsCatalog;
}) {
    const client = useResearchApi();
    const graph = useQuery(graphOptions(client, result, candidate.candidateFingerprint));
    if (graph.isError) return <QueryError error={graph.error} retry={() => void graph.refetch()} />;
    if (graph.isPending) return <p role="status">Verifying exact Factor Graph membership…</p>;
    let options: readonly FactorSeriesOption[];
    try {
        options = admittedFactorSeries(result, candidate, graph.data, published);
    } catch (error) {
        return (
            <p className="error" role="alert">
                {error instanceof Error ? error.message : "CONTRACT_ERROR: invalid Factor binding"}
            </p>
        );
    }
    return (
        <FactorEvidenceView
            result={result}
            summary={summary}
            candidate={candidate}
            options={options}
            statistics={statistics}
        />
    );
}
