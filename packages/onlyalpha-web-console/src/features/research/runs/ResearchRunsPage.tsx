import { useInfiniteQuery } from "@tanstack/react-query";
import { useResearchApi } from "../../../app/providers";
import { QueryError } from "../../../shared/components/QueryState";
import { RunsTable } from "./RunsTable";
import { runsOptions } from "./queries";

export function ResearchRunsPage() {
    const client = useResearchApi();
    const query = useInfiniteQuery(runsOptions(client));
    if (query.isPending)
        return (
            <main className="page">
                <p role="status">Loading durable Research Runs…</p>
            </main>
        );
    if (query.isError)
        return (
            <main className="page">
                <QueryError error={query.error} retry={() => void query.refetch()} />
            </main>
        );
    const runs = query.data.pages.flatMap((page) => page.runs);
    return (
        <main className="page runs-page">
            <p className="eyebrow">PostgreSQL operational authority</p>
            <h1>Research Runs</h1>
            <p className="lede">
                Only authoritative states and timestamps are shown. No inferred progress.
            </p>
            {runs.length === 0 ? <p>No Runs have been submitted.</p> : <RunsTable runs={runs} />}
            {query.hasNextPage ? (
                <button
                    type="button"
                    disabled={query.isFetchingNextPage}
                    onClick={() => void query.fetchNextPage()}
                >
                    {query.isFetchingNextPage ? "Loading…" : "Load older Runs"}
                </button>
            ) : null}
        </main>
    );
}
