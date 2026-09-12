import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useResearchApi } from "../../../app/providers";
import type { ResearchResultFingerprint } from "../../../domain/research/identity";
import { QueryError } from "../../../shared/components/QueryState";
import { WorkspaceIcon } from "../../../shared/components/WorkspaceIcon";
import { artifactOptions, catalogOptions } from "../queries";
import { StatisticsEvidence } from "../results/components/StatisticsWorkspace";

export function AnalysisEnginePanel({
    result
}: {
    readonly result: ResearchResultFingerprint | null;
}) {
    return (
        <section
            className={`analysis-engine${result === null ? " analysis-engine-empty" : ""}`}
            aria-label="Analysis canvas"
        >
            {result === null ? (
                <div className="analysis-welcome">
                    <span className="analysis-engine-symbol">
                        <WorkspaceIcon name="analysis" />
                    </span>
                    <span className="analysis-badge">AUTHORITATIVE RESEARCH EVIDENCE</span>
                    <h2>OnlyAlpha Analysis</h2>
                    <p>
                        Select an existing Research Result or completed Run
                        <br />
                        to inspect authoritative evidence.
                    </p>
                    <div className="analysis-capabilities">
                        <span>
                            <WorkspaceIcon name="results" />
                            Exact results
                        </span>
                        <span>
                            <WorkspaceIcon name="data" />
                            Published statistics
                        </span>
                        <span>
                            <WorkspaceIcon name="shield" />
                            Traceable inputs
                        </span>
                    </div>
                    <div className="analysis-welcome-actions">
                        <Link className="primary-link" to="/research/results">
                            Open exact Result <WorkspaceIcon name="arrow" />
                        </Link>
                        <Link className="secondary-link" to="/research/new">
                            New Research
                        </Link>
                    </div>
                    <small>
                        This workspace inspects evidence; it does not generate AI trading advice.
                    </small>
                </div>
            ) : (
                <SelectedEvidence key={result} result={result} />
            )}
        </section>
    );
}

function SelectedEvidence({ result }: { readonly result: ResearchResultFingerprint }) {
    const client = useResearchApi();
    const summary = useQuery(artifactOptions(client, result));
    const statistics = useQuery(catalogOptions(client, result));
    if (summary.isError)
        return <QueryError error={summary.error} retry={() => void summary.refetch()} />;
    if (statistics.isError)
        return <QueryError error={statistics.error} retry={() => void statistics.refetch()} />;
    if (summary.isPending || statistics.isPending)
        return <p role="status">Loading exact Research evidence…</p>;
    const evidence = summary.data;
    const descriptor = statistics.data.statistics[0];
    return (
        <div className="analysis-evidence">
            <div className="analysis-section-heading">
                <div>
                    <span className="analysis-badge">VERIFIED ARTIFACT</span>
                    <h2>Research evidence</h2>
                </div>
                <Link className="analysis-text-link" to={`/research/results/${result}`}>
                    Full workspace <WorkspaceIcon name="arrow" />
                </Link>
            </div>
            <p className="analysis-result-identity">
                <span>Exact Result</span>
                <code>{result}</code>
            </p>
            <div className="analysis-evidence-counts">
                <div>
                    <strong>{evidence.candidateCount}</strong>
                    <span>Candidates</span>
                </div>
                <div>
                    <strong>{evidence.statisticsCount}</strong>
                    <span>Statistics</span>
                </div>
                <div>
                    <strong>{evidence.publishedSeriesCount}</strong>
                    <span>Published series</span>
                </div>
            </div>
            <dl className="analysis-evidence-context">
                <dt>Instruments</dt>
                <dd>
                    {evidence.instrumentIds.length === 0
                        ? "Not included in this Artifact"
                        : evidence.instrumentIds.join(", ")}
                </dd>
                <dt>Created at UTC</dt>
                <dd>{evidence.createdAt}</dd>
                <dt>Artifact profile</dt>
                <dd>{evidence.artifactProfile}</dd>
            </dl>
            <details className="identity-inspector">
                <summary>Research path and exact evidence references</summary>
                <p>Dataset Snapshot → Research Result → Verified Artifact → Published Statistics</p>
                <dl className="facts">
                    <dt>Dataset Snapshot</dt>
                    <dd>{evidence.datasetSnapshotFingerprint}</dd>
                    <dt>Result plan</dt>
                    <dd>{evidence.researchResultPlanFingerprint}</dd>
                    <dt>Result content</dt>
                    <dd>{evidence.researchResultContentFingerprint}</dd>
                    <dt>Artifact content</dt>
                    <dd>{evidence.artifactContentFingerprint}</dd>
                </dl>
            </details>
            <section className="analysis-statistics" aria-labelledby="analysis-statistics-heading">
                <h3 id="analysis-statistics-heading">Published Statistics</h3>
                {descriptor === undefined ? (
                    <p className="analysis-footnote">
                        This Artifact contains no Statistics evidence.
                    </p>
                ) : (
                    <>
                        <p className="analysis-caption">
                            {descriptor.definition.method} · {descriptor.feature.outputName} →{" "}
                            {descriptor.target.outputName}
                        </p>
                        <StatisticsEvidence result={result} descriptor={descriptor} />
                    </>
                )}
                {statistics.data.statistics.length > 1 ? (
                    <Link className="analysis-text-link" to={`/research/results/${result}`}>
                        Inspect all published Statistics in the full workspace
                    </Link>
                ) : null}
            </section>
        </div>
    );
}

export function ResearchJourney() {
    return (
        <section className="analysis-engine research-journey" aria-label="Research workflow">
            <span className="analysis-badge">DEFINE → RUN → OBSERVE → ANALYZE</span>
            <h2>Your Research workflow</h2>
            <p>Every analysis begins with formal inputs and ends with exact evidence.</p>
            <div className="research-journey-steps">
                <Link to="/research/new">
                    <span>01</span>
                    <strong>Define Research</strong>
                    <p>Compose intent and validate an exact Specification.</p>
                </Link>
                <Link to="/research/runs">
                    <span>02</span>
                    <strong>Observe Runs</strong>
                    <p>Read durable state and completed Result references.</p>
                </Link>
                <Link to="/research/results">
                    <span>03</span>
                    <strong>Inspect Results</strong>
                    <p>Explore immutable evidence, statistics and charts.</p>
                </Link>
            </div>
            <Link className="analysis-text-link" to="/research/library">
                Browse admitted research capabilities <WorkspaceIcon name="arrow" />
            </Link>
        </section>
    );
}
