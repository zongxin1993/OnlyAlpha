import type { ResearchDefinitionResolutionTransport } from "../../../api/research/schemas";

export type ResolutionState =
    | { readonly status: "UNRESOLVED" }
    | { readonly status: "RESOLVING"; readonly revision: number }
    | {
          readonly status: "INVALID";
          readonly code: string;
          readonly detail: string;
          readonly path?: string;
      }
    | {
          readonly status: "RESOLVED";
          readonly revision: number;
          readonly value: ResearchDefinitionResolutionTransport;
      };

export function ResearchInspector({ state }: { readonly state: ResolutionState }) {
    return (
        <aside className="context-inspector" aria-label="Resolution inspector">
            <div className="inspector-heading">
                <p className="eyebrow">Authority inspector</p>
                <span className={`resolution-state ${state.status.toLowerCase()}`}>
                    {state.status}
                </span>
            </div>
            {state.status === "UNRESOLVED" ? (
                <p className="muted">
                    Resolve the current Definition to obtain authoritative identities and the exact
                    Specification.
                </p>
            ) : state.status === "RESOLVING" ? (
                <p role="status">Resolving Definition revision {state.revision}…</p>
            ) : state.status === "INVALID" ? (
                <div className="error" role="alert">
                    <strong>{state.code}</strong>
                    {state.path === undefined ? null : <code>{state.path}</code>}
                    <span>{state.detail}</span>
                </div>
            ) : (
                <>
                    <dl className="inspector-facts">
                        <dt>Authoring Definition</dt>
                        <dd>{state.value.authoring_definition_fingerprint}</dd>
                        <dt>Resolved Definition</dt>
                        <dd>{state.value.resolved_definition_fingerprint}</dd>
                        <dt>Dataset Snapshot</dt>
                        <dd>{state.value.dataset_snapshot_fingerprint}</dd>
                        <dt>Instruments</dt>
                        <dd>{state.value.instrument_count}</dd>
                        <dt>Candidates</dt>
                        <dd>{state.value.candidate_count}</dd>
                        <dt>Specification</dt>
                        <dd>{state.value.specification_fingerprint}</dd>
                    </dl>
                    <section>
                        <h3>Published variables</h3>
                        <ul className="plain-list">
                            {state.value.published_variables.map((item) => (
                                <li key={`${item.instance_key}.${item.output_name}`}>
                                    <code>
                                        {item.instance_key}.{item.output_name}
                                    </code>
                                    <span>{item.semantic_type}</span>
                                </li>
                            ))}
                        </ul>
                    </section>
                    <details>
                        <summary>Exact Specification · read only</summary>
                        <pre>{JSON.stringify(state.value.exact_specification, null, 2)}</pre>
                    </details>
                </>
            )}
        </aside>
    );
}
