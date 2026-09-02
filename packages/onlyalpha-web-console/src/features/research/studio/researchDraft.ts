import type {
    ResearchCalculationCatalogItemTransport,
    ResearchScalarTransport
} from "../../../api/research/schemas";

export type UniverseKind =
    "SINGLE_INSTRUMENT" | "EXPLICIT_INSTRUMENT_SET" | "REGISTERED_POOL" | "REGISTERED_UNIVERSE";
export type ScalarType = Exclude<ResearchScalarTransport["type"], "NULL">;

export interface DatasetDraft {
    readonly universeKind: UniverseKind;
    readonly instrumentsText: string;
    readonly registeredId: string;
    readonly start: string;
    readonly end: string;
    readonly step: string;
    readonly aggregation: "TIME" | "TICK" | "VOLUME" | "VALUE";
    readonly priceType: "LAST" | "BID" | "ASK" | "MID" | "MARK";
    readonly aggregationSource: "EXTERNAL" | "INTERNAL";
    readonly adjustmentType: "RAW" | "FORWARD" | "BACKWARD";
    readonly adjustmentReference: string;
}

export interface ParameterDraft {
    readonly mode: "FIXED" | "SWEEP";
    readonly scalarType: ScalarType;
    readonly valuesText: string;
}

export interface CalculationDraft {
    readonly draftId: number;
    readonly catalogKey: string;
    readonly instanceKey: string;
    readonly parameters: Readonly<Record<string, ParameterDraft>>;
    readonly publishedOutputs: readonly string[];
    readonly inputBindings: Readonly<Record<string, string>>;
}

export interface OperandDraft {
    readonly kind: "REFERENCE" | "LITERAL";
    readonly reference: string;
    readonly dataType: ScalarType;
    readonly valueText: string;
}

export type ExpressionDraft =
    | {
          readonly kind: "COMPARISON";
          readonly operator: "==" | "!=" | "<" | "<=" | ">" | ">=";
          readonly left: OperandDraft;
          readonly right: OperandDraft;
      }
    | { readonly kind: "NOT"; readonly operand: ExpressionDraft }
    | { readonly kind: "AND" | "OR"; readonly operands: readonly ExpressionDraft[] };

export interface StatisticsDraft {
    readonly draftId: number;
    readonly variable: string;
    readonly targetInstanceKey: string;
    readonly method: string;
}

export interface ResearchDraft {
    readonly dataset: DatasetDraft;
    readonly calculations: readonly CalculationDraft[];
    readonly eligibility: ExpressionDraft | null;
    readonly entry: ExpressionDraft | null;
    readonly exit: ExpressionDraft | null;
    readonly targets: readonly CalculationDraft[];
    readonly statistics: readonly StatisticsDraft[];
}

export const catalogKey = (item: ResearchCalculationCatalogItemTransport): string =>
    `${item.type_reference.kind}:${item.type_reference.type_id}@${item.type_reference.semantic_version}`;

const scalarText = (value: ResearchScalarTransport): string =>
    value.value === null ? "" : String(value.value);

const parameterScalarType = (value: string): ScalarType => {
    if (value === "INTEGER" || value === "DECIMAL" || value === "BOOLEAN" || value === "STRING")
        return value;
    throw new Error(`Unsupported Calculation parameter type: ${value}`);
};

export function calculationDraftFromCatalog(
    item: ResearchCalculationCatalogItemTransport,
    draftId: number,
    instanceKey: string
): CalculationDraft {
    return {
        draftId,
        catalogKey: catalogKey(item),
        instanceKey,
        parameters: Object.fromEntries(
            item.parameters.map((parameter) => [
                parameter.name,
                {
                    mode: "FIXED",
                    scalarType:
                        parameter.default.type === "NULL"
                            ? parameterScalarType(parameter.type)
                            : parameter.default.type,
                    valuesText: scalarText(parameter.default)
                }
            ])
        ),
        publishedOutputs: item.outputs[0] === undefined ? [] : [item.outputs[0].name],
        inputBindings: Object.fromEntries(item.inputs.map((input) => [input.name, ""]))
    };
}

export const emptyOperand = (reference = "bar.close"): OperandDraft => ({
    kind: "REFERENCE",
    reference,
    dataType: "DECIMAL",
    valueText: ""
});

export const emptyComparison = (reference = "bar.close"): ExpressionDraft => ({
    kind: "COMPARISON",
    operator: ">",
    left: emptyOperand(reference),
    right: { kind: "LITERAL", reference: "", dataType: "DECIMAL", valueText: "0" }
});

export const initialResearchDraft = (): ResearchDraft => ({
    dataset: {
        universeKind: "SINGLE_INSTRUMENT",
        instrumentsText: "",
        registeredId: "",
        start: "",
        end: "",
        step: "1",
        aggregation: "TIME",
        priceType: "LAST",
        aggregationSource: "EXTERNAL",
        adjustmentType: "RAW",
        adjustmentReference: ""
    },
    calculations: [],
    eligibility: null,
    entry: null,
    exit: null,
    targets: [],
    statistics: []
});
