import { useQuery } from "@tanstack/react-query";
import { useResearchApi } from "../../app/providers";
import type { ProductHealthSelector } from "../../api/research/client";
import { QueryError } from "../../shared/components/QueryState";
import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";

const checks: readonly {
    readonly selector: ProductHealthSelector;
    readonly title: string;
    readonly description: string;
}[] = [
    {
        selector: "live",
        title: "HTTP process",
        description: "Process liveness only. LIVE here never means live trading."
    },
    {
        selector: "ready",
        title: "API readiness",
        description: "Readiness reported by the API and its required authorities."
    },
    {
        selector: "execution",
        title: "Backtest execution",
        description: "Reported Backtest worker capacity, not trading permission."
    }
];

export function SystemHealthPage() {
    return (
        <main className="page product-inspector-page">
            <header className="catalog-header">
                <div>
                    <p className="eyebrow">System · independent health observations</p>
                    <h1>System Health</h1>
                    <p className="lede">
                        Inspect the three formal health surfaces independently. A reachable process
                        does not prove API readiness or execution capability.
                    </p>
                </div>
                <span className="analysis-badge">READ ONLY</span>
            </header>
            <div className="product-boundary-note">
                <WorkspaceIcon name="shield" /> These observations do not authorize LIVE trading or
                change any Runtime state.
            </div>
            <div className="health-grid">
                {checks.map((check) => (
                    <HealthCard key={check.selector} {...check} />
                ))}
            </div>
        </main>
    );
}

function HealthCard({ selector, title, description }: (typeof checks)[number]) {
    const client = useResearchApi();
    const query = useQuery({
        queryKey: ["product", "health", selector],
        queryFn: ({ signal }) => client.getHealth(selector, signal),
        staleTime: 0
    });
    return (
        <section className="catalog-panel health-card" aria-label={title}>
            <header>
                <WorkspaceIcon name="shield" />
                <h2>{title}</h2>
            </header>
            <p className="catalog-meta">{description}</p>
            <code className="health-endpoint">GET /health/{selector}</code>
            {query.isError ? (
                <QueryError
                    title={`Unable to read ${title}.`}
                    error={query.error}
                    retry={() => void query.refetch()}
                />
            ) : query.isPending ? (
                <p role="status">Reading health response…</p>
            ) : (
                <>
                    <p className="health-reported-status">
                        <span>Reported status</span>
                        <strong>{query.data.status}</strong>
                    </p>
                    {query.data.reason === undefined || query.data.reason === null ? null : (
                        <p className="health-reason">{query.data.reason}</p>
                    )}
                    <dl className="health-checks">
                        {Object.entries(query.data.checks).map(([name, status]) => (
                            <div key={name}>
                                <dt>{name}</dt>
                                <dd>{status}</dd>
                            </div>
                        ))}
                    </dl>
                    {Object.keys(query.data.checks).length === 0 ? (
                        <p className="catalog-meta">No individual checks were returned.</p>
                    ) : null}
                    <p className="catalog-meta">
                        {query.isFetching
                            ? "Refreshing; the previous response is shown."
                            : "Last response read by this browser:"}
                        <br />
                        <time dateTime={new Date(query.dataUpdatedAt).toISOString()}>
                            {new Date(query.dataUpdatedAt).toISOString()}
                        </time>
                    </p>
                    <button
                        type="button"
                        className="quiet-button"
                        aria-label={`Refresh ${title}`}
                        disabled={query.isFetching}
                        onClick={() => void query.refetch()}
                    >
                        {query.isFetching ? "Refreshing…" : "Refresh observation"}
                    </button>
                </>
            )}
        </section>
    );
}
