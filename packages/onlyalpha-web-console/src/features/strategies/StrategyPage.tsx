import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useResearchApi } from "../../app/providers";
import { parseSha256Fingerprint, type Sha256Fingerprint } from "../../domain/research/identity";
import { ExactResourceForm } from "../../shared/components/ExactResourceForm";
import { admitResourceIdentity } from "../../shared/resourceIdentity";
import { QueryError } from "../../shared/components/QueryState";
import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";

export function StrategyPage() {
    const raw = useParams().strategyFingerprint;
    const navigate = useNavigate();
    const selected = admitResourceIdentity(raw, parseSha256Fingerprint);
    return (
        <main className="page product-inspector-page">
            <header className="catalog-header">
                <div>
                    <p className="eyebrow">Strategies · immutable identity</p>
                    <h1>Strategy Workspace</h1>
                    <p className="lede">
                        Inspect an existing frozen Strategy by its exact fingerprint. A Strategy
                        Revision defines semantics; it is not permission to trade.
                    </p>
                </div>
                <Link className="secondary-link" to="/research/results">
                    Research evidence <WorkspaceIcon name="arrow" />
                </Link>
            </header>
            <ExactResourceForm
                key={raw ?? "empty"}
                id="strategy-fingerprint"
                label="Strategy fingerprint"
                action="Open Strategy"
                initialValue={raw ?? ""}
                placeholder="64 lower-case hexadecimal characters"
                onOpen={(value) => {
                    const fingerprint = parseSha256Fingerprint(value);
                    void navigate(`/strategies/${fingerprint}`);
                }}
            />
            {selected.error === null ? null : (
                <p role="alert" className="error">
                    INVALID_QUERY: {selected.error}
                </p>
            )}
            {selected.value === null ? (
                <section className="product-empty">
                    <WorkspaceIcon name="shield" />
                    <h2>One Strategy. One immutable identity.</h2>
                    <p>
                        Enter a Strategy fingerprint to inspect its registered revision and
                        promotion references.
                    </p>
                    <span>No global Strategy catalog is exposed by the current Product API.</span>
                </section>
            ) : (
                <StrategyDetails key={selected.value} fingerprint={selected.value} />
            )}
        </main>
    );
}

function StrategyDetails({ fingerprint }: { readonly fingerprint: Sha256Fingerprint }) {
    const client = useResearchApi();
    const query = useQuery({
        queryKey: ["product", "strategy", fingerprint],
        queryFn: ({ signal }) => client.getStrategy(fingerprint, signal),
        staleTime: 0
    });
    if (query.isError)
        return (
            <QueryError
                title="Unable to load this Strategy."
                error={query.error}
                retry={() => void query.refetch()}
            />
        );
    if (query.isPending) return <p role="status">Loading authoritative Strategy references…</p>;
    const strategy = query.data;
    return (
        <div className="product-inspector-grid">
            <section className="catalog-panel">
                <div className="section-heading">
                    <h2>Strategy identity</h2>
                    <button
                        type="button"
                        className="quiet-button"
                        disabled={query.isFetching}
                        onClick={() => void query.refetch()}
                    >
                        {query.isFetching ? "Refreshing…" : "Refresh Strategy"}
                    </button>
                </div>
                <dl className="facts">
                    <dt>Strategy fingerprint</dt>
                    <dd>{strategy.strategy_fingerprint}</dd>
                    <dt>Reported promotion stage</dt>
                    <dd>{strategy.current_stage}</dd>
                    <dt>Transport schema version</dt>
                    <dd>{strategy.schema_version}</dd>
                </dl>
                <p className="product-boundary-note">
                    Promotion stage does not activate LIVE trading. No execution or promotion
                    command is available on this page.
                </p>
                <h3>Freeze relation references</h3>
                {strategy.freeze_relation_fingerprints.length === 0 ? (
                    <p>No Freeze relation references were returned.</p>
                ) : (
                    <ul className="exact-reference-list">
                        {strategy.freeze_relation_fingerprints.map((reference) => (
                            <li key={reference}>
                                <code>{reference}</code>
                            </li>
                        ))}
                    </ul>
                )}
            </section>
            <aside className="catalog-panel" aria-label="Strategy context">
                <h2>Evidence context</h2>
                <p>
                    The server returned {strategy.promotion_records.length} promotion records.
                    Open-ended revision payloads are not interpreted as a second Strategy model in
                    the browser.
                </p>
                <div className="product-workflow-note">
                    <WorkspaceIcon name="research" />
                    <span>
                        Research discovers.
                        <br />
                        Strategy Revision defines.
                        <br />
                        Backtest verifies.
                    </span>
                </div>
                <Link className="primary-link" to="/backtest/runs">
                    Inspect a Backtest <WorkspaceIcon name="arrow" />
                </Link>
            </aside>
        </div>
    );
}
