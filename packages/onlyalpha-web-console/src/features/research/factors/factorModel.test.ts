import type { ResearchCalculationCatalogItemTransport } from "../../../api/research/schemas";
import { parseDecimalText } from "../../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseSha256Fingerprint,
    parseStatisticsFingerprint
} from "../../../domain/research/identity";
import type {
    ResearchCandidate,
    ResearchCandidateGraph,
    ResearchGraphNode,
    ResearchPublishedSeries,
    ResearchPublishedSeriesCatalog,
    ResearchStatisticsCatalog,
    ResearchStatisticsDescriptor
} from "../../../domain/research/model";
import { publishedSeriesKey } from "../results/model/selectors";
import {
    admittedFactorSeries,
    factorCatalogItems,
    parseFactorDateRange,
    statisticsForFactor
} from "./factorModel";

const result = parseResearchResultFingerprint("a".repeat(64));
const otherResult = parseResearchResultFingerprint("b".repeat(64));
const candidateId = parseSha256Fingerprint("c".repeat(64));
const calculationId = parseSha256Fingerprint("d".repeat(64));
const nodeId = parseSha256Fingerprint("e".repeat(64));
const graphId = parseSha256Fingerprint("f".repeat(64));
const otherId = parseSha256Fingerprint("1".repeat(64));
const statisticId = parseStatisticsFingerprint("2".repeat(64));

const candidate: ResearchCandidate = {
    candidateFingerprint: candidateId,
    candidateCalculationId: "research.factor",
    calculationFingerprint: calculationId,
    graphFingerprint: graphId,
    assignment: {},
    assignmentTypes: {},
    statisticsFingerprints: [statisticId],
    signalRoles: []
};
const factorNode: ResearchGraphNode = {
    nodeFingerprint: nodeId,
    alias: "Momentum",
    definition: {
        schemaVersion: 2,
        kind: "FACTOR",
        typeId: "example.momentum",
        semanticVersion: "1.2.0",
        parameters: {},
        inputs: [],
        inputBindings: {},
        outputs: [
            {
                name: "score",
                dataType: "DECIMAL",
                semanticType: "FACTOR_SCORE",
                nullable: true,
                dimensions: ["INSTRUMENT", "TIME"],
                unit: null
            }
        ],
        warmup: {
            minimumObservations: 2,
            readyCondition: "READY",
            preReadyOutput: "NULL",
            initialization: "FIRST_OBSERVATION"
        },
        missingValues: "PROPAGATE",
        timestamp: "OBSERVATION_TIME",
        numeric: {
            representation: "DECIMAL",
            precision: 28,
            outputQuantum: parseDecimalText("0.0001"),
            rounding: "ROUND_HALF_EVEN"
        },
        factorKind: "TIME_SERIES",
        extensions: {}
    }
};
const graph: ResearchCandidateGraph = {
    researchResultFingerprint: result,
    candidateFingerprint: candidateId,
    calculationFingerprint: calculationId,
    graphFingerprint: graphId,
    graph: { schemaVersion: 1, nodes: [factorNode] }
};
const series: ResearchPublishedSeries = {
    candidateFingerprint: candidateId,
    calculationFingerprint: calculationId,
    nodeFingerprint: nodeId,
    outputName: "score",
    valueKind: "DECIMAL"
};
const published: ResearchPublishedSeriesCatalog = {
    researchResultFingerprint: result,
    series: [series]
};
const descriptor: ResearchStatisticsDescriptor = {
    statisticsFingerprint: statisticId,
    statisticsResultFingerprint: "3".repeat(64),
    resultContentFingerprint: "4".repeat(64),
    statisticsResultSchemaVersion: 1,
    rowCount: 12,
    feature: {
        calculationFingerprint: calculationId,
        nodeFingerprint: nodeId,
        outputName: "score"
    },
    target: {
        calculationFingerprint: calculationId,
        nodeFingerprint: otherId,
        outputName: "forward_return"
    },
    definition: {
        method: "SPEARMAN_RANK_IC",
        minimumObservations: 3,
        pairingPolicy: "EXACT",
        universePolicy: "ORIGINAL_RESEARCH_UNIVERSE",
        rankTieMethod: "AVERAGE",
        weighting: "EQUAL",
        numeric: {
            representation: "DECIMAL",
            precision: 28,
            outputQuantum: parseDecimalText("0.0001"),
            rounding: "ROUND_HALF_EVEN"
        }
    }
};
const statistics: ResearchStatisticsCatalog = {
    researchResultFingerprint: result,
    statistics: [descriptor]
};

function catalogItem(
    kind: "FACTOR" | "INDICATOR" = "FACTOR",
    version = "1.2.0"
): ResearchCalculationCatalogItemTransport {
    return {
        kind,
        type_reference: { kind, type_id: "example.momentum", semantic_version: version },
        inputs: [],
        outputs: [
            {
                name: "score",
                data_type: "DECIMAL",
                semantic_type: "FACTOR_SCORE",
                nullable: true,
                dimensions: ["INSTRUMENT", "TIME"],
                unit: null
            }
        ],
        parameters: [],
        parameter_sweep_allowed: true
    };
}

function withNode(node: ResearchGraphNode): ResearchCandidateGraph {
    return { ...graph, graph: { ...graph.graph, nodes: [node] } };
}

function selectedOption() {
    const option = admittedFactorSeries(result, candidate, graph, published)[0];
    if (option === undefined) throw new Error("Fixture Factor Series was not admitted");
    return option;
}

describe("Factor catalog presentation", () => {
    it("uses the formal Factor kind and preserves each exact version and original object", () => {
        const first = catalogItem();
        const second = catalogItem("FACTOR", "2.0.0");
        const indicator = { ...catalogItem("INDICATOR"), kind: "FACTOR" };
        const items = Object.freeze([first, indicator, second]);
        expect(factorCatalogItems(items, "")).toEqual([first, second]);
        expect(factorCatalogItems(items, "MOMENTUM 2.0.0 SCORE")).toEqual([second]);
        expect(factorCatalogItems(items, "example.momentum@1.2.0")).toEqual([first]);
        expect(factorCatalogItems(items, "factor_score")[0]).toBe(first);
        expect(items).toEqual([first, indicator, second]);
    });

    it("treats search characters literally instead of as regular expressions", () => {
        expect(factorCatalogItems([catalogItem()], ".*")).toEqual([]);
        expect(factorCatalogItems([catalogItem()], "[")).toEqual([]);
        expect(factorCatalogItems([catalogItem()], "  ExAmPlE.MoMeNtUm  ")).toHaveLength(1);
    });
});

describe("Factor Series evidence admission", () => {
    it("retains exact published identity and graph version without recalculation", () => {
        const option = selectedOption();
        expect(option.key).toBe(publishedSeriesKey(series));
        expect(option.series).toBe(series);
        expect(option.node).toBe(factorNode);
        expect(option.label).toBe("Momentum · example.momentum@1.2.0 · score");
    });

    it.each([
        ["Result", { researchResultFingerprint: otherResult }],
        ["Candidate", { candidateFingerprint: otherId }],
        ["Calculation version", { calculationFingerprint: otherId }],
        ["Graph", { graphFingerprint: otherId }]
    ])("rejects a graph from another %s", (_name, mismatch) => {
        expect(() =>
            admittedFactorSeries(result, candidate, { ...graph, ...mismatch }, published)
        ).toThrow("CONTRACT_ERROR");
    });

    it("rejects a Published Series catalog from another Result", () => {
        expect(() =>
            admittedFactorSeries(result, candidate, graph, {
                ...published,
                researchResultFingerprint: otherResult
            })
        ).toThrow("different Result");
    });

    it("rejects a selected Candidate series from a different exact calculation", () => {
        expect(() =>
            admittedFactorSeries(result, candidate, graph, {
                ...published,
                series: [{ ...series, calculationFingerprint: otherId }]
            })
        ).toThrow("Candidate calculation");
    });

    it("admits a global series only for the exact Candidate calculation and ignores other Candidates", () => {
        const global = { ...series, candidateFingerprint: null };
        const options = admittedFactorSeries(result, candidate, graph, {
            ...published,
            series: [
                { ...series, candidateFingerprint: otherId },
                { ...global, calculationFingerprint: otherId },
                global
            ]
        });
        expect(options.map((option) => option.series)).toEqual([global]);
        expect(options[0]?.key).toBe(publishedSeriesKey(global));
    });

    it("never calls an Indicator a Factor even when output names and semantics match", () => {
        const indicator: ResearchGraphNode = {
            ...factorNode,
            definition: { ...factorNode.definition, kind: "INDICATOR" }
        };
        expect(admittedFactorSeries(result, candidate, withNode(indicator), published)).toEqual([]);
    });

    it.each([
        ["unknown node", { nodeFingerprint: otherId }],
        ["unknown output", { outputName: "another_score" }],
        ["wrong value kind", { valueKind: "INTEGER" as const }]
    ])("rejects %s instead of finding a similar output", (_name, mismatch) => {
        expect(() =>
            admittedFactorSeries(result, candidate, graph, {
                ...published,
                series: [{ ...series, ...mismatch }]
            })
        ).toThrow("CONTRACT_ERROR");
    });

    it.each(["BOOLEAN", "STRING"] as const)("rejects nonnumeric %s Factor outputs", (dataType) => {
        const node: ResearchGraphNode = {
            ...factorNode,
            definition: {
                ...factorNode.definition,
                outputs: factorNode.definition.outputs.map((output) => ({ ...output, dataType }))
            }
        };
        expect(() =>
            admittedFactorSeries(result, candidate, withNode(node), {
                ...published,
                series: [{ ...series, valueKind: dataType }]
            })
        ).toThrow("numeric data type");
    });

    it("admits integer Factor values but omits non-Factor semantic outputs", () => {
        const node: ResearchGraphNode = {
            ...factorNode,
            alias: null,
            definition: {
                ...factorNode.definition,
                outputs: factorNode.definition.outputs.map((output) => ({
                    ...output,
                    dataType: "INTEGER",
                    semanticType: "FACTOR_VALUE"
                }))
            }
        };
        expect(
            admittedFactorSeries(result, candidate, withNode(node), {
                ...published,
                series: [{ ...series, valueKind: "INTEGER" }]
            })[0]?.label
        ).toBe("example.momentum@1.2.0 · score");
        const diagnostic: ResearchGraphNode = {
            ...factorNode,
            definition: {
                ...factorNode.definition,
                outputs: factorNode.definition.outputs.map((output) => ({
                    ...output,
                    semanticType: "DIAGNOSTIC"
                }))
            }
        };
        expect(admittedFactorSeries(result, candidate, withNode(diagnostic), published)).toEqual(
            []
        );
    });

    it("rejects ambiguous node and Published Series identities", () => {
        expect(() =>
            admittedFactorSeries(
                result,
                candidate,
                {
                    ...graph,
                    graph: { ...graph.graph, nodes: [factorNode, factorNode] }
                },
                published
            )
        ).toThrow("duplicate node");
        expect(() =>
            admittedFactorSeries(result, candidate, graph, {
                ...published,
                series: [series, series]
            })
        ).toThrow("identity is duplicated");
    });
});

describe("Factor Statistics membership", () => {
    it("keeps the original authoritative method, Target, and population definition", () => {
        const output = statisticsForFactor(result, candidate, selectedOption(), statistics);
        expect(output).toEqual([descriptor]);
        expect(output[0]).toBe(descriptor);
        expect(output[0]?.definition.universePolicy).toBe("ORIGINAL_RESEARCH_UNIVERSE");
    });

    it("requires Candidate membership as well as the exact Feature reference", () => {
        expect(
            statisticsForFactor(
                result,
                { ...candidate, statisticsFingerprints: [] },
                selectedOption(),
                statistics
            )
        ).toEqual([]);
        for (const feature of [
            { ...descriptor.feature, calculationFingerprint: otherId },
            { ...descriptor.feature, nodeFingerprint: otherId },
            { ...descriptor.feature, outputName: "another_score" }
        ]) {
            expect(
                statisticsForFactor(result, candidate, selectedOption(), {
                    ...statistics,
                    statistics: [{ ...descriptor, feature }]
                })
            ).toEqual([]);
        }
    });

    it("rejects foreign Result and Candidate context instead of relabeling its Statistics", () => {
        expect(() =>
            statisticsForFactor(result, candidate, selectedOption(), {
                ...statistics,
                researchResultFingerprint: otherResult
            })
        ).toThrow("different Research Result");
        expect(() =>
            statisticsForFactor(
                result,
                {
                    ...candidate,
                    candidateFingerprint: otherId
                },
                selectedOption(),
                statistics
            )
        ).toThrow("exact Candidate");
    });
});

describe("Factor UTC date range", () => {
    it("uses exact UTC midnights and an exclusive end, including leap days", () => {
        expect(parseFactorDateRange("2024-02-29", "2024-03-01")).toEqual({
            from: 1709164800000000000n,
            to: 1709251200000000000n
        });
        expect(parseFactorDateRange("1969-12-31", "1970-01-01")).toEqual({
            from: -86400000000000n,
            to: 0n
        });
    });

    it("allows either unbounded side without reading the current clock", () => {
        expect(parseFactorDateRange("", "")).toEqual({});
        expect(parseFactorDateRange("1970-01-01", "")).toEqual({ from: 0n });
        expect(parseFactorDateRange("", "1970-01-01")).toEqual({ to: 0n });
    });

    it.each([
        "2023-02-29",
        "2024-02-30",
        "2024-13-01",
        "2024-00-01",
        "2024-01-00",
        "0000-01-01",
        "2024-2-01",
        " 2024-02-01",
        "2024-02-01 ",
        "2024-02-01T00:00:00Z",
        "not-a-date"
    ])("rejects invalid or noncanonical date %s on either side", (date) => {
        expect(() => parseFactorDateRange(date, "")).toThrow("INVALID_TIME_RANGE");
        expect(() => parseFactorDateRange("", date)).toThrow("INVALID_TIME_RANGE");
    });

    it.each([
        ["2024-02-29", "2024-02-29"],
        ["2024-03-01", "2024-02-29"]
    ])("rejects empty or reversed [%s, %s)", (from, to) => {
        expect(() => parseFactorDateRange(from, to)).toThrow("exclusive end");
    });
});
