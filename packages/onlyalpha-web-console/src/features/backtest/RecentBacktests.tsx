import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useResearchApi } from "../../app/providers";
import { QueryError } from "../../shared/components/QueryState";

export function RecentBacktests() {
    const client = useResearchApi();
    const query = useQuery({
        queryKey: ["product", "backtest-runs"],
        queryFn: ({ signal }) => client.listBacktestRuns(signal),
        staleTime: 0
    });
    return (
        <section className="catalog-panel">
            <h2>Recent Backtests</h2>
            {query.isPending ? <p role="status">Loading recent Backtests…</p> : null}
            {query.isError ? (
                <QueryError
                    title="Unable to load recent Backtests."
                    error={query.error}
                    retry={() => void query.refetch()}
                />
            ) : null}
            {query.data?.length === 0 ? <p>No Backtests have been submitted.</p> : null}
            <ul>
                {query.data?.map((run) => (
                    <li key={run.run_id}>
                        <Link to={`/backtest/runs/${run.run_id}`}>
                            {run.queued_at} · {run.state} · {run.run_id}
                        </Link>
                    </li>
                ))}
            </ul>
            <p>
                Latest 50 durable Runs. An open Run resumes through the same URL after reload; a
                restarted worker recovers its original Runtime.
            </p>
        </section>
    );
}
