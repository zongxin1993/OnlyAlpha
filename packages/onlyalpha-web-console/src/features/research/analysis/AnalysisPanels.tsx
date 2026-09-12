import { Link } from "react-router-dom";
import type { ResearchRunSummary } from "../../../domain/research/model";
import { WorkspaceIcon, type WorkspaceIconName } from "../../../shared/components/WorkspaceIcon";
import { RunStateBadge } from "../runs/RunStateBadge";

const opportunities: readonly {
    readonly title: string;
    readonly label: string;
    readonly detail: string;
    readonly to: string;
    readonly icon: WorkspaceIconName;
    readonly source: string;
}[] = [
    {
        title: "Explore evidence",
        label: "RESULTS",
        detail: "Inspect an exact immutable Research result.",
        to: "/research/results",
        icon: "analysis",
        source: "Artifact"
    },
    {
        title: "Observe research",
        label: "RUNS",
        detail: "Follow durable Run states and result references.",
        to: "/research/runs",
        icon: "runs",
        source: "Run facts"
    },
    {
        title: "Build a hypothesis",
        label: "RESEARCH",
        detail: "Compose and validate your next Research definition.",
        to: "/research/new",
        icon: "research",
        source: "Definition"
    },
    {
        title: "Discover capabilities",
        label: "LIBRARY",
        detail: "Inspect registered types, versions and parameters.",
        to: "/research/library",
        icon: "library",
        source: "Catalog"
    }
];

function OpportunityCard({
    opportunity
}: {
    readonly opportunity: (typeof opportunities)[number];
}) {
    return (
        <Link className="opportunity-card" to={opportunity.to}>
            <div className="opportunity-card-title">
                <strong>{opportunity.title}</strong>
                <span className="analysis-badge">{opportunity.label}</span>
            </div>
            <div className="opportunity-card-facts">
                <div>
                    <span>SOURCE</span>
                    <strong>{opportunity.source}</strong>
                </div>
                <div>
                    <span>WORKFLOW</span>
                    <strong>Research</strong>
                </div>
                <WorkspaceIcon name={opportunity.icon} />
            </div>
            <p>
                {opportunity.detail}
                <WorkspaceIcon name="arrow" />
            </p>
        </Link>
    );
}

export function OpportunityRadar() {
    return (
        <section className="opportunity-radar" aria-labelledby="opportunity-heading">
            <div className="analysis-section-heading">
                <div>
                    <h1 id="opportunity-heading">AI Opportunity Radar</h1>
                    <p>Research shortcuts · not AI recommendations or trading signals</p>
                </div>
                <span className="analysis-badge">EVIDENCE FIRST</span>
            </div>
            <div className="opportunity-cards">
                {opportunities.map((opportunity) => (
                    <OpportunityCard key={opportunity.to} opportunity={opportunity} />
                ))}
            </div>
        </section>
    );
}

export function MarketTickerStrip() {
    return (
        <section className="market-ticker" aria-label="Market ticker">
            <span className="market-ticker-notice">
                MARKET FEED <span>Unavailable</span>
            </span>
            {["Prices", "Change", "Volatility", "Breadth", "Market signals"].map((label) => (
                <span className="market-ticker-item" key={label}>
                    {label}
                    <strong>—</strong>
                </span>
            ))}
        </section>
    );
}

export function MarketPulseGrid() {
    return (
        <section className="analysis-panel market-pulse" aria-labelledby="market-pulse-heading">
            <header>
                <WorkspaceIcon name="results" />
                <h2 id="market-pulse-heading">Market Pulse</h2>
                <span className="analysis-badge">NO FEED</span>
            </header>
            <p className="analysis-caption">Heatmap · no governed market data</p>
            <div className="market-pulse-grid">
                {[
                    "Equities",
                    "Futures",
                    "Crypto",
                    "FX",
                    "Rates",
                    "Commodities",
                    "Sectors",
                    "Indices",
                    "Funds"
                ].map((label) => (
                    <div className="market-pulse-cell" key={label}>
                        <span>{label}</span>
                        <strong>—</strong>
                        <small>Unavailable</small>
                    </div>
                ))}
            </div>
            <p className="analysis-footnote">No prices, changes or market rankings are inferred.</p>
        </section>
    );
}

export function EconomicCalendarPanel() {
    return (
        <section className="analysis-panel economic-calendar" aria-labelledby="calendar-heading">
            <header>
                <WorkspaceIcon name="calendar" />
                <h2 id="calendar-heading">Economic Calendar</h2>
            </header>
            <div className="calendar-columns" aria-hidden="true">
                <span>TIME</span>
                <span>EVENT</span>
                <span>IMPACT</span>
            </div>
            <div className="calendar-empty">
                <WorkspaceIcon name="calendar" />
                <strong>Event feed unavailable</strong>
                <p>No official calendar source is connected to this workspace.</p>
            </div>
        </section>
    );
}

export function RecentResearchPanel({
    runs,
    loading,
    unavailable,
    onSelectResult
}: {
    readonly runs: readonly ResearchRunSummary[];
    readonly loading: boolean;
    readonly unavailable: boolean;
    readonly onSelectResult: () => void;
}) {
    const resultRuns = runs
        .filter(
            (run): run is ResearchRunSummary & { readonly resultRef: string } =>
                run.state === "COMPLETED" && run.resultRef !== null
        )
        .filter(
            (run, index, items) =>
                items.findIndex((item) => item.resultRef === run.resultRef) === index
        );
    return (
        <aside className="analysis-recent-rail" aria-label="Recent Research">
            <section className="analysis-panel recent-research">
                <header>
                    <WorkspaceIcon name="clock" />
                    <h2>Recent Runs</h2>
                    <Link to="/research/runs" aria-label="View all Research Runs">
                        <WorkspaceIcon name="arrow" />
                    </Link>
                </header>
                <p className="analysis-caption">From the loaded operational Run page</p>
                {loading ? (
                    <p role="status">Loading Run references…</p>
                ) : unavailable ? (
                    <p className="analysis-footnote">Run data is unavailable.</p>
                ) : runs.length === 0 ? (
                    <div className="rail-empty">
                        <WorkspaceIcon name="runs" />
                        <strong>No Research Runs yet</strong>
                        <Link to="/research/new">Define your first Research</Link>
                    </div>
                ) : (
                    <ul className="recent-research-list">
                        {runs.slice(0, 6).map((run) => (
                            <li key={run.runId}>
                                <Link to={`/research/runs/${run.runId}`}>
                                    <span className="recent-run-title">
                                        <code title={run.runId}>
                                            {run.runId.slice(0, 8)}…{run.runId.slice(-4)}
                                        </code>
                                        <RunStateBadge state={run.state} />
                                    </span>
                                    <time dateTime={run.queuedAt}>{run.queuedAt}</time>
                                </Link>
                            </li>
                        ))}
                    </ul>
                )}
            </section>
            <section className="analysis-panel recent-results">
                <header>
                    <WorkspaceIcon name="results" />
                    <h2>Result References</h2>
                </header>
                <p className="analysis-caption">Exact Results from loaded completed Runs</p>
                {resultRuns.length === 0 ? (
                    <p className="analysis-footnote">
                        {loading
                            ? "Waiting for Run references."
                            : unavailable
                              ? "Result references unavailable."
                              : "No completed Result references in this Run page."}
                    </p>
                ) : (
                    <ul className="recent-research-list">
                        {resultRuns.slice(0, 4).map((run) => (
                            <li key={run.resultRef}>
                                <Link
                                    to={`/research/analysis?result=${run.resultRef}`}
                                    onClick={onSelectResult}
                                >
                                    <span className="recent-run-title">
                                        <code title={run.resultRef}>
                                            {run.resultRef.slice(0, 12)}…
                                        </code>
                                        <WorkspaceIcon name="arrow" />
                                    </span>
                                    <span>Open authoritative evidence</span>
                                </Link>
                            </li>
                        ))}
                    </ul>
                )}
                <Link className="analysis-text-link" to="/research/results">
                    Open an exact Result <WorkspaceIcon name="arrow" />
                </Link>
            </section>
            <div className="analysis-authority-note">
                <WorkspaceIcon name="shield" />
                <p>
                    Immutable evidence.
                    <br />
                    No browser-owned research truth.
                </p>
            </div>
        </aside>
    );
}
