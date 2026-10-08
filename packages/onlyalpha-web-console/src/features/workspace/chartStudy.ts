import type { ChartCalculationDraft } from "../../api/research/chartCatalog";
import type { MarketDataBarSemantic, MarketDataSourceReference } from "../../api/marketData/model";

/** Input intent only: no canonical normalization, scientific identity or execution permission. */
export type StudyScalar =
    | { readonly type: "NULL"; readonly value: null }
    | { readonly type: "BOOLEAN"; readonly value: boolean }
    | { readonly type: "INTEGER"; readonly value: number }
    | { readonly type: "DECIMAL" | "STRING"; readonly value: string };
export interface StudyParameter {
    readonly name: string;
    readonly type: "INTEGER" | "DECIMAL" | "STRING" | "BOOLEAN";
    readonly required: boolean;
    readonly default: StudyScalar;
    readonly minimum: StudyScalar | null;
    readonly maximum: StudyScalar | null;
    readonly enumValues: readonly StudyScalar[];
    readonly uppercase: boolean;
}
export interface StudyDescriptor {
    readonly kind: string;
    readonly typeId: string;
    readonly semanticVersion: string;
    readonly parameters: readonly StudyParameter[];
    readonly outputs: readonly { readonly name: string; readonly semantic_type: string }[];
}
export interface ChartStudyContext {
    readonly key: string;
    readonly source: MarketDataSourceReference;
    readonly instrumentId: string;
    readonly barSemantic: MarketDataBarSemantic;
}
export interface StudyConfiguration {
    readonly parameters: Readonly<Record<string, StudyScalar>>;
    readonly outputName: string;
}
export interface StudyPresentation {
    readonly placement: "PRICE_OVERLAY" | "SEPARATE_PANE";
    readonly color: string;
    readonly lineWidth: number;
    readonly opacity: number;
    readonly visible: boolean;
}
export interface ChartStudyInstance {
    /** Browser display identity, never a Calculation fingerprint. */
    readonly instanceId: string;
    readonly context: ChartStudyContext;
    readonly selection: ChartCalculationDraft;
    readonly configuration: StudyConfiguration;
    readonly presentation: StudyPresentation;
    readonly connectionState: "CONFIGURED_NOT_EXECUTED" | "STALE_CONFIG";
}

// Exact Catalog encodes untagged scalars. This adapter tags by transport representation;
// numeric STRING defaults remain STRING, not a browser-normalized Calculation definition.
function scalar(
    value: string | number | boolean | null,
    type: StudyParameter["type"]
): StudyScalar {
    if (value === null) return { type: "NULL", value };
    if (typeof value === "boolean") return { type: "BOOLEAN", value };
    if (typeof value === "number") {
        if (!Number.isSafeInteger(value)) throw new Error("不安全的整数元数据");
        return { type: "INTEGER", value };
    }
    return { type: type === "DECIMAL" ? "DECIMAL" : "STRING", value };
}
function typed(value: {
    readonly type: string;
    readonly value: string | number | boolean | null;
}): StudyScalar {
    switch (value.type) {
        case "NULL":
            if (value.value === null) return { type: "NULL", value: null };
            break;
        case "BOOLEAN":
            if (typeof value.value === "boolean") return { type: "BOOLEAN", value: value.value };
            break;
        case "INTEGER":
            if (typeof value.value === "number" && Number.isSafeInteger(value.value))
                return { type: "INTEGER", value: value.value };
            break;
        case "STRING":
        case "DECIMAL":
            if (typeof value.value === "string") return { type: value.type, value: value.value };
            break;
    }
    throw new Error("参数 scalar 类型或精度不安全");
}

export function studyDescriptor(selection: ChartCalculationDraft): StudyDescriptor {
    let result: StudyDescriptor;
    if (selection.source === "REGISTERED_DISCOVERY") {
        const item = selection.registration;
        result = {
            kind: item.kind,
            typeId: item.type_reference.type_id,
            semanticVersion: item.type_reference.semantic_version,
            parameters: item.parameters.map((parameter) => ({
                name: parameter.name,
                type: parameterType(parameter.type),
                required: parameter.required,
                default: typed(parameter.default),
                minimum: parameter.minimum === null ? null : typed(parameter.minimum),
                maximum: parameter.maximum === null ? null : typed(parameter.maximum),
                enumValues: parameter.enum_values.map(typed),
                uppercase: parameter.uppercase
            })),
            outputs: item.outputs
        };
    } else {
        const item = selection.entry.capability.type_descriptor;
        result = {
            kind: item.kind,
            typeId: item.type_id,
            semanticVersion: item.semantic_version,
            parameters: item.parameters.map((parameter) => ({
                name: parameter.name,
                type: parameter.parameter_type,
                required: parameter.required,
                default: scalar(parameter.default, parameter.parameter_type),
                minimum:
                    parameter.minimum === null
                        ? null
                        : scalar(parameter.minimum, parameter.parameter_type),
                maximum:
                    parameter.maximum === null
                        ? null
                        : scalar(parameter.maximum, parameter.parameter_type),
                enumValues: parameter.enum_values.map((value) =>
                    scalar(value, parameter.parameter_type)
                ),
                uppercase: parameter.uppercase
            })),
            outputs: item.outputs
        };
    }
    if (
        new Set(result.parameters.map((p) => p.name)).size !== result.parameters.length ||
        new Set(result.outputs.map((p) => p.name)).size !== result.outputs.length ||
        result.outputs.length === 0
    )
        throw new Error("参数或输出名称重复 / 输出缺失");
    for (const parameter of result.parameters) {
        for (const bound of [parameter.minimum, parameter.maximum, ...parameter.enumValues]) {
            if (bound !== null && !validShape(parameter.type, bound))
                throw new Error("参数约束元数据无效");
        }
        if (
            parameter.minimum !== null &&
            parameter.maximum !== null &&
            compareNumeric(parameter.minimum, parameter.maximum) > 0
        )
            throw new Error("参数上下界无效");
        if (parameter.default.type === "NULL") {
            if (!parameter.required) throw new Error("可选参数没有合法默认值");
        } else if (parameterInputError(parameter, parameter.default) !== null)
            throw new Error("官方默认值不符合输入约束");
    }
    return result;
}

function parameterType(value: string): StudyParameter["type"] {
    if (value === "INTEGER" || value === "DECIMAL" || value === "STRING" || value === "BOOLEAN")
        return value;
    throw new Error("不支持的参数类型");
}

// Exact text comparison for UI bounds/enum only. No Number conversion or precision rounding.
// Exponents are compared as bigint orders; never allocate 10**exponent expanded strings.
function decimalParts(value: string) {
    const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(value);
    if (match === null || value.length > 4096) throw new Error("请输入有限十进制文本");
    const fraction = match[3] ?? match[4] ?? "";
    const digits = `${match[2] ?? ""}${fraction}`.replace(/^0+/, "") || "0";
    return {
        negative: match[1] === "-" && digits !== "0",
        digits,
        order: BigInt(digits.length) + BigInt(match[5] ?? "0") - BigInt(fraction.length)
    };
}
function numericText(value: StudyScalar): string {
    if (value.type === "INTEGER") {
        if (!Number.isSafeInteger(value.value)) throw new Error("整数超出安全输入范围");
        return String(value.value);
    }
    if (value.type === "STRING" || value.type === "DECIMAL") return value.value;
    throw new Error("非数值参数");
}
function compareNumeric(a: StudyScalar, b: StudyScalar): number {
    const left = decimalParts(numericText(a)),
        right = decimalParts(numericText(b));
    if (left.digits === "0" && right.digits === "0") return 0;
    if (left.negative !== right.negative) return left.negative ? -1 : 1;
    const length = Math.max(left.digits.length, right.digits.length);
    const l = left.digits.padEnd(length, "0"),
        r = right.digits.padEnd(length, "0");
    const magnitude =
        left.digits === "0"
            ? -1
            : right.digits === "0"
              ? 1
              : left.order < right.order
                ? -1
                : left.order > right.order
                  ? 1
                  : l < r
                    ? -1
                    : l > r
                      ? 1
                      : 0;
    return left.negative ? -magnitude : magnitude;
}
function validShape(type: StudyParameter["type"], value: StudyScalar): boolean {
    if (type === "BOOLEAN") return value.type === "BOOLEAN";
    if (type === "STRING") return value.type === "STRING";
    try {
        const text = numericText(value);
        if (type === "INTEGER")
            return /^[+-]?\d+$/.test(text) && Number.isSafeInteger(Number(text));
        decimalParts(text);
        return true;
    } catch {
        return false;
    }
}
export function parameterInputError(
    parameter: StudyParameter,
    value: StudyScalar | undefined
): string | null {
    if (
        value === undefined ||
        value.type === "NULL" ||
        ((value.type === "STRING" || value.type === "DECIMAL") &&
            value.value === "" &&
            (parameter.type !== "STRING" || parameter.required))
    )
        return "必填 / 请输入值";
    if (!validShape(parameter.type, value)) return "输入类型或精度不安全";
    try {
        if (parameter.minimum !== null && compareNumeric(value, parameter.minimum) < 0)
            return "低于 minimum";
        if (parameter.maximum !== null && compareNumeric(value, parameter.maximum) > 0)
            return "超过 maximum";
        if (
            parameter.enumValues.length > 0 &&
            !parameter.enumValues.some((candidate) =>
                parameter.type === "INTEGER" || parameter.type === "DECIMAL"
                    ? compareNumeric(value, candidate) === 0
                    : JSON.stringify(value) === JSON.stringify(candidate)
            )
        )
            return "不在官方 enum 中";
    } catch {
        return "参数约束无法验证";
    }
    return null;
}
export function parameterTextInput(parameter: StudyParameter, value: string): StudyScalar {
    if (
        parameter.type === "INTEGER" &&
        /^[+-]?\d+$/.test(value) &&
        Number.isSafeInteger(Number(value))
    )
        return { type: "INTEGER", value: Number(value) };
    return { type: parameter.type === "DECIMAL" ? "DECIMAL" : "STRING", value };
}
export function configurationErrors(
    descriptor: StudyDescriptor,
    configuration: StudyConfiguration
): readonly string[] {
    const errors = descriptor.parameters.flatMap((parameter) => {
        const error = parameterInputError(parameter, configuration.parameters[parameter.name]);
        return error === null ? [] : [`${parameter.name}: ${error}`];
    });
    if (
        Object.keys(configuration.parameters).some(
            (name) => !descriptor.parameters.some((p) => p.name === name)
        )
    )
        errors.push("未知参数");
    if (!descriptor.outputs.some((output) => output.name === configuration.outputName))
        errors.push("请选择官方 output");
    return errors;
}
export function validPresentation(value: StudyPresentation): boolean {
    return (
        ["PRICE_OVERLAY", "SEPARATE_PANE"].includes(value.placement) &&
        /^#[0-9a-fA-F]{6}$/.test(value.color) &&
        Number.isFinite(value.lineWidth) &&
        value.lineWidth >= 1 &&
        value.lineWidth <= 5 &&
        Number.isFinite(value.opacity) &&
        value.opacity >= 0 &&
        value.opacity <= 1 &&
        typeof value.visible === "boolean"
    );
}
