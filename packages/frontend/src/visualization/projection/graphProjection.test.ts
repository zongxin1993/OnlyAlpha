import { parseDecimalText } from "../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseSha256Fingerprint
} from "../../domain/research/identity";
import type { ResearchCandidateGraph } from "../../domain/research/model";
import { escapeDot, graphToDot, projectGraph } from "./graphProjection";

const first = parseSha256Fingerprint("1".repeat(64));
const second = parseSha256Fingerprint("2".repeat(64));
const graph: ResearchCandidateGraph = {
    researchResultFingerprint: parseResearchResultFingerprint("a".repeat(64)),
    candidateFingerprint: parseSha256Fingerprint("b".repeat(64)),
    calculationFingerprint: parseSha256Fingerprint("c".repeat(64)),
    graphFingerprint: parseSha256Fingerprint("d".repeat(64)),
    graph: {
        schemaVersion: 1,
        nodes: [
            {
                nodeFingerprint: second,
                alias: 'decision"node',
                definition: {
                    schemaVersion: 2,
                    kind: "PREDICATE",
                    typeId: "onlyalpha.predicate.comparison",
                    semanticVersion: "1",
                    parameters: { threshold: { type: "DECIMAL", value: parseDecimalText("30") } },
                    inputs: [],
                    inputBindings: {
                        value: { nodeFingerprint: first, outputName: "rsi", source: null }
                    },
                    outputs: [
                        {
                            name: "signal",
                            dataType: "BOOLEAN",
                            nullable: true,
                            dimensions: ["TIME"],
                            semanticType: "ENTRY_SIGNAL",
                            unit: null
                        }
                    ],
                    warmup: {
                        minimumObservations: 1,
                        readyCondition: "READY",
                        preReadyOutput: "NULL",
                        initialization: "NONE"
                    },
                    missingValues: "PROPAGATE",
                    timestamp: "EVENT_TIME",
                    numeric: {
                        representation: "DECIMAL",
                        precision: 38,
                        outputQuantum: null,
                        rounding: "CONTEXT"
                    },
                    factorKind: null,
                    extensions: {}
                }
            },
            {
                nodeFingerprint: first,
                alias: "rsi",
                definition: {
                    schemaVersion: 2,
                    kind: "INDICATOR",
                    typeId: "onlyalpha.indicator.rsi",
                    semanticVersion: "1",
                    parameters: {},
                    inputs: [],
                    inputBindings: {},
                    outputs: [
                        {
                            name: "rsi",
                            dataType: "DECIMAL",
                            nullable: true,
                            dimensions: ["TIME"],
                            semanticType: "INDICATOR_VALUE",
                            unit: null
                        }
                    ],
                    warmup: {
                        minimumObservations: 14,
                        readyCondition: "READY",
                        preReadyOutput: "NULL",
                        initialization: "WINDOW"
                    },
                    missingValues: "PROPAGATE",
                    timestamp: "EVENT_TIME",
                    numeric: {
                        representation: "DECIMAL",
                        precision: 38,
                        outputQuantum: null,
                        rounding: "CONTEXT"
                    },
                    factorKind: null,
                    extensions: {}
                }
            }
        ]
    }
};

it("uses exact stable node identities and deterministic edges", () => {
    const firstProjection = projectGraph(graph, "EXACT");
    const secondProjection = projectGraph(graph, "EXACT");
    expect(firstProjection).toEqual(secondProjection);
    expect(firstProjection.nodes.map((node) => node.id)).toEqual([first, second]);
    expect(firstProjection.edges).toEqual([{ from: first, to: second, label: "rsi → value" }]);
});

it("escapes DOT without treating it as graph truth", () => {
    expect(escapeDot('a"b\\c\nd')).toBe('a\\"b\\\\c\\nd');
    const dot = graphToDot(projectGraph(graph, "SEMANTIC"));
    expect(dot).toContain(`"${first}" -> "${second}"`);
    expect(dot).toContain('decision\\"node');
});

it("projects reused external sources once without mutating exact Graph authority", () => {
    const source = { nodeFingerprint: null, outputName: "close", source: "bar.close" } as const;
    const withSources: ResearchCandidateGraph = {
        ...graph,
        graph: {
            ...graph.graph,
            nodes: graph.graph.nodes.map((node) => ({
                ...node,
                definition: {
                    ...node.definition,
                    inputs: [
                        ...node.definition.inputs,
                        {
                            name: "close",
                            dataType: "DECIMAL" as const,
                            nullable: false,
                            dimensions: ["TIME"],
                            semanticType: "MARKET_PRICE",
                            unit: null
                        }
                    ],
                    inputBindings: { ...node.definition.inputBindings, close: source }
                }
            }))
        }
    };
    const before = JSON.stringify(withSources);
    const projected = projectGraph(withSources, "EXACT");
    expect(projected.nodes.filter((node) => node.presentationKind === "EXTERNAL_SOURCE")).toEqual([
        expect.objectContaining({ id: "external-source:bar.close", label: "bar.close" })
    ]);
    expect(projected.edges.filter((edge) => edge.from === "external-source:bar.close")).toEqual([
        { from: "external-source:bar.close", to: first, label: "bar.close → close" },
        { from: "external-source:bar.close", to: second, label: "bar.close → close" }
    ]);
    expect(JSON.stringify(withSources)).toBe(before);
});
