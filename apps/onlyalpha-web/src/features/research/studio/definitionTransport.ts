import type {
    ResearchCalculationCatalogItemTransport,
    ResearchCalculationInstanceTransport,
    ResearchDefinitionTransport,
    ResearchExpressionTransport,
    ResearchScalarTransport
} from "../../../api/research/schemas";
import type {
    CalculationDraft,
    ExpressionDraft,
    OperandDraft,
    ResearchDraft,
    ScalarType
} from "./researchDraft";
import { catalogKey } from "./researchDraft";

export class ResearchDraftError extends Error {
    constructor(
        readonly path: string,
        message: string
    ) {
        super(message);
        this.name = "ResearchDraftError";
    }
}

const required = (value: string, path: string): string => {
    const result = value.trim();
    if (result.length === 0) throw new ResearchDraftError(path, "Value is required");
    return result;
};

const positiveInteger = (value: string, path: string): number => {
    const admitted = required(value, path);
    if (!/^[1-9][0-9]*$/.test(admitted))
        throw new ResearchDraftError(path, "Value must be a positive integer");
    const result = Number(admitted);
    if (!Number.isSafeInteger(result))
        throw new ResearchDraftError(path, "Integer exceeds the exact browser range");
    return result;
};

export function parseScalar(type: ScalarType, text: string, path: string): ResearchScalarTransport {
    const value = required(text, path);
    if (type === "BOOLEAN") {
        if (value !== "true" && value !== "false")
            throw new ResearchDraftError(path, "Boolean must be true or false");
        return { type, value: value === "true" };
    }
    if (type === "INTEGER") {
        if (!/^-?(?:0|[1-9][0-9]*)$/.test(value))
            throw new ResearchDraftError(path, "Integer is invalid");
        const integer = Number(value);
        if (!Number.isSafeInteger(integer))
            throw new ResearchDraftError(path, "Integer exceeds the exact browser range");
        return { type, value: integer };
    }
    if (type === "DECIMAL") {
        if (!/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value))
            throw new ResearchDraftError(path, "Decimal is invalid");
        return { type, value };
    }
    return { type, value };
}

function reference(value: string, path: string) {
    const admitted = required(value, path);
    if (admitted.startsWith("bar.")) {
        return { kind: "DATASET_FIELD" as const, field_name: admitted.slice(4) };
    }
    const separator = admitted.indexOf(".");
    if (separator <= 0 || separator === admitted.length - 1)
        throw new ResearchDraftError(path, "Published variable reference is invalid");
    return {
        kind: "VARIABLE" as const,
        instance_key: admitted.slice(0, separator),
        output_name: admitted.slice(separator + 1)
    };
}

function operand(value: OperandDraft, path: string) {
    return value.kind === "REFERENCE"
        ? reference(value.reference, path)
        : {
              kind: "LITERAL" as const,
              data_type: value.dataType,
              value: parseScalar(value.dataType, value.valueText, `${path}.value`)
          };
}

export function buildExpressionTransport(
    expression: ExpressionDraft,
    path: string
): ResearchExpressionTransport {
    if (expression.kind === "COMPARISON") {
        return {
            kind: "COMPARISON",
            operator: expression.operator,
            left: operand(expression.left, `${path}.left`),
            right: operand(expression.right, `${path}.right`)
        };
    }
    if (expression.kind === "NOT") {
        return {
            kind: "NOT",
            operand: buildExpressionTransport(expression.operand, `${path}.operand`)
        };
    }
    if (expression.operands.length < 2)
        throw new ResearchDraftError(path, `${expression.kind} requires at least two operands`);
    return {
        kind: expression.kind,
        operands: expression.operands.map((item, index) =>
            buildExpressionTransport(item, `${path}.operands[${String(index)}]`)
        )
    };
}

function calculation(
    draft: CalculationDraft,
    catalog: ReadonlyMap<string, ResearchCalculationCatalogItemTransport>,
    path: string,
    target: boolean
): ResearchCalculationInstanceTransport {
    const item = catalog.get(draft.catalogKey);
    if (item === undefined)
        throw new ResearchDraftError(path, "Calculation catalog item is unavailable");
    if (target !== (item.type_reference.kind === "TARGET"))
        throw new ResearchDraftError(path, "Calculation kind is invalid for this section");
    const parameters = item.parameters.reduce<ResearchCalculationInstanceTransport["parameters"]>(
        (result, definition) => {
            const value = draft.parameters[definition.name];
            if (value === undefined)
                throw new ResearchDraftError(
                    `${path}.parameters.${definition.name}`,
                    "Parameter is missing"
                );
            if (value.mode === "SWEEP") {
                const values = value.valuesText.split(",").map((entry) => entry.trim());
                if (target || !item.parameter_sweep_allowed)
                    throw new ResearchDraftError(
                        `${path}.parameters.${definition.name}`,
                        "Sweep is not admitted for this Calculation"
                    );
                if (values.length < 2)
                    throw new ResearchDraftError(
                        `${path}.parameters.${definition.name}`,
                        "Sweep requires at least two explicit values"
                    );
                return {
                    ...result,
                    [definition.name]: {
                        kind: "SWEEP" as const,
                        values: values.map((entry, index) =>
                            parseScalar(
                                value.scalarType,
                                entry,
                                `${path}.parameters.${definition.name}[${String(index)}]`
                            )
                        )
                    }
                };
            }
            return {
                ...result,
                [definition.name]: {
                    kind: "FIXED" as const,
                    value: parseScalar(
                        value.scalarType,
                        value.valuesText,
                        `${path}.parameters.${definition.name}`
                    )
                }
            };
        },
        {}
    );
    if (draft.publishedOutputs.length === 0)
        throw new ResearchDraftError(`${path}.published_outputs`, "Publish at least one output");
    const unknownOutput = draft.publishedOutputs.find(
        (name) => !item.outputs.some((output) => output.name === name)
    );
    if (unknownOutput !== undefined)
        throw new ResearchDraftError(
            `${path}.published_outputs`,
            `Published output is unavailable: ${unknownOutput}`
        );
    const published = [...draft.publishedOutputs];
    return {
        instance_key: required(draft.instanceKey, `${path}.instance_key`),
        type_reference: item.type_reference,
        parameters,
        published_outputs: published,
        input_bindings: item.inputs.map((input) => ({
            input_name: input.name,
            source: (() => {
                const source = required(
                    draft.inputBindings[input.name] ?? "",
                    `${path}.input_bindings.${input.name}`
                );
                const admitted = reference(source, `${path}.input_bindings.${input.name}`);
                return admitted.kind === "DATASET_FIELD" ? source : admitted;
            })()
        })),
        primary_output: published[0] ?? null
    };
}

export function buildResearchDefinitionTransport(
    draft: ResearchDraft,
    calculations: readonly ResearchCalculationCatalogItemTransport[]
): ResearchDefinitionTransport {
    const catalog = new Map(calculations.map((item) => [catalogKey(item), item]));
    const instruments = draft.dataset.instrumentsText
        .split(/[\s,]+/)
        .map((item) => item.trim())
        .filter(Boolean);
    const registered = draft.dataset.universeKind.startsWith("REGISTERED");
    if (registered) required(draft.dataset.registeredId, "dataset.universe.registered_id");
    if (!registered && instruments.length === 0)
        throw new ResearchDraftError(
            "dataset.universe.instrument_ids",
            "At least one instrument is required"
        );
    if (draft.dataset.universeKind === "SINGLE_INSTRUMENT" && instruments.length !== 1)
        throw new ResearchDraftError(
            "dataset.universe.instrument_ids",
            "Single instrument requires exactly one ID"
        );
    const calculationInstances = draft.calculations.map((item, index) =>
        calculation(item, catalog, `calculations[${String(index)}]`, false)
    );
    const targets = draft.targets.map((item, index) =>
        calculation(item, catalog, `targets[${String(index)}]`, true)
    );
    if (calculationInstances.length === 0)
        throw new ResearchDraftError("calculations", "Add at least one Calculation");
    if (targets.length === 0) throw new ResearchDraftError("targets", "Add at least one Target");
    const instanceKeys = [...calculationInstances, ...targets].map((item) => item.instance_key);
    if (new Set(instanceKeys).size !== instanceKeys.length)
        throw new ResearchDraftError("calculations", "Instance keys must be unique");
    if (draft.statistics.length === 0)
        throw new ResearchDraftError("statistics", "Add at least one Statistics request");

    return {
        schema_version: 1,
        dataset: {
            universe: {
                kind: draft.dataset.universeKind,
                instrument_ids: registered ? [] : instruments,
                registered_id: registered ? draft.dataset.registeredId.trim() : null
            },
            bar_specification: {
                step: positiveInteger(draft.dataset.step, "dataset.bar_specification.step"),
                aggregation: draft.dataset.aggregation,
                price_type: draft.dataset.priceType
            },
            aggregation_source: draft.dataset.aggregationSource,
            start: required(draft.dataset.start, "dataset.start"),
            end: required(draft.dataset.end, "dataset.end"),
            adjustment_type: draft.dataset.adjustmentType,
            adjustment_reference:
                draft.dataset.adjustmentReference.trim().length === 0
                    ? null
                    : draft.dataset.adjustmentReference.trim()
        },
        calculations: calculationInstances,
        eligibility:
            draft.eligibility === null
                ? null
                : buildExpressionTransport(draft.eligibility, "eligibility"),
        signals: {
            entry:
                draft.entry === null
                    ? null
                    : buildExpressionTransport(draft.entry, "signals.entry"),
            exit: draft.exit === null ? null : buildExpressionTransport(draft.exit, "signals.exit")
        },
        targets,
        statistics: draft.statistics.map((item, index) => {
            const itemPath = `statistics[${String(index)}]`;
            const variable = reference(item.variable, `${itemPath}.variable`);
            if (variable.kind !== "VARIABLE")
                throw new ResearchDraftError(
                    `${itemPath}.variable`,
                    "Statistics requires a published variable"
                );
            let method: "IC" | "RANK_IC";
            if (item.method === "IC") method = "IC";
            else if (item.method === "RANK_IC") method = "RANK_IC";
            else
                throw new ResearchDraftError(
                    `${itemPath}.method`,
                    "Statistics method is unsupported"
                );
            return {
                variable,
                target_instance_key: required(
                    item.targetInstanceKey,
                    `${itemPath}.target_instance_key`
                ),
                definition: {
                    schema_version: 1,
                    method,
                    minimum_observations: 2,
                    pairing_policy: "PAIRWISE_COMPLETE",
                    universe_policy: "OBSERVED_PAIRWISE",
                    rank_tie_method: "AVERAGE",
                    weighting: "EQUAL",
                    numeric: {
                        representation: "DECIMAL",
                        precision: 38,
                        output_quantum: "0.000000000001",
                        rounding: "ROUND_HALF_EVEN"
                    }
                }
            };
        }),
        display_metadata: {}
    };
}
