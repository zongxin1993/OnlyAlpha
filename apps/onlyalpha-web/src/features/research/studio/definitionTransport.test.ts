import type { ResearchCalculationCatalogItemTransport } from "../../../api/research/schemas";
import { buildResearchDefinitionTransport, ResearchDraftError } from "./definitionTransport";
import type { CalculationDraft, ExpressionDraft, ResearchDraft } from "./researchDraft";
import { initialResearchDraft } from "./researchDraft";

const parameter = (name: string, type: string, value: number | string) => ({
    name,
    type,
    required: true,
    default: { type: type === "INTEGER" ? ("INTEGER" as const) : ("DECIMAL" as const), value },
    minimum: null,
    maximum: null,
    enum_values: [],
    uppercase: false
});
const port = (name: string, semantic = "FACTOR_VALUE") => ({
    name,
    data_type: "DECIMAL",
    nullable: true,
    semantic_type: semantic,
    dimensions: ["INSTRUMENT", "TIME"],
    unit: null
});
const catalog: readonly ResearchCalculationCatalogItemTransport[] = [
    {
        kind: "INDICATOR",
        type_reference: { kind: "INDICATOR", type_id: "test.rsi", semantic_version: "1" },
        parameters: [parameter("period", "INTEGER", 14)],
        inputs: [],
        outputs: [port("value", "INDICATOR_VALUE")],
        parameter_sweep_allowed: true
    },
    {
        kind: "FACTOR",
        type_reference: { kind: "FACTOR", type_id: "test.factor", semantic_version: "1" },
        parameters: [parameter("weight", "DECIMAL", "0.5")],
        inputs: [port("source", "INDICATOR_VALUE")],
        outputs: [port("score", "FACTOR_SCORE")],
        parameter_sweep_allowed: true
    },
    {
        kind: "TARGET",
        type_reference: { kind: "TARGET", type_id: "test.target", semantic_version: "1" },
        parameters: [parameter("offset", "INTEGER", 5)],
        inputs: [port("price", "PRICE")],
        outputs: [port("target_value", "TARGET_VALUE")],
        parameter_sweep_allowed: false
    }
];

const calc = (
    draftId: number,
    key: string,
    catalogKey: string,
    parameters: CalculationDraft["parameters"],
    publishedOutputs: readonly string[],
    inputBindings: CalculationDraft["inputBindings"] = {}
): CalculationDraft => ({
    draftId,
    catalogKey,
    instanceKey: key,
    parameters,
    publishedOutputs,
    inputBindings
});

const complexExpression: ExpressionDraft = {
    kind: "AND",
    operands: [
        {
            kind: "COMPARISON",
            operator: ">",
            left: { kind: "REFERENCE", reference: "bar.close", dataType: "DECIMAL", valueText: "" },
            right: { kind: "LITERAL", reference: "", dataType: "DECIMAL", valueText: "5.00" }
        },
        {
            kind: "NOT",
            operand: {
                kind: "OR",
                operands: [
                    {
                        kind: "COMPARISON",
                        operator: "<",
                        left: {
                            kind: "REFERENCE",
                            reference: "rsi.value",
                            dataType: "DECIMAL",
                            valueText: ""
                        },
                        right: {
                            kind: "LITERAL",
                            reference: "",
                            dataType: "INTEGER",
                            valueText: "30"
                        }
                    },
                    {
                        kind: "COMPARISON",
                        operator: "==",
                        left: {
                            kind: "LITERAL",
                            reference: "",
                            dataType: "BOOLEAN",
                            valueText: "true"
                        },
                        right: {
                            kind: "LITERAL",
                            reference: "",
                            dataType: "BOOLEAN",
                            valueText: "false"
                        }
                    }
                ]
            }
        }
    ]
};

function admittedDraft(): ResearchDraft {
    const base = initialResearchDraft();
    return {
        ...base,
        dataset: {
            ...base.dataset,
            universeKind: "EXPLICIT_INSTRUMENT_SET",
            instrumentsText: "B.XNAS, A.XNAS",
            start: "2026-01-01T00:00:00Z",
            end: "2026-06-01T00:00:00Z"
        },
        calculations: [
            calc(
                1,
                "rsi",
                "INDICATOR:test.rsi@1",
                { period: { mode: "SWEEP", scalarType: "INTEGER", valuesText: "7, 14" } },
                ["value"]
            ),
            calc(
                2,
                "factor",
                "FACTOR:test.factor@1",
                { weight: { mode: "FIXED", scalarType: "DECIMAL", valuesText: "0.50" } },
                ["score"],
                { source: "rsi.value" }
            )
        ],
        eligibility: complexExpression,
        entry: complexExpression.kind === "AND" ? (complexExpression.operands[0] ?? null) : null,
        exit: complexExpression.kind === "AND" ? (complexExpression.operands[1] ?? null) : null,
        targets: [
            calc(
                3,
                "return_5",
                "TARGET:test.target@1",
                { offset: { mode: "FIXED", scalarType: "INTEGER", valuesText: "5" } },
                ["target_value"],
                { price: "bar.close" }
            )
        ],
        statistics: [
            {
                draftId: 4,
                variable: "factor.score",
                targetInstanceKey: "return_5",
                method: "RANK_IC"
            }
        ]
    };
}

it("builds the complete formal Definition transport without resolving semantics", () => {
    const result = buildResearchDefinitionTransport(admittedDraft(), catalog);
    expect(result.dataset.universe).toEqual({
        kind: "EXPLICIT_INSTRUMENT_SET",
        instrument_ids: ["B.XNAS", "A.XNAS"],
        registered_id: null
    });
    expect(result.calculations[0]?.parameters.period).toEqual({
        kind: "SWEEP",
        values: [
            { type: "INTEGER", value: 7 },
            { type: "INTEGER", value: 14 }
        ]
    });
    expect(result.calculations[1]?.input_bindings[0]?.source).toEqual({
        kind: "VARIABLE",
        instance_key: "rsi",
        output_name: "value"
    });
    expect(result.targets[0]?.input_bindings[0]?.source).toBe("bar.close");
    expect(result.eligibility).toMatchObject({
        kind: "AND",
        operands: [{ kind: "COMPARISON" }, { kind: "NOT", operand: { kind: "OR" } }]
    });
    expect(result.signals.entry).toMatchObject({ kind: "COMPARISON" });
    expect(result.signals.exit).toMatchObject({ kind: "NOT" });
    expect(result.statistics[0]).toMatchObject({
        variable: { kind: "VARIABLE", instance_key: "factor", output_name: "score" },
        target_instance_key: "return_5",
        definition: { method: "RANK_IC" }
    });
    expect(JSON.stringify(result)).not.toContain("fingerprint");
});

it.each([
    ["SINGLE_INSTRUMENT", "A.XNAS", "", ["A.XNAS"], null],
    ["REGISTERED_POOL", "", "pool.alpha", [], "pool.alpha"],
    ["REGISTERED_UNIVERSE", "", "universe.alpha", [], "universe.alpha"]
] as const)(
    "builds %s Universe transport",
    (kind, instrumentsText, registeredId, instrumentIds, expectedRegistered) => {
        const draft = admittedDraft();
        const result = buildResearchDefinitionTransport(
            {
                ...draft,
                dataset: { ...draft.dataset, universeKind: kind, instrumentsText, registeredId }
            },
            catalog
        );
        expect(result.dataset.universe.instrument_ids).toEqual(instrumentIds);
        expect(result.dataset.universe.registered_id).toBe(expectedRegistered);
    }
);

it("fails closed for incomplete and forbidden Target sweep drafts", () => {
    const draft = admittedDraft();
    expect(() => buildResearchDefinitionTransport({ ...draft, calculations: [] }, catalog)).toThrow(
        ResearchDraftError
    );
    const target = draft.targets[0];
    if (target === undefined) throw new Error("Target fixture is missing");
    expect(() =>
        buildResearchDefinitionTransport(
            {
                ...draft,
                targets: [
                    {
                        ...target,
                        parameters: {
                            offset: { mode: "SWEEP", scalarType: "INTEGER", valuesText: "1, 2" }
                        }
                    }
                ]
            },
            catalog
        )
    ).toThrow("Sweep is not admitted");
});
