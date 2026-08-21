import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useResearchApi } from "../../../../app/providers";
import { QueryError } from "../../../../shared/components/QueryState";
import { GraphvizInspectorView } from "../../../../visualization/graph/graphviz/GraphvizInspectorView";
import { graphToDot, projectGraph } from "../../../../visualization/projection/graphProjection";
import { graphOptions } from "../../queries";
import { useResultWorkspace } from "../ResultWorkspaceContext";

export function GraphInspector() {
    const { summary, candidates, selection, dispatch, scientificUnavailable } =
        useResultWorkspace();
    const client = useResearchApi();
    const candidate = candidates?.candidates.find(
        (item) => item.candidateFingerprint === selection.candidateFingerprint
    );
    if (scientificUnavailable)
        return (
            <p className="warning">
                Exact Graph evidence is unavailable for this Artifact profile.
            </p>
        );
    if (candidate === undefined) return <p role="status">Loading exact Graph selector…</p>;
    return (
        <SelectedGraphInspector
            result={summary.researchResultFingerprint}
            candidate={candidate}
            mode={selection.graphMode}
            setMode={(value) => {
                dispatch({ type: "GRAPH_MODE", value });
            }}
            client={client}
        />
    );
}

function SelectedGraphInspector({
    result,
    candidate,
    mode,
    setMode,
    client
}: {
    readonly result: ReturnType<typeof useResultWorkspace>["summary"]["researchResultFingerprint"];
    readonly candidate: NonNullable<
        ReturnType<typeof useResultWorkspace>["candidates"]
    >["candidates"][number];
    readonly mode: "SEMANTIC" | "EXACT";
    readonly setMode: (value: "SEMANTIC" | "EXACT") => void;
    readonly client: ReturnType<typeof useResearchApi>;
}) {
    const graph = useQuery(graphOptions(client, result, candidate.candidateFingerprint));
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const onSelectNode = useCallback((nodeId: string) => {
        setSelectedNodeId(nodeId);
    }, []);
    const projection = useMemo(
        () => (graph.data === undefined ? null : projectGraph(graph.data, mode)),
        [graph.data, mode]
    );
    const dot = useMemo(() => (projection === null ? null : graphToDot(projection)), [projection]);
    if (graph.isPending) return <p role="status">Loading exact Candidate Graph…</p>;
    if (graph.isError) return <QueryError error={graph.error} retry={() => void graph.refetch()} />;
    if (
        graph.data.candidateFingerprint !== candidate.candidateFingerprint ||
        graph.data.calculationFingerprint !== candidate.calculationFingerprint ||
        graph.data.graphFingerprint !== candidate.graphFingerprint
    )
        return (
            <p className="error" role="alert">
                CONTRACT_ERROR: Candidate and Graph linkage mismatch
            </p>
        );
    if (projection === null || dot === null) return null;
    const selected =
        projection.nodes.find((node) => node.id === selectedNodeId) ?? projection.nodes[0];
    return (
        <section aria-labelledby="graph-inspector-heading">
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Read-only exact authority projection</p>
                    <h2 id="graph-inspector-heading">Graph Inspector</h2>
                </div>
                <div className="segmented-control" aria-label="Graph mode">
                    {(["SEMANTIC", "EXACT"] as const).map((value) => (
                        <button
                            key={value}
                            type="button"
                            aria-pressed={mode === value}
                            onClick={() => {
                                setMode(value);
                            }}
                        >
                            {value === "SEMANTIC" ? "Semantic Graph" : "Exact Graph"}
                        </button>
                    ))}
                </div>
            </div>
            <p className="muted">
                Graphviz layout and SVG are presentation-only. This inspector cannot edit or submit
                graph semantics.
            </p>
            <div className="graph-inspector-layout">
                <GraphvizInspectorView dot={dot} onSelectNode={onSelectNode} />
                <aside className="node-inspector" aria-label="Selected exact node inspector">
                    {selected === undefined ? (
                        <p>Graph has no nodes.</p>
                    ) : (
                        <>
                            <p className="eyebrow">Selected node</p>
                            <h3>{selected.label.split("\n")[0]}</h3>
                            <dl className="facts">
                                <dt>Node fingerprint</dt>
                                <dd>{selected.id}</dd>
                                <dt>Type</dt>
                                <dd>
                                    {selected.typeId}@{selected.semanticVersion}
                                </dd>
                                <dt>Kind</dt>
                                <dd>{selected.kind}</dd>
                                <dt>Inputs</dt>
                                <dd>{selected.inputs.join(", ") || "None"}</dd>
                                <dt>Outputs</dt>
                                <dd>{selected.outputs.join(", ")}</dd>
                                <dt>Parameters</dt>
                                <dd>
                                    <pre>{JSON.stringify(selected.parameters, null, 2)}</pre>
                                </dd>
                            </dl>
                        </>
                    )}
                </aside>
            </div>
            <details className="identity-inspector">
                <summary>Inspect Graph identities</summary>
                <code>{graph.data.graphFingerprint}</code>
                <code>{graph.data.calculationFingerprint}</code>
                <code>{graph.data.candidateFingerprint}</code>
            </details>
        </section>
    );
}
