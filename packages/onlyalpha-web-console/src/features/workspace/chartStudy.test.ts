import type { ChartCalculationDraft, RegisteredCalculation } from "../../api/research/chartCatalog";
import { readChartCatalog } from "../../api/research/chartCatalog";
import { researchCalculationCatalogSchema } from "../../api/research/schemas";
import { chartCatalogFixture } from "../../test/chartCatalog";
import {
    configurationErrors,
    transientConfigurationErrors,
    parameterInputError,
    parameterTextInput,
    studyDescriptor,
    studyName,
    validPresentation,
    type StudyParameter,
    type StudyScalar
} from "./chartStudy";

function registration(): RegisteredCalculation {
    const item = researchCalculationCatalogSchema.parse(chartCatalogFixture().discovery)
        .calculations[0];
    if (item === undefined) throw new Error("Missing registration");
    return structuredClone(item);
}
function descriptor(item = registration()) {
    return studyDescriptor({ source: "REGISTERED_DISCOVERY", registration: item });
}
const decimal = (value: string): StudyScalar => ({ type: "DECIMAL", value });
function numericParameter(): StudyParameter {
    return {
        name: "threshold",
        type: "DECIMAL",
        required: false,
        default: decimal("0"),
        minimum: null,
        maximum: null,
        enumValues: [],
        uppercase: false
    };
}

it("adapts both formal DTO families and keeps raw defaults and no execution claim", async () => {
    const fixture = chartCatalogFixture();
    const discovery = descriptor();
    vi.stubGlobal(
        "fetch",
        vi.fn((input: string) =>
            Promise.resolve(
                new Response(
                    JSON.stringify(
                        input.endsWith("/active")
                            ? fixture.active
                            : input.includes("/runtime-generations/")
                              ? fixture.binding
                              : input.endsWith("/readiness")
                                ? fixture.readiness
                                : fixture.context
                    )
                )
            )
        )
    );
    const catalog = await readChartCatalog();
    const entry = catalog.entries[0];
    if (entry === undefined) throw new Error("Missing entry");
    const selection: ChartCalculationDraft = { source: "EXACT_CATALOG", catalog, entry };
    expect(studyDescriptor(selection)).toEqual(discovery);
    expect(discovery.parameters.map((p) => p.default)).toEqual([
        { type: "INTEGER", value: 20 },
        { type: "STRING", value: "CLOSE" }
    ]);
});
afterEach(() => {
    vi.unstubAllGlobals();
});
it("preserves numeric STRING default tags rather than normalizing", () => {
    const item = registration();
    const p = item.parameters[0];
    if (p === undefined) throw new Error("Missing parameter");
    p.default = { type: "STRING", value: "0020" };
    expect(descriptor(item).parameters[0]?.default).toEqual({ type: "STRING", value: "0020" });
});
it.each(["1.5", "", "NaN", "Infinity", "9007199254740992", "1e2", "-1"])(
    "rejects invalid integer input %s",
    (input) => {
        const p = descriptor().parameters[0];
        if (p === undefined) throw new Error("Missing parameter");
        expect(parameterInputError(p, parameterTextInput(p, input))).not.toBeNull();
    }
);
it("compares large decimals, exponents, negative values and zero without Number rounding", () => {
    const p = {
        ...numericParameter(),
        minimum: decimal("9007199254740993.123456789012345678901"),
        maximum: decimal("9007199254740993.123456789012345678903")
    };
    const value = "9007199254740993.123456789012345678902";
    expect(parameterTextInput(p, value)).toEqual(decimal(value));
    expect(parameterInputError(p, decimal(value))).toBeNull();
    expect(parameterInputError(p, decimal("9007199254740993.123456789012345678904"))).toBe(
        "超过 maximum"
    );
    expect(parameterInputError(p, decimal("9007199254740993.123456789012345678900"))).toBe(
        "低于 minimum"
    );
    const negative = {
        ...numericParameter(),
        minimum: decimal("-2e99999999999999999"),
        maximum: decimal("-1e99999999999999999")
    };
    expect(parameterInputError(negative, decimal("-15e99999999999999998"))).toBeNull();
    expect(
        parameterInputError(
            { ...numericParameter(), maximum: decimal("0") },
            decimal("0e99999999999999999999")
        )
    ).toBeNull();
    expect(
        parameterInputError(
            { ...numericParameter(), enumValues: [decimal("1.00")] },
            decimal(".1e1")
        )
    ).toBeNull();
});
it.each(["NaN", "Infinity", "", "1.2.3", "0x10"])("rejects non-decimal text %s", (value) => {
    expect(parameterInputError(numericParameter(), decimal(value))).not.toBeNull();
});
it.each([
    "unsafe",
    "duplicate",
    "empty-output",
    "bad-default",
    "bad-enum",
    "bad-bounds",
    "wrong-tag",
    "unsupported"
])("fails closed for %s metadata", (condition) => {
    const item = registration();
    const p = item.parameters[0];
    if (p === undefined) throw new Error("Missing parameter");
    if (condition === "unsafe") p.default = { type: "INTEGER", value: 9007199254740992 };
    if (condition === "duplicate") item.parameters.push(p);
    if (condition === "empty-output") item.outputs = [];
    if (condition === "bad-default") p.default = { type: "INTEGER", value: 0 };
    if (condition === "bad-enum") p.enum_values = [{ type: "INTEGER", value: 10 }];
    if (condition === "bad-bounds") p.maximum = { type: "INTEGER", value: -1 };
    if (condition === "wrong-tag") p.default = { type: "INTEGER", value: "20" };
    if (condition === "unsupported") p.type = "UNKNOWN";
    expect(() => descriptor(item)).toThrow();
});
it("requires explicit NULL/default input and output choice; boolean is never text", () => {
    const item = registration();
    item.parameters = [
        {
            name: "enabled",
            type: "BOOLEAN",
            required: true,
            default: { type: "NULL", value: null },
            minimum: null,
            maximum: null,
            enum_values: [],
            uppercase: false
        }
    ];
    const d = descriptor(item);
    const p = d.parameters[0];
    if (p === undefined) throw new Error("Missing parameter");
    expect(parameterInputError(p, { type: "STRING", value: "false" })).not.toBeNull();
    expect(parameterInputError(p, { type: "BOOLEAN", value: false })).toBeNull();
    expect(
        configurationErrors(d, {
            parameters: { enabled: { type: "NULL", value: null } },
            outputNames: [""]
        })
    ).toHaveLength(2);
    expect(
        configurationErrors(d, {
            parameters: { enabled: { type: "BOOLEAN", value: false } },
            outputNames: ["invented"]
        })
    ).toEqual(["请选择官方 output"]);
});
it.each(["bad-color", "zero-width", "large-width", "opacity", "infinite"])(
    "rejects %s presentation without changing inputs",
    (condition) => {
        const value = {
            placement: "PRICE_OVERLAY" as const,
            color: "#1f5f8b",
            lineWidth: 2,
            opacity: 1,
            visible: true
        };
        expect(validPresentation(value)).toBe(true);
        if (condition === "bad-color") value.color = "url(javascript:alert(1))";
        if (condition === "zero-width") value.lineWidth = 0;
        if (condition === "large-width") value.lineWidth = 6;
        if (condition === "opacity") value.opacity = -0.1;
        if (condition === "infinite") value.opacity = Infinity;
        expect(validPresentation(value)).toBe(false);
    }
);

it("checks transient support separately without narrowing the canonical descriptor", async () => {
    const { default: sample } =
        await import("../../../../../test-data/web/chart-studies/query.json");
    const { ChartStudyCapabilitiesSchema } = await import("../../api/chartStudies/http.generated");
    const capability = ChartStudyCapabilitiesSchema.parse({
        schema_version: 2,
        capabilities: [sample.capability]
    }).capabilities[0];
    if (capability === undefined) throw new Error("Expected installed capability");
    const selection: ChartCalculationDraft = { source: "CHART_STUDY_TRANSIENT", capability };
    const original = studyDescriptor(selection);
    const configuration = {
        parameters: {
            period: { type: "INTEGER" as const, value: 10001 },
            price_field: { type: "STRING" as const, value: "VOLUME" }
        },
        outputNames: ["value"]
    };
    expect(configurationErrors(original, configuration)).toEqual([]);
    expect(transientConfigurationErrors(capability, configuration)).toHaveLength(1);
    expect(
        transientConfigurationErrors(capability, {
            ...configuration,
            parameters: {
                period: { type: "INTEGER", value: 10000 },
                price_field: { type: "STRING", value: "CLOSE" }
            }
        })
    ).toEqual([]);
    expect(studyDescriptor(selection)).toEqual(original);
});

it("selects a numeric output group and rejects empty, duplicate or nonnumeric members", () => {
    const item = registration();
    item.parameters = [];
    item.outputs = [
        {
            dimensions: ["TIME"],
            nullable: true,
            unit: null,
            name: "fast",
            semantic_type: "NUMERIC_SERIES",
            data_type: "DECIMAL"
        },
        {
            dimensions: ["TIME"],
            nullable: true,
            unit: null,
            name: "slow",
            semantic_type: "NUMERIC_SERIES",
            data_type: "DECIMAL"
        },
        {
            dimensions: ["TIME"],
            nullable: true,
            unit: null,
            name: "ready",
            semantic_type: "READINESS",
            data_type: "STRING"
        }
    ];
    const d = descriptor(item);
    expect(configurationErrors(d, { parameters: {}, outputNames: ["fast", "slow"] })).toEqual([]);
    for (const outputNames of [[], ["fast", "fast"], ["ready"], ["missing"]])
        expect(configurationErrors(d, { parameters: {}, outputNames })).not.toHaveLength(0);
});

it("keeps explicit semantic-variant labels on configured indicator instances", async () => {
    const { default: sample } =
        await import("../../../../../test-data/web/chart-studies/query.json");
    const { ChartStudyCapabilitiesSchema } = await import("../../api/chartStudies/http.generated");
    const capability = ChartStudyCapabilitiesSchema.parse({
        schema_version: 2,
        capabilities: [sample.capability]
    }).capabilities[0];
    if (capability === undefined) throw new Error("Missing capability");
    capability.presentation.default_variant = false;
    expect(studyName({ source: "CHART_STUDY_TRANSIENT", capability })).toBe(
        `${capability.presentation.display_name} · 语义版本 ${capability.semantic_version}`
    );
});
