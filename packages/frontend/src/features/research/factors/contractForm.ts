// Editing projections only. Backend canonical identity and acceptance remain authoritative.
export type ContractKind = "input_contract" | "parameter_contract" | "output_contract";
export const contractTitles: Record<ContractKind, string> = {
    input_contract: "所需数据",
    parameter_contract: "可调参数",
    output_contract: "计算结果"
};
export const contractTypes = ["DECIMAL", "INTEGER", "BOOLEAN", "STRING"] as const;
type ObjectValue = Record<string, unknown>;
const has = (value: ObjectValue, key: string) => Object.hasOwn(value, key);
const object = (value: unknown): value is ObjectValue =>
    value !== null && typeof value === "object" && !Array.isArray(value);
export function inspectContract(text: string): { value: ObjectValue | null; error: string } {
    try {
        if (new TextEncoder().encode(text).length > 262144)
            throw new Error("契约超过现有内容大小限制");
        const value: unknown = JSON.parse(text);
        if (!object(value)) throw new Error("契约必须是 JSON 对象");
        // Native JSON syntax validation first; inspect tokens before using parsed values.
        // In particular JSON.parse alone silently discards duplicate keys and rounds integers.
        const stack: (Set<string> | null)[] = [];
        const tokens = [
            ...text.matchAll(
                /"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}[\]:,]|true|false|null/g
            )
        ];
        for (const [i, match] of tokens.entries()) {
            const token = match[0];
            const isKey = token.startsWith('"') && tokens[i + 1]?.[0] === ":";
            if (!["{", "[", "}", "]", ":", ","].includes(token) && !isKey && stack.length > 32)
                throw new Error("契约超过现有嵌套深度限制");
            if (token === "{" || token === "[") {
                stack.push(token === "{" ? new Set() : null);
                if (stack.length > 33) throw new Error("契约超过现有嵌套深度限制");
            } else if (token === "}" || token === "]") stack.pop();
            else if (token.startsWith('"')) {
                const decoded: unknown = JSON.parse(token);
                if (typeof decoded !== "string") throw new Error("JSON 字符串无效");
                if (decoded.includes("\0")) throw new Error("契约不能包含 NUL 控制字符");
                if (tokens[i + 1]?.[0] === ":") {
                    const keys = stack.at(-1);
                    if (keys?.has(decoded)) throw new Error(`JSON 字段重复：${decoded}`);
                    keys?.add(decoded);
                }
            } else if (
                /^-?\d/.test(token) &&
                (/[.eE]/.test(token) || !Number.isSafeInteger(Number(token)))
            )
                throw new Error("契约数值只支持安全范围内的整数；精确小数请使用字符串");
        }
        return { value, error: "" };
    } catch (error) {
        return { value: null, error: error instanceof Error ? error.message : "契约 JSON 无效" };
    }
}
export interface ContractRow {
    original: ObjectValue;
    originalName: string;
    name: string;
    type: string;
    nullable: boolean;
    required: boolean;
    hasDefault: boolean;
    defaultText: string;
    defaultTouched: boolean;
}
function row(name: string, spec: ObjectValue): ContractRow {
    return {
        original: spec,
        originalName: name,
        name,
        type: String(spec.type),
        nullable: spec.nullable === true || spec.missing === true,
        required: typeof spec.required === "boolean" ? spec.required : !has(spec, "default"),
        hasDefault: has(spec, "default"),
        defaultText:
            typeof spec.default === "boolean"
                ? String(spec.default)
                : typeof spec.default === "string" || typeof spec.default === "number"
                  ? String(spec.default)
                  : "",
        defaultTouched: false
    };
}
export function newRow(kind: ContractKind): ContractRow {
    return row(
        "",
        kind === "parameter_contract" ? { type: "INTEGER", required: true } : { type: "DECIMAL" }
    );
}
export function changeRow<
    K extends "name" | "type" | "nullable" | "required" | "hasDefault" | "defaultText"
>(value: ContractRow, key: K, next: ContractRow[K]): ContractRow {
    return { ...value, [key]: next, ...(key === "defaultText" ? { defaultTouched: true } : {}) };
}
function defaultValue(value: ContractRow): unknown {
    const text = value.defaultText;
    if (value.type !== value.original.type && value.hasDefault && !value.defaultTouched)
        throw new Error("类型已变更，请重新确认默认值");
    if (
        value.type === value.original.type &&
        value.hasDefault === has(value.original, "default") &&
        text === row(value.originalName, value.original).defaultText
    )
        return value.original.default;
    if (value.type === "STRING") return text;
    if (value.type === "BOOLEAN") {
        if (text === "true" || text === "false") return text === "true";
    } else if (value.type === "INTEGER") {
        if (/^-?(?:0|[1-9]\d*)$/.test(text) && Number.isSafeInteger(Number(text)))
            return Number(text);
    } else if (value.type === "DECIMAL") {
        if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) return text;
    }
    throw new Error("默认值与参数类型不符；整数须在安全范围内，精确小数使用有限十进制值");
}
function validDefault(type: string, value: unknown): boolean {
    if (type === "STRING") return typeof value === "string";
    if (type === "BOOLEAN") return typeof value === "boolean";
    if (type === "INTEGER")
        return (
            (typeof value === "number" && Number.isSafeInteger(value)) ||
            (typeof value === "string" && /^-?\d+$/.test(value))
        );
    return (
        (typeof value === "number" && Number.isSafeInteger(value)) ||
        (typeof value === "string" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value))
    );
}
export function rowsFromContract(kind: ContractKind, text: string): ContractRow[] | null {
    const parsed = inspectContract(text);
    if (parsed.value === null) return null;
    const allowed =
        kind === "parameter_contract"
            ? ["type", "required", "default"]
            : kind === "input_contract"
              ? ["type", "nullable", "missing"]
              : ["type", "nullable", "missing", "semantic_type"];
    const rows: ContractRow[] = [];
    for (const [name, spec] of Object.entries(parsed.value)) {
        if (
            !name.trim() ||
            (kind === "parameter_contract" && /\s/.test(name)) ||
            !object(spec) ||
            !contractTypes.some((t) => t === spec.type) ||
            Object.keys(spec).some((k) => !allowed.includes(k))
        )
            return null;
        if (has(spec, "nullable") && has(spec, "missing")) return null;
        for (const key of ["nullable", "missing", "required"])
            if (has(spec, key) && typeof spec[key] !== "boolean") return null;
        if (has(spec, "semantic_type") && spec.semantic_type !== "FACTOR_VALUE") return null;
        if (kind === "parameter_contract") {
            if (Object.is(spec.default, -0)) return null;
            if (has(spec, "default") && !validDefault(String(spec.type), spec.default)) return null;
            if (spec.required === false && (!has(spec, "default") || spec.default === null))
                return null;
        }
        rows.push(row(name, spec));
    }
    return rows;
}
function equal(a: ObjectValue, b: ObjectValue): boolean {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every((k) => has(b, k) && a[k] === b[k]);
}
export function contractFromRows(
    kind: ContractKind,
    rows: ContractRow[],
    originalText: string
): { text: string; error: string; companion: boolean; companionRows: ContractRow[] } {
    const companionRows: ContractRow[] = [];
    try {
        const names = new Set<string>();
        const pairs = rows.map((value) => {
            const owner =
                kind === "parameter_contract"
                    ? "参数"
                    : kind === "input_contract"
                      ? "输入"
                      : "结果";
            if (!value.name.trim()) throw new Error(`请输入${owner}名称`);
            if (kind === "parameter_contract" && /\s/.test(value.name))
                throw new Error("参数名称不能包含空白字符");
            if (names.has(value.name)) throw new Error(`${owner}名称重复：${value.name}`);
            names.add(value.name);
            const spec = { ...value.original };
            const baseline = row(value.originalName, value.original);
            if (value.type !== baseline.type) spec.type = value.type;
            if (kind === "parameter_contract") {
                if (value.hasDefault) {
                    spec.default = defaultValue(value);
                    if (!validDefault(value.type, spec.default))
                        throw new Error("默认值与参数类型不符");
                } else delete spec.default;
                if (value.required !== baseline.required) spec.required = value.required;
                else if (!has(spec, "required") && value.required === has(spec, "default")) {
                    spec.required = value.required;
                    companionRows.push(value);
                }
                if (!value.required && (!value.hasDefault || spec.default == null))
                    throw new Error("非必填参数需要有效默认值");
            } else if (value.nullable !== baseline.nullable)
                spec[has(spec, "missing") ? "missing" : "nullable"] = value.nullable;
            return [value.name, spec] as const;
        });
        const result = Object.fromEntries(pairs);
        const initial = inspectContract(originalText).value;
        const unchanged =
            initial !== null &&
            Object.keys(initial).length === pairs.length &&
            pairs.every(([name, spec]) => object(initial[name]) && equal(spec, initial[name]));
        return {
            text: unchanged ? originalText : JSON.stringify(result, null, 2),
            error: "",
            companion: companionRows.length > 0,
            companionRows
        };
    } catch (error) {
        return {
            text: originalText,
            error: error instanceof Error ? error.message : "契约填写无效",
            companion: false,
            companionRows: []
        };
    }
}

export function sameContractValues(left: string, right: string): boolean {
    const a = inspectContract(left).value,
        b = inspectContract(right).value;
    return (
        a !== null &&
        b !== null &&
        Object.keys(a).length === Object.keys(b).length &&
        Object.keys(a).every((k) => object(a[k]) && object(b[k]) && equal(a[k], b[k]))
    );
}
