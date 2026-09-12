import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useResearchApi } from "../../app/providers";
import type { BacktestRunTransport } from "../../api/research/schemas";
import type { BacktestRunId } from "../../domain/research/identity";
import { QueryError } from "../../shared/components/QueryState";

export function BacktestEvidencePanel({
    run,
    id
}: {
    readonly run: BacktestRunTransport;
    readonly id: BacktestRunId;
}) {
    const client = useResearchApi();
    const query = useQuery({
        queryKey: ["product", "backtest-evidence", id, run.evidence_fingerprint],
        queryFn: ({ signal }) => client.getBacktestEvidence(id, signal),
        staleTime: Infinity
    });
    if (query.isError)
        return (
            <QueryError
                title="Unable to load Backtest Evidence."
                error={query.error}
                retry={() => void query.refetch()}
            />
        );
    if (query.isPending) return <p role="status">Loading verified Evidence manifest…</p>;
    const manifest = query.data.manifest;
    if (
        manifest.backtest_run_id !== run.run_id ||
        manifest.evidence_fingerprint !== run.evidence_fingerprint ||
        manifest.result_fingerprint !== run.result_fingerprint ||
        manifest.determinism_fingerprint !== run.determinism_fingerprint ||
        manifest.specification_fingerprint !== run.specification_fingerprint ||
        manifest.admission_resolution_fingerprint !== run.admission_resolution_fingerprint
    )
        return (
            <p className="error" role="alert">
                CONTRACT_ERROR: Run and Evidence references do not match. Unlinked evidence is not
                displayed.
            </p>
        );
    return (
        <div className="backtest-evidence">
            <p className="catalog-meta">Verified manifest linked to the exact completed Run.</p>
            <dl className="facts">
                <dt>Evidence fingerprint</dt>
                <dd>{manifest.evidence_fingerprint}</dd>
                <dt>Result fingerprint</dt>
                <dd>{manifest.result_fingerprint}</dd>
                <dt>Determinism fingerprint</dt>
                <dd>{manifest.determinism_fingerprint}</dd>
                <dt>Strategy</dt>
                <dd>
                    <Link to={`/strategies/${manifest.strategy_fingerprint}`}>
                        {manifest.strategy_fingerprint}
                    </Link>
                </dd>
                <dt>Kernel semantics version</dt>
                <dd>{manifest.kernel_semantics_version}</dd>
                <dt>Dataset Snapshot</dt>
                <dd>{manifest.base_dataset_snapshot_fingerprint}</dd>
                <dt>Dataset binding</dt>
                <dd>{manifest.dataset_binding_fingerprint}</dd>
            </dl>
            <details className="identity-inspector">
                <summary>Profile and implementation references</summary>
                <dl className="facts">
                    <dt>Market Product composition</dt>
                    <dd>{manifest.market_product_composition_fingerprint}</dd>
                    <dt>Portfolio profile</dt>
                    <dd>{manifest.portfolio_profile_fingerprint}</dd>
                    <dt>Risk profile</dt>
                    <dd>{manifest.risk_profile_fingerprint}</dd>
                    <dt>Execution profile</dt>
                    <dd>{manifest.execution_profile_fingerprint}</dd>
                </dl>
                <ul className="exact-reference-list">
                    {manifest.implementation_fingerprints.map((fingerprint) => (
                        <li key={fingerprint}>
                            <code>{fingerprint}</code>
                        </li>
                    ))}
                </ul>
            </details>
            <h3>Artifact metadata</h3>
            {manifest.artifacts.length === 0 ? (
                <p>No artifacts are listed in this manifest.</p>
            ) : (
                <ul className="artifact-metadata-list">
                    {manifest.artifacts.map((artifact) => (
                        <li key={artifact.name}>
                            <strong>{artifact.name}</strong>
                            <span>
                                {artifact.size} bytes · {artifact.media_type}
                            </span>
                            <code>{artifact.sha256}</code>
                        </li>
                    ))}
                </ul>
            )}
            <p className="product-boundary-note">
                This manifest does not expose returns, Sharpe or an equity curve. It is evidence
                linkage, not a performance assessment or promotion decision.
            </p>
        </div>
    );
}
