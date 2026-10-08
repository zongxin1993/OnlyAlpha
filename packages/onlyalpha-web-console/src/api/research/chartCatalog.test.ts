import { chartCatalogFixture } from "../../test/chartCatalog";
import { readChartCatalog, readRegisteredCalculations } from "./chartCatalog";

afterEach(() => {
    vi.unstubAllGlobals();
});

function serve(fixture = chartCatalogFixture(), finalRuntime = fixture.runtime) {
    let activeReads = 0;
    const fetcher = vi.fn((input: string, init: RequestInit) => {
        expect(init.method).toBeUndefined();
        const path = input.replace("/api/v2/research/", "");
        const body =
            path === "runtime-generations/active"
                ? {
                      ...fixture.active,
                      runtime_generation_fingerprint:
                          ++activeReads === 1 ? fixture.runtime : finalRuntime
                  }
                : path === `runtime-generations/${fixture.runtime}`
                  ? fixture.binding
                  : path === `catalog-context/exact/${fixture.catalog}`
                    ? fixture.context
                    : path === `catalog-context/exact/${fixture.catalog}/readiness`
                      ? fixture.readiness
                      : null;
        if (body === null) throw new Error(`Unexpected query ${input}`);
        return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetcher);
    return fetcher;
}

it("resolves distinct Runtime and Catalog identities and forwards exact descriptor defaults", async () => {
    const fixture = chartCatalogFixture();
    const fetcher = serve(fixture);
    const catalog = await readChartCatalog();
    expect(catalog.runtimeGenerationFingerprint).toBe(fixture.runtime);
    expect(catalog.catalogGenerationFingerprint).toBe(fixture.catalog);
    expect(catalog.entries[0]).toMatchObject({
        availability: "AVAILABLE",
        capability: fixture.capability,
        readiness: fixture.witness
    });
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
        `/api/v2/research/runtime-generations/active`,
        `/api/v2/research/runtime-generations/${fixture.runtime}`,
        `/api/v2/research/catalog-context/exact/${fixture.catalog}`,
        `/api/v2/research/catalog-context/exact/${fixture.catalog}/readiness`,
        `/api/v2/research/runtime-generations/active`
    ]);
});

it("has no frontend type allowlist", async () => {
    const fixture = chartCatalogFixture();
    fixture.capability.type_id = "registered.indicator.custom";
    fixture.capability.type_descriptor.type_id = fixture.capability.type_id;
    fixture.witness.type_id = fixture.capability.type_id;
    serve(fixture);
    expect((await readChartCatalog()).entries[0]?.availability).toBe("AVAILABLE");
});

it.each([
    [
        "whole context",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.context.catalog_generation_fingerprint = "b".repeat(64);
        }
    ],
    [
        "runtime owner",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.binding.runtime_generation_fingerprint = f.catalog;
        }
    ],
    [
        "nested descriptor",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.capability.type_descriptor.type_id = "other";
        }
    ],
    [
        "source owner",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.provider.provider_id = "other";
        }
    ],
    [
        "leaf implementation",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.witness.implementation_fingerprint = "b".repeat(64);
        }
    ],
    [
        "duplicate owner",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.context.ordered_calculation_capabilities.push(f.capability);
        }
    ],
    [
        "duplicate witness",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.readiness.ordered_calculation_readiness_capabilities.push(f.witness);
        }
    ],
    [
        "wrong family",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.capability.kind = "FACTOR";
            f.capability.type_descriptor.kind = "FACTOR";
        }
    ],
    [
        "complete different projection",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.readiness.exact_catalog_context_projection_fingerprint = "b".repeat(64);
        }
    ],
    [
        "readiness scope",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.witness.catalog_generation_fingerprint = "b".repeat(64);
        }
    ],
    [
        "readiness provider",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.witness.provider_version = "other";
        }
    ],
    [
        "orphan witness",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.witness.type_id = "other";
        }
    ],
    [
        "duplicate parameter",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.capability.type_descriptor.parameters.push(f.parameter);
        }
    ],
    [
        "duplicate output",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.capability.type_descriptor.outputs.push(f.output);
        }
    ],
    [
        "duplicate provider",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.context.ordered_providers.push(f.provider);
        }
    ],
    [
        "duplicate version",
        (f: ReturnType<typeof chartCatalogFixture>) => {
            f.witness.readiness_contract_versions = [1, 1];
        }
    ]
] as const)("fails closed on %s mutations", async (_name, mutate) => {
    const fixture = chartCatalogFixture();
    mutate(fixture);
    serve(fixture);
    await expect(readChartCatalog()).rejects.toMatchObject({ code: "INVALID" });
});

it("missing witness remains incomplete, never AVAILABLE", async () => {
    const fixture = chartCatalogFixture();
    fixture.readiness.ordered_calculation_readiness_capabilities = [];
    serve(fixture);
    expect((await readChartCatalog()).entries[0]).toMatchObject({
        availability: "NOT_CONNECTED",
        readiness: null
    });
});

it.each(["backend", "readiness", "shape"])(
    "complete unsupported %s is not selectable",
    async (dimension) => {
        const fixture = chartCatalogFixture();
        if (dimension === "backend") {
            fixture.capability.backend = "TRADING";
            fixture.witness.backend = "TRADING";
            fixture.witness.readiness_contract_versions = [];
        }
        if (dimension === "readiness") fixture.witness.readiness_contract_versions = [2];
        if (dimension === "shape")
            fixture.capability.type_descriptor.execution_shape = "CROSS_SECTION";
        serve(fixture);
        expect((await readChartCatalog()).entries[0]?.availability).toBe("UNSUPPORTED");
    }
);

it("fences a switch between Catalog reads and publication", async () => {
    serve(chartCatalogFixture(), "b".repeat(64));
    await expect(readChartCatalog()).rejects.toMatchObject({ code: "STALE" });
});

it("classifies disappearance at the final Runtime fence as stale, not initial absence", async () => {
    const fixture = chartCatalogFixture();
    let activeReads = 0;
    vi.stubGlobal(
        "fetch",
        vi.fn((input: string) => {
            if (input.endsWith("/active") && ++activeReads === 2)
                return Promise.resolve(
                    new Response(JSON.stringify({ detail: "RUNTIME_GENERATION_NOT_ACTIVE" }), {
                        status: 503
                    })
                );
            const body = input.endsWith("/active")
                ? fixture.active
                : input.includes("/runtime-generations/")
                  ? fixture.binding
                  : input.endsWith("/readiness")
                    ? fixture.readiness
                    : fixture.context;
            return Promise.resolve(new Response(JSON.stringify(body)));
        })
    );
    await expect(readChartCatalog()).rejects.toMatchObject({ code: "STALE" });
});

it.each([
    [503, { detail: "RUNTIME_GENERATION_NOT_ACTIVE" }, "NO_RUNTIME"],
    [503, { detail: "DATABASE_UNAVAILABLE" }, "TRANSPORT"],
    [200, { schema_version: 1 }, "INVALID"],
    [
        200,
        {
            schema_version: 1,
            runtime_generation_fingerprint: "a".repeat(64),
            source_code: "not metadata"
        },
        "INVALID"
    ]
])("preserves absence versus failure (%s)", async (status, body, code) => {
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status })))
    );
    await expect(readChartCatalog()).rejects.toMatchObject({ code });
});

it.each([
    { type: "INTEGER", value: true },
    { type: "BOOLEAN", value: 1 },
    { type: "STRING", value: 20 },
    { type: "NULL", value: "missing" },
    { type: "DECIMAL", value: "NaN" },
    { type: "DECIMAL", value: "Infinity" }
])("rejects mismatched typed discovery scalars: %j", async (scalar) => {
    const fixture = chartCatalogFixture();
    const parameter = fixture.discovery.calculations[0]?.parameters[0];
    if (parameter === undefined) throw new Error("Missing parameter fixture");
    Object.assign(parameter.default, scalar);
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response(JSON.stringify(fixture.discovery))))
    );
    await expect(readRegisteredCalculations()).rejects.toMatchObject({ code: "INVALID" });
});

it.each(["default", "minimum", "maximum", "enum"])(
    "validates typed scalars in %s metadata",
    async (field) => {
        const fixture = chartCatalogFixture();
        const parameter = fixture.discovery.calculations[0]?.parameters[0];
        if (parameter === undefined) throw new Error("Missing parameter fixture");
        const bad = { type: "INTEGER", value: true };
        if (field === "enum") Object.assign(parameter, { enum_values: [bad] });
        else Object.assign(parameter, { [field]: bad });
        vi.stubGlobal(
            "fetch",
            vi.fn(() => Promise.resolve(new Response(JSON.stringify(fixture.discovery))))
        );
        await expect(readRegisteredCalculations()).rejects.toMatchObject({ code: "INVALID" });
    }
);

it.each(["numeric-boolean", "boolean-numeric", "optional-null"])(
    "rejects incompatible parameter defaults: %s",
    async (condition) => {
        const fixture = chartCatalogFixture();
        const parameter = fixture.discovery.calculations[0]?.parameters[0];
        if (parameter === undefined) throw new Error("Missing parameter fixture");
        if (condition === "numeric-boolean")
            Object.assign(parameter.default, { type: "BOOLEAN", value: true });
        if (condition === "boolean-numeric") parameter.type = "BOOLEAN";
        if (condition === "optional-null")
            Object.assign(parameter.default, { type: "NULL", value: null });
        vi.stubGlobal(
            "fetch",
            vi.fn(() => Promise.resolve(new Response(JSON.stringify(fixture.discovery))))
        );
        await expect(readRegisteredCalculations()).rejects.toMatchObject({ code: "INVALID" });
    }
);

it("retains numeric string defaults without browser coercion", async () => {
    const fixture = chartCatalogFixture();
    const parameter = fixture.discovery.calculations[0]?.parameters[0];
    if (parameter === undefined) throw new Error("Missing parameter fixture");
    Object.assign(parameter.default, { type: "STRING", value: "20" });
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response(JSON.stringify(fixture.discovery))))
    );
    expect((await readRegisteredCalculations())[0]?.parameters[0]?.default).toEqual({
        type: "STRING",
        value: "20"
    });
});

it("does not hide malformed JSON or rejected transports as empty catalogs", async () => {
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response("not json")))
    );
    await expect(readChartCatalog()).rejects.toMatchObject({ code: "INVALID" });
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.reject(new TypeError("offline")))
    );
    await expect(readChartCatalog()).rejects.toMatchObject({ code: "TRANSPORT" });
});

it("reads registered discovery independently of Runtime and exact Catalog queries", async () => {
    const fixture = chartCatalogFixture();
    const fetcher = vi.fn((input: string) => {
        expect(input).toBe("/api/v2/research/catalog/calculations");
        return Promise.resolve(new Response(JSON.stringify(fixture.discovery)));
    });
    vi.stubGlobal("fetch", fetcher);
    expect(await readRegisteredCalculations()).toEqual(fixture.discovery.calculations);
    expect(fetcher).toHaveBeenCalledTimes(1);
});

it.each([
    "duplicate",
    "wrong-kind",
    "duplicate-parameter",
    "duplicate-output",
    "missing-output",
    "source-code"
])("rejects malformed registered discovery: %s", async (mutation) => {
    const fixture = chartCatalogFixture();
    const item = fixture.discovery.calculations[0];
    if (item?.parameters[0] === undefined || item.outputs[0] === undefined)
        throw new Error("Missing discovery fixture");
    if (mutation === "duplicate") fixture.discovery.calculations.push(item);
    if (mutation === "wrong-kind") item.type_reference.kind = "FACTOR";
    if (mutation === "duplicate-parameter") item.parameters.push(item.parameters[0]);
    if (mutation === "duplicate-output") item.outputs.push(item.outputs[0]);
    if (mutation === "missing-output") item.outputs = [];
    if (mutation === "source-code") Object.assign(item, { source_code: "not navigation metadata" });
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response(JSON.stringify(fixture.discovery))))
    );
    await expect(readRegisteredCalculations()).rejects.toMatchObject({ code: "INVALID" });
});
