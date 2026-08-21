import type { ResearchCandidateGraph } from "../../domain/research/model";
import type {
    GraphPresentation,
    GraphPresentationEdge,
    GraphPresentationNode
} from "../model/graph";

export type GraphMode = "SEMANTIC" | "EXACT";

export function projectGraph(value: ResearchCandidateGraph, mode: GraphMode): GraphPresentation {
    const nodes: GraphPresentationNode[] = value.graph.nodes.map((node) => ({
        id: node.nodeFingerprint,
        label:
            mode === "SEMANTIC"
                ? `${node.alias ?? node.definition.typeId}\n${node.definition.kind}`
                : `${node.alias ?? node.definition.typeId}\n${node.nodeFingerprint}`,
        kind: node.definition.kind,
        typeId: node.definition.typeId,
        semanticVersion: node.definition.semanticVersion,
        parameters: node.definition.parameters,
        inputs: node.definition.inputs.map((port) => port.name),
        outputs: node.definition.outputs.map((port) => port.name)
    }));
    const edges: GraphPresentationEdge[] = [];
    for (const node of value.graph.nodes) {
        for (const [inputName, reference] of Object.entries(node.definition.inputBindings).sort(
            ([left], [right]) => left.localeCompare(right)
        )) {
            if (reference.nodeFingerprint !== null)
                edges.push({
                    from: reference.nodeFingerprint,
                    to: node.nodeFingerprint,
                    label: `${reference.outputName} → ${inputName}`
                });
        }
    }
    return {
        nodes: nodes.sort((left, right) => left.id.localeCompare(right.id)),
        edges: edges.sort((left, right) =>
            `${left.from}:${left.to}:${left.label}`.localeCompare(
                `${right.from}:${right.to}:${right.label}`
            )
        )
    };
}

export function escapeDot(value: string): string {
    return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"').replaceAll("\n", "\\n");
}

export function graphToDot(value: GraphPresentation): string {
    const lines = ["digraph OnlyAlpha {", '  graph [bgcolor="transparent", rankdir="LR"];'];
    for (const node of value.nodes)
        lines.push(
            `  "${escapeDot(node.id)}" [label="${escapeDot(node.label)}", shape="box", class="onlyalpha-node"];`
        );
    for (const edge of value.edges)
        lines.push(
            `  "${escapeDot(edge.from)}" -> "${escapeDot(edge.to)}" [label="${escapeDot(edge.label)}"];`
        );
    lines.push("}");
    return lines.join("\n");
}
