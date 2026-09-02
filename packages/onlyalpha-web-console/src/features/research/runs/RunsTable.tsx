import { Link } from "react-router-dom";
import type { ResearchRunSummary } from "../../../domain/research/model";
import { RunStateBadge } from "./RunStateBadge";

const duration = (run: ResearchRunSummary): string => {
    if (run.startedAt === null || run.finishedAt === null) return "—";
    const milliseconds = Date.parse(run.finishedAt) - Date.parse(run.startedAt);
    return Number.isFinite(milliseconds) && milliseconds >= 0
        ? `${(milliseconds / 1000).toFixed(1)}s`
        : "—";
};

export function RunsTable({ runs }: { readonly runs: readonly ResearchRunSummary[] }) {
    return (
        <div className="table-scroll">
            <table className="runs-table">
                <thead>
                    <tr>
                        <th>State</th>
                        <th>Queued</th>
                        <th>Duration</th>
                        <th>Specification</th>
                        <th>Result</th>
                        <th>Run</th>
                    </tr>
                </thead>
                <tbody>
                    {runs.map((run) => (
                        <tr key={run.runId}>
                            <td>
                                <RunStateBadge state={run.state} />
                            </td>
                            <td>{run.queuedAt}</td>
                            <td>{duration(run)}</td>
                            <td>
                                <code>{run.specificationFingerprint}</code>
                            </td>
                            <td>
                                {run.resultRef === null ? (
                                    "—"
                                ) : (
                                    <Link to={`/research/results/${run.resultRef}`}>Open</Link>
                                )}
                            </td>
                            <td>
                                <Link to={`/research/runs/${run.runId}`}>{run.runId}</Link>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
