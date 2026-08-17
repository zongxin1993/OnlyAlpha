import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { parseResearchResultFingerprint } from "../../../domain/research/identity";
import { useResearchApi } from "../../../app/providers";
import { QueryError } from "../../../shared/components/QueryState";
import { artifactOptions, catalogOptions } from "../queries";

export function ArtifactOverviewPage() {
    const { researchResultFingerprint: raw = "" } = useParams();
    let result: ReturnType<typeof parseResearchResultFingerprint> | null = null;
    try {
        result = parseResearchResultFingerprint(raw);
    } catch {
        // Admission is rendered below, before any API consumer is mounted.
    }
    return result === null ? (
        <main className="page">
            <div className="error" role="alert">
                INVALID_QUERY: route fingerprint is invalid
            </div>
        </main>
    ) : (
        <ValidArtifactOverviewPage result={result} />
    );
}

function ValidArtifactOverviewPage({
    result
}: {
    readonly result: ReturnType<typeof parseResearchResultFingerprint>;
}) {
    const client = useResearchApi();
    const summary = useQuery(artifactOptions(client, result));
    const catalog = useQuery(catalogOptions(client, result));
    if (summary.isPending || catalog.isPending)
        return (
            <main className="page">
                <p role="status">Loading verified Artifact…</p>
            </main>
        );
    if (summary.isError)
        return (
            <main className="page">
                <QueryError error={summary.error} retry={() => void summary.refetch()} />
            </main>
        );
    if (catalog.isError)
        return (
            <main className="page">
                <QueryError error={catalog.error} retry={() => void catalog.refetch()} />
            </main>
        );

    return (
        <main className="page">
            <nav>
                <Link to="/research">← Open another exact result</Link>
            </nav>
            <p className="eyebrow">Verified immutable Research Artifact</p>
            <h1>Artifact overview</h1>
            <dl className="facts">
                <dt>Research Result</dt>
                <dd>{summary.data.researchResultFingerprint}</dd>
                <dt>Dataset Snapshot</dt>
                <dd>{summary.data.datasetSnapshotFingerprint}</dd>
                <dt>Artifact content</dt>
                <dd>{summary.data.artifactContentFingerprint}</dd>
                <dt>Created at UTC</dt>
                <dd>{summary.data.createdAt}</dd>
                <dt>Profile / schema</dt>
                <dd>
                    {summary.data.artifactProfile} / {summary.data.artifactSchemaVersion}
                </dd>
                <dt>Statistics / rows</dt>
                <dd>
                    {summary.data.statisticsCount} / {summary.data.rowCount}
                </dd>
            </dl>
            <section>
                <h2>Statistics catalog</h2>
                {catalog.data.statistics.length === 0 ? (
                    <p>No Statistics are members of this Artifact.</p>
                ) : (
                    <ul className="catalog">
                        {catalog.data.statistics.map((item) => (
                            <li key={item.statisticsFingerprint}>
                                <Link
                                    to={`/research/${result}/statistics/${item.statisticsFingerprint}`}
                                >
                                    <strong>{item.definition.method}</strong>
                                    <code>{item.statisticsFingerprint}</code>
                                    <span>
                                        {item.feature.outputName} → {item.target.outputName} ·{" "}
                                        {item.rowCount} rows
                                    </span>
                                </Link>
                            </li>
                        ))}
                    </ul>
                )}
            </section>
        </main>
    );
}
