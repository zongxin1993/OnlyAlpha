import type { ResearchGraphScalar } from "../../domain/research/model";

export interface GraphPresentationNode {
    readonly id: string;
    readonly label: string;
    readonly kind: string;
    readonly typeId: string;
    readonly semanticVersion: string;
    readonly parameters: Readonly<Record<string, ResearchGraphScalar>>;
    readonly inputs: readonly string[];
    readonly outputs: readonly string[];
}

export interface GraphPresentationEdge {
    readonly from: string;
    readonly to: string;
    readonly label: string;
}

export interface GraphPresentation {
    readonly nodes: readonly GraphPresentationNode[];
    readonly edges: readonly GraphPresentationEdge[];
}
