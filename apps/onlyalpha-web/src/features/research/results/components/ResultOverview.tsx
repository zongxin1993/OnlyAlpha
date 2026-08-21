import { useResultWorkspace } from "../ResultWorkspaceContext";

export function ResultOverview() {
    const { summary } = useResultWorkspace();
    return (
        <section aria-labelledby="result-overview-heading">
            <h2 id="result-overview-heading">Scientific evidence overview</h2>
            <div className="evidence-summary">
                <article>
                    <strong>{summary.candidateCount}</strong>
                    <span>Candidates</span>
                </article>
                <article>
                    <strong>{summary.publishedSeriesCount}</strong>
                    <span>Published series</span>
                </article>
                <article>
                    <strong>{summary.signalSeriesCount}</strong>
                    <span>Signal series</span>
                </article>
                <article>
                    <strong>{summary.statisticsCount}</strong>
                    <span>Statistics</span>
                </article>
                <article>
                    <strong>{summary.rowCount}</strong>
                    <span>Statistics rows</span>
                </article>
                <article>
                    <strong>{summary.marketRowCount}</strong>
                    <span>Market rows</span>
                </article>
            </div>
            <details className="identity-inspector">
                <summary>Inspect exact identities</summary>
                <dl className="facts">
                    <dt>Research Result</dt>
                    <dd>{summary.researchResultFingerprint}</dd>
                    <dt>Dataset Snapshot</dt>
                    <dd>{summary.datasetSnapshotFingerprint}</dd>
                    <dt>Artifact content</dt>
                    <dd>{summary.artifactContentFingerprint}</dd>
                    <dt>Result plan</dt>
                    <dd>{summary.researchResultPlanFingerprint}</dd>
                    <dt>Result content</dt>
                    <dd>{summary.researchResultContentFingerprint}</dd>
                    <dt>Profile / schema</dt>
                    <dd>
                        {summary.artifactProfile} / {summary.artifactSchemaVersion}
                    </dd>
                    <dt>Created at UTC</dt>
                    <dd>{summary.createdAt}</dd>
                </dl>
            </details>
        </section>
    );
}
