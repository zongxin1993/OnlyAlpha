import type { ResearchCandidateGraph } from "../../domain/research/model";
import type {
    GraphPresentation,
    GraphPresentationEdge,
    GraphPresentationNode
} from "../model/graph";

export type GraphMode = "SEMANTIC" | "EXACT";

const compareText = (left: string, right: string): number =>
    left < right ? -1 : left > right ? 1 : 0;

export function projectGraph(value: ResearchCandidateGraph, mode: GraphMode): GraphPresentation {
    const nodes: GraphPresentationNode[] = value.graph.nodes.map((node) => ({
        id: node.nodeFingerprint,
        label:
            mode === "SEMANTIC"
                ? `${node.alias ?? node.definition.typeId}\n${node.definition.kind}`
                : `${node.alias ?? node.definition.typeId}\n${node.nodeFingerprint}`,
        presentationKind: "CALCULATION",
        kind: node.definition.kind,
        typeId: node.definition.typeId,
        semanticVersion: node.definition.semanticVersion,
        parameters: node.definition.parameters,
        inputs: node.definition.inputs.map((port) => port.name),
        outputs: node.definition.outputs.map((port) => port.name)
    }));
    const edges: GraphPresentationEdge[] = [];
    const externalSources = new Map<string, GraphPresentationNode>();
    for (const node of value.graph.nodes) {
        for (const [inputName, reference] of Object.entries(node.definition.inputBindings).sort(
            ([left], [right]) => compareText(left, right)
        )) {
            if (reference.nodeFingerprint !== null)
                edges.push({
                    from: reference.nodeFingerprint,
                    to: node.nodeFingerprint,
                    label: `${reference.outputName} → ${inputName}`
                });
            else if (reference.source !== null) {
                const id = `external-source:${reference.source}`;
                if (!externalSources.has(id))
                    externalSources.set(id, {
                        id,
                        label: reference.source,
                        presentationKind: "EXTERNAL_SOURCE",
                        kind: "EXTERNAL_SOURCE",
                        typeId: "external.dataset.source",
                        semanticVersion: "presentation-only",
                        parameters: {},
                        inputs: [],
                        outputs: [reference.source]
                    });
                edges.push({
                    from: id,
                    to: node.nodeFingerprint,
                    label: `${reference.source} → ${inputName}`
                });
            }
        }
    }
    nodes.push(...externalSources.values());
    return {
        nodes: nodes.sort((left, right) => compareText(left.id, right.id)),
        edges: edges.sort((left, right) =>
            compareText(
                `${left.from}:${left.to}:${left.label}`,
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
