import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useResearchApi } from "../../app/providers";
import { parseBacktestRunId, type BacktestRunId } from "../../domain/research/identity";
import { ExactResourceForm } from "../../shared/components/ExactResourceForm";
import { QueryError } from "../../shared/components/QueryState";
import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";
import { admitResourceIdentity } from "../../shared/resourceIdentity";
import { BacktestEvidencePanel } from "./BacktestEvidencePanel";

export function BacktestPage() {
    const raw = useParams().backtestRunId;
    const navigate = useNavigate();
    const selected = admitResourceIdentity(raw, parseBacktestRunId);
    return (
        <main className="page product-inspector-page">
            <header className="catalog-header">
                <div>
                    <p className="eyebrow">Backtest · historical execution evidence</p>
                    <h1>Backtest Workspace</h1>
                    <p className="lede">
                        Inspect a durable Backtest Run and its verified Evidence manifest.
                        Performance values are shown only when a formal read contract supplies them.
                    </p>
                </div>
                <Link className="secondary-link" to="/strategies">
                    Strategy workspace <WorkspaceIcon name="arrow" />
                </Link>
            </header>
            <ExactResourceForm
                key={raw ?? "empty"}
                id="backtest-run-id"
                label="Backtest Run ID"
                action="Open Backtest"
                initialValue={raw ?? ""}
                placeholder="Exact canonical UUID4"
                onOpen={(value) => {
                    const id = parseBacktestRunId(value);
                    void navigate(`/backtest/runs/${id}`);
                }}
            />
            {selected.error === null ? null : (
                <p className="error" role="alert">
                    INVALID_QUERY: {selected.error}
                </p>
            )}
            {selected.value === null ? (
                <section className="product-empty">
                    <WorkspaceIcon name="results" />
                    <h2>Historical evidence, exact by identity.</h2>
                    <p>
                        Enter an existing Backtest Run ID to inspect its lifecycle and linked
                        immutable evidence.
                    </p>
                    <span>
                        The Product API has no global Backtest Run list. No returns, Sharpe or
                        equity curve are invented here.
                    </span>
                </section>
            ) : (
                <BacktestDetails key={selected.value} id={selected.value} />
            )}
        </main>
    );
}

function BacktestDetails({ id }: { readonly id: BacktestRunId }) {
    const client = useResearchApi();
    const query = useQuery({
        queryKey: ["product", "backtest-run", id],
        queryFn: ({ signal }) => client.getBacktestRun(id, signal),
        staleTime: 0
    });
    if (query.isError)
        return (
            <QueryError
                title="Unable to load this Backtest Run."
                error={query.error}
                retry={() => void query.refetch()}
            />
        );
    if (query.isPending) return <p role="status">Loading durable Backtest Run…</p>;
    const run = query.data;
    return (
        <div className="product-inspector-grid">
            <section className="catalog-panel">
                <div className="section-heading">
                    <h2>Run lifecycle</h2>
                    <button
                        type="button"
                        className="quiet-button"
                        disabled={query.isFetching}
                        onClick={() => void query.refetch()}
                    >
                        {query.isFetching ? "Refreshing…" : "Refresh Backtest"}
                    </button>
                </div>
                <p className="product-state">
                    <span>Reported state</span>
                    <strong>{run.state}</strong>
                </p>
                <dl className="facts">
                    <dt>Run ID</dt>
                    <dd>{run.run_id}</dd>
                    <dt>Revision</dt>
                    <dd>{run.revision}</dd>
                    <dt>Queued at</dt>
                    <dd>{run.queued_at}</dd>
                    <dt>Started at</dt>
                    <dd>{run.started_at ?? "Not reported"}</dd>
                    <dt>Finished at</dt>
                    <dd>{run.finished_at ?? "Not reported"}</dd>
                    <dt>Cancellation requested at</dt>
                    <dd>{run.cancel_requested_at ?? "Not requested"}</dd>
                    <dt>Specification</dt>
                    <dd>{run.specification_fingerprint}</dd>
                    <dt>Admission resolution</dt>
                    <dd>{run.admission_resolution_fingerprint}</dd>
                </dl>
                {run.failure === null ? null : (
                    <div className="error" role="alert">
                        <strong>
                            {run.failure.phase} · {run.failure.code}
                        </strong>
                        <p>{run.failure.detail}</p>
                    </div>
                )}
                <p className="product-boundary-note">
                    States and timestamps come from the durable Run. No inferred progress or
                    browser-owned execution state.
                </p>
            </section>
            <aside className="catalog-panel" aria-label="Backtest Evidence">
                <h2>Backtest Evidence</h2>
                {run.state !== "COMPLETED" ? (
                    <p>
                        Evidence becomes available only after the Run completes. The browser does
                        not construct partial official results.
                    </p>
                ) : run.evidence_fingerprint === null ? (
                    <p className="error" role="alert">
                        CONTRACT_ERROR: completed Run has no Evidence reference.
                    </p>
                ) : (
                    <BacktestEvidencePanel run={run} id={id} />
                )}
            </aside>
        </div>
    );
}
