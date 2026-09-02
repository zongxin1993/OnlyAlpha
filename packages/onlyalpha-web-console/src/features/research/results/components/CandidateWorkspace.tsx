import { useResultWorkspace } from "../ResultWorkspaceContext";
import { CandidateComparison } from "./CandidateComparison";

function assignmentText(value: boolean | number | string | null): string {
    return value === null ? "NULL" : typeof value === "string" ? value : String(value);
}

export function CandidateWorkspace() {
    const { candidates, selection, dispatch, scientificUnavailable } = useResultWorkspace();
    if (scientificUnavailable)
        return (
            <p className="warning">
                Scientific Candidate evidence is unavailable for this Artifact profile.
            </p>
        );
    if (candidates === null) return <p role="status">Loading Candidate catalog…</p>;
    if (candidates.candidates.length === 0)
        return <p>No Candidates are members of this Artifact.</p>;
    const dimensions = [
        ...new Set(candidates.candidates.flatMap((candidate) => Object.keys(candidate.assignment)))
    ].sort();
    return (
        <section aria-labelledby="candidate-heading">
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Exact Result membership</p>
                    <h2 id="candidate-heading">Candidates</h2>
                </div>
                <span>{dimensions.length} parameter dimensions</span>
            </div>
            <p className="muted">
                Comparison values, when available, use one explicitly selected exact Statistics
                timestamp—never a browser aggregate.
            </p>
            <div className="table-scroll">
                <table>
                    <thead>
                        <tr>
                            <th>Select</th>
                            {dimensions.map((dimension) => (
                                <th key={dimension}>{dimension}</th>
                            ))}
                            <th>Statistics</th>
                            <th>Exact identity</th>
                        </tr>
                    </thead>
                    <tbody>
                        {candidates.candidates.map((candidate) => (
                            <tr
                                key={candidate.candidateFingerprint}
                                className={
                                    candidate.candidateFingerprint ===
                                    selection.candidateFingerprint
                                        ? "selected-row"
                                        : undefined
                                }
                            >
                                <td>
                                    <button
                                        type="button"
                                        className="quiet-button"
                                        aria-pressed={
                                            candidate.candidateFingerprint ===
                                            selection.candidateFingerprint
                                        }
                                        onClick={() => {
                                            dispatch({
                                                type: "CANDIDATE",
                                                value: candidate.candidateFingerprint
                                            });
                                        }}
                                    >
                                        Select
                                    </button>
                                </td>
                                {dimensions.map((dimension) => (
                                    <td key={dimension}>
                                        {assignmentText(candidate.assignment[dimension] ?? null)}
                                    </td>
                                ))}
                                <td>{candidate.statisticsFingerprints.length}</td>
                                <td>
                                    <details>
                                        <summary>Inspect</summary>
                                        <code>{candidate.candidateFingerprint}</code>
                                        <code>{candidate.calculationFingerprint}</code>
                                        <code>{candidate.graphFingerprint}</code>
                                        {candidate.statisticsFingerprints.map((fingerprint) => (
                                            <code key={fingerprint}>{fingerprint}</code>
                                        ))}
                                    </details>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <CandidateComparison candidates={candidates.candidates} />
        </section>
    );
}
