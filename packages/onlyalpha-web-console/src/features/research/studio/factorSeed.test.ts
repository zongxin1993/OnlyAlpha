import type { ResearchCalculationCatalogItemTransport } from "../../../api/research/schemas";
import { readFactorSeed } from "./factorSeed";
import { initialResearchDraft } from "./researchDraft";

const factor: ResearchCalculationCatalogItemTransport = {
    kind: "FACTOR",
    type_reference: { kind: "FACTOR", type_id: "test.factor.momentum", semantic_version: "1" },
    parameters: [
        {
            name: "period",
            type: "INTEGER",
            required: false,
            default: { type: "INTEGER", value: 14 },
            minimum: { type: "INTEGER", value: 1 },
            maximum: null,
            enum_values: [],
            uppercase: false
        }
    ],
    inputs: [
        {
            name: "price",
            data_type: "DECIMAL",
            nullable: false,
            semantic_type: "PRICE",
            dimensions: ["INSTRUMENT", "TIME"],
            unit: "PRICE"
        }
    ],
    outputs: [
        {
            name: "score",
            data_type: "DECIMAL",
            nullable: true,
            semantic_type: "FACTOR_SCORE",
            dimensions: ["INSTRUMENT", "TIME"],
            unit: null
        }
    ],
    parameter_sweep_allowed: true
};
const indicator: ResearchCalculationCatalogItemTransport = {
    ...factor,
    kind: "INDICATOR",
    type_reference: { kind: "INDICATOR", type_id: "test.indicator.momentum", semantic_version: "1" }
};
const key = "FACTOR:test.factor.momentum@1";

function ready(parameters: URLSearchParams) {
    const seed = readFactorSeed(parameters, [factor, indicator]);
    if (seed?.kind !== "READY") throw new Error("Expected a valid Factor authoring seed");
    return seed;
}

it("does not infer a Factor seed when its explicit query parameter is absent", () => {
    expect(
        readFactorSeed(new URLSearchParams("instrument=A.XNAS&from=2026-01-01"), [factor])
    ).toBeNull();
});

it("uses only the exact admitted Factor and preserves unbound inputs and missing Target/Statistics", () => {
    const seed = ready(new URLSearchParams({ factor: key, instrument: "A.XNAS" }));
    expect(seed.factorKey).toBe(key);
    expect(seed.draft.dataset).toEqual({
        ...initialResearchDraft().dataset,
        instrumentsText: "A.XNAS"
    });
    expect(seed.draft.calculations).toEqual([
        {
            draftId: 1,
            catalogKey: key,
            instanceKey: "factor_1",
            parameters: { period: { mode: "FIXED", scalarType: "INTEGER", valuesText: "14" } },
            publishedOutputs: ["score"],
            inputBindings: { price: "" }
        }
    ]);
    expect(seed.draft.targets).toEqual([]);
    expect(seed.draft.statistics).toEqual([]);
    expect(seed.draft.eligibility).toBeNull();
    expect(seed.draft.entry).toBeNull();
    expect(seed.draft.exit).toBeNull();
});

it("preserves a two-stock selection and an explicit half-open UTC date interval", () => {
    const parameters = new URLSearchParams({ factor: key, from: "2024-02-29", to: "2024-03-02" });
    parameters.append("instrument", "A.XNAS");
    parameters.append("instrument", "B.XNAS");
    const seed = ready(parameters);
    expect(seed.draft.dataset.universeKind).toBe("EXPLICIT_INSTRUMENT_SET");
    expect(seed.draft.dataset.instrumentsText).toBe("A.XNAS, B.XNAS");
    expect(seed.draft.dataset.start).toBe("2024-02-29T00:00:00Z");
    expect(seed.draft.dataset.end).toBe("2024-03-02T00:00:00Z");
});

it("does not invent instruments or an opposite date endpoint when only some fields are supplied", () => {
    const seed = ready(new URLSearchParams({ factor: key, from: "2026-01-01" }));
    expect(seed.draft.dataset.instrumentsText).toBe("");
    expect(seed.draft.dataset.start).toBe("2026-01-01T00:00:00Z");
    expect(seed.draft.dataset.end).toBe("");
    expect(seed.draft.targets).toEqual([]);
});

it.each([
    "FACTOR:test.factor.momentum@2",
    "FACTOR:unknown.factor@1",
    "INDICATOR:test.indicator.momentum@1",
    ""
])("rejects absent versions and non-Factor catalog selections: %s", (selection) => {
    const seed = readFactorSeed(new URLSearchParams({ factor: selection }), [factor, indicator]);
    expect(seed).toEqual({
        kind: "INVALID",
        detail: "The exact Factor type and version is not available in the current catalog."
    });
});

it.each([
    "",
    "A.XNAS B.XNAS",
    "A.XNAS,B.XNAS",
    " A.XNAS",
    "A.XNAS\n",
    `A${String.fromCharCode(0)}XNAS`
])(
    "rejects instrument text the existing builder cannot represent without changing its identity: %j",
    (instrument) => {
        const seed = readFactorSeed(new URLSearchParams({ factor: key, instrument }), [factor]);
        expect(seed?.kind).toBe("INVALID");
    }
);

it("rejects duplicate instrument or singular selector parameters instead of silently picking one", () => {
    for (const duplicate of ["factor", "from", "to", "instrument"]) {
        const parameters = new URLSearchParams({
            factor: key,
            from: "2026-01-01",
            to: "2026-02-01",
            instrument: "A.XNAS"
        });
        const value = parameters.get(duplicate);
        if (value === null) throw new Error("Missing duplicate fixture value");
        parameters.append(duplicate, value);
        expect(readFactorSeed(parameters, [factor])?.kind).toBe("INVALID");
    }
});

it("rejects an ambiguous current catalog instead of selecting its first matching registration", () => {
    expect(readFactorSeed(new URLSearchParams({ factor: key }), [factor, factor])?.kind).toBe(
        "INVALID"
    );
});

it.each([
    { from: "2026-02-29", to: "2026-03-01" },
    { from: "2026-01-01", to: "2026-04-31" },
    { from: "2026-1-01", to: "2026-02-01" },
    { from: "0000-01-01", to: "2026-02-01" },
    { from: "2026-01-01", to: "2026-01-01" },
    { from: "2026-02-01", to: "2026-01-01" },
    { from: "2026-01-01", to: "" },
    { from: "2026-01-01T00:00:00Z", to: "2026-02-01" }
])(
    "rejects invalid calendar dates or empty/reversed half-open intervals: $from → $to",
    (interval) => {
        expect(
            readFactorSeed(new URLSearchParams({ factor: key, ...interval }), [factor])?.kind
        ).toBe("INVALID");
    }
);
