import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { researchQueryKeys } from "../../../api/research/queryKeys";
import { useResearchApi } from "../../../app/providers";
import { parseResearchRunId } from "../../../domain/research/identity";
import { QueryError } from "../../../shared/components/QueryState";
import { RunStateBadge } from "./RunStateBadge";
import { runOptions } from "./queries";

export function ResearchRunPage() {
    const raw = useParams().runId ?? "";
    let runId: ReturnType<typeof parseResearchRunId> | null = null;
    try {
        runId = parseResearchRunId(raw);
    } catch {
        // Render admission below without mounting an API consumer.
    }
    return runId === null ? (
        <main className="page">
            <div className="error" role="alert">
                RESEARCH_RUN_ID_INVALID: route identity is invalid
            </div>
        </main>
    ) : (
        <ValidResearchRunPage runId={runId} />
    );
}

function ValidResearchRunPage({
    runId
}: {
    readonly runId: ReturnType<typeof parseResearchRunId>;
}) {
    const client = useResearchApi();
    const queryClient = useQueryClient();
    const query = useQuery(runOptions(client, runId));
    const cancel = useMutation({
        mutationFn: () => client.cancelRun(runId),
        onSuccess: (run) => queryClient.setQueryData(researchQueryKeys.run(runId), run)
    });
    if (query.isPending)
        return (
            <main className="page">
                <p role="status">Loading authoritative Run…</p>
            </main>
        );
    if (query.isError)
        return (
            <main className="page">
                <QueryError error={query.error} retry={() => void query.refetch()} />
            </main>
        );
    const run = query.data;
    const cancellable = run.state === "QUEUED" || run.state === "RUNNING";
    return (
        <main className="page run-detail-page">
            <nav>
                <Link to="/research/runs">← All Runs</Link>
            </nav>
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Durable Research Run</p>
                    <h1>Run detail</h1>
                </div>
                <RunStateBadge state={run.state} />
            </div>
            <dl className="facts">
                <Fact label="Run ID" value={run.runId} />
                <Fact label="Revision" value={run.revision.toString()} />
                <Fact label="State" value={run.state} />
                <Fact label="Queued" value={run.queuedAt} />
                <Fact label="Started" value={run.startedAt} />
                <Fact label="Cancel requested" value={run.cancelRequestedAt} />
                <Fact label="Finished" value={run.finishedAt} />
                <Fact label="Specification" value={run.specificationFingerprint} />
                <Fact label="Admission resolution" value={run.admissionResolutionFingerprint} />
                <Fact label="Result reference" value={run.resultRef} />
                <Fact label="Artifact reference" value={run.artifactRef} />
            </dl>
            {run.failure === null ? null : (
                <section className="error" role="alert">
                    <strong>
                        {run.failure.phase} · {run.failure.code}
                    </strong>
                    <p>{run.failure.detail}</p>
                </section>
            )}
            <div className="run-actions">
                {cancellable ? (
                    <button
                        type="button"
                        className="button-danger"
                        disabled={cancel.isPending}
                        onClick={() => {
                            cancel.mutate();
                        }}
                    >
                        {cancel.isPending ? "Requesting…" : "Request cancellation"}
                    </button>
                ) : null}
                {run.state === "COMPLETED" && run.resultRef !== null ? (
                    <Link className="button-link" to={`/research/results/${run.resultRef}`}>
                        Open exact Result
                    </Link>
                ) : null}
            </div>
            {cancel.isError ? (
                <QueryError
                    error={cancel.error}
                    retry={() => {
                        cancel.mutate();
                    }}
                />
            ) : null}
            <details>
                <summary>Persisted exact Specification · read only</summary>
                <pre>{JSON.stringify(run.specification, null, 2)}</pre>
            </details>
        </main>
    );
}

function Fact({ label, value }: { readonly label: string; readonly value: string | null }) {
    return (
        <>
            <dt>{label}</dt>
            <dd>{value ?? "—"}</dd>
        </>
    );
}
