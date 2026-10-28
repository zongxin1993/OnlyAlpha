import { useQueryClient } from "@tanstack/react-query";
import { registry as registrySchema } from "../../../api/privateAssets/client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AppProviders } from "../../../app/providers";
import { FactorExplorerPage } from "./FactorExplorerPage";

const revision = "b".repeat(64);
const content = "c".repeat(64);
const entry = {
    locator: {
        private_asset_kind: "FACTOR",
        private_asset_id: "private.factor.momentum",
        revision_fingerprint: revision,
        content_fingerprint: content
    },
    semantic_version: "2",
    description: "Momentum metadata",
    category: "momentum",
    tags: ["daily"]
};
const exact = {
    schema_version: 1,
    factor_id: entry.locator.private_asset_id,
    semantic_version: "2",
    revision_fingerprint: revision,
    parent_revision_fingerprint: null,
    source_text: "def calculate(api, inputs, parameters):\n    return inputs\n",
    source_sha256: content,
    factor_api_version: 1,
    factor_api_contract_fingerprint: "d".repeat(64),
    input_contract: { price: { type: "DECIMAL" } },
    parameter_contract: {},
    output_contract: { alpha: { type: "DECIMAL" } },
    description: entry.description,
    economic_rationale: "An explicit saved hypothesis",
    category: entry.category,
    tags: entry.tags
};
const presentation = {
    locator: entry.locator,
    display: {
        schema_version: 1,
        factor_id: entry.locator.private_asset_id,
        display_name: "价格动量",
        usage_summary: "观察价格变化",
        edit_number: 1
    },
    display_fingerprint: "e".repeat(64),
    display_version: 1
};
const calls: string[] = [];
beforeEach(() => {
    calls.length = 0;
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    vi.stubGlobal(
        "fetch",
        vi.fn((input: RequestInfo | URL) => {
            const path =
                typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
            calls.push(path);
            const body =
                path === "/api/v2/private-assets"
                    ? {
                          schema_version: 1,
                          registry_fingerprint: "a".repeat(64),
                          entries: [entry],
                          factor_presentations: [presentation]
                      }
                    : path.includes("/private-assets/factors/")
                      ? exact
                      : path.includes("/chart/studies/capabilities")
                        ? {
                              error: {
                                  code: "CHART_STUDY_CAPABILITY_UNAVAILABLE",
                                  detail: "Installation unavailable"
                              }
                          }
                        : { schema_version: 2, calculations: [] };
            return Promise.resolve(
                new Response(JSON.stringify(body), {
                    status: path.includes("/chart/") ? 503 : 200,
                    headers: { "content-type": "application/json", "cache-control": "no-store" }
                })
            );
        })
    );
});
afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
});

test("shows actual private metadata and explicitly deferred Research without fetching Runs/results", async () => {
    render(
        <AppProviders>
            <FactorExplorerPage />
        </AppProviders>
    );
    expect(await screen.findByText("价格动量 · 第 1 版")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Configure Research · unavailable" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run Research" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open published results" })).toBeDisabled();
    expect(calls.some((path) => /\/runs|\/results|\/resolve/.test(path))).toBe(false);
    expect(calls.some((path) => path.includes("/factors/"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /价格动量 · 第 1 版/ }));
    expect(
        await screen.findByRole("article", { name: "Exact Factor metadata" })
    ).toBeInTheDocument();
    expect(screen.getByText("An explicit saved hypothesis")).toBeInTheDocument();
    expect(calls).toContain(
        `/api/v2/private-assets/factors/private.factor.momentum/revisions/${revision}?content_fingerprint=${content}`
    );
    expect(screen.queryByText(exact.source_text)).not.toBeInTheDocument();
});

test("denied inventory is an explicit error and does not become successful absence", async () => {
    vi.stubGlobal(
        "fetch",
        vi.fn(() =>
            Promise.resolve(
                new Response(
                    JSON.stringify({
                        error: { code: "FORBIDDEN", detail: "Metadata access denied" }
                    }),
                    {
                        status: 403,
                        headers: { "content-type": "application/json", "cache-control": "no-store" }
                    }
                )
            )
        )
    );
    render(
        <AppProviders>
            <FactorExplorerPage />
        </AppProviders>
    );
    expect(await screen.findByText("Private Factor inventory is unavailable.")).toBeInTheDocument();
    expect(
        screen.queryByText("No published private Factor metadata matches this search.")
    ).not.toBeInTheDocument();
    await waitFor(() => {
        expect(calls.some((path) => path.includes("/runs"))).toBe(false);
    });
});

test.each([false, true])(
    "joins the actual descriptor before showing chart support (changed=%s)",
    async (changed) => {
        const sample = await import("../../../../../../test-data/web/chart-studies/query.json");
        const capability = structuredClone(sample.capability);
        const descriptor = capability.descriptor;
        const calculation = {
            kind: descriptor.kind,
            type_reference: {
                kind: descriptor.kind,
                type_id: descriptor.type_id,
                semantic_version: descriptor.semantic_version
            },
            inputs: descriptor.inputs,
            outputs: structuredClone(descriptor.outputs),
            parameters: descriptor.parameters.map((p) => {
                const scalar = (value: unknown) => ({
                    type: value === null ? "NULL" : p.parameter_type,
                    value
                });
                const optionalScalar = (value: unknown) => (value === null ? null : scalar(value));
                return {
                    name: p.name,
                    type: p.parameter_type,
                    required: p.required,
                    default: scalar(p.default),
                    minimum: optionalScalar(p.minimum),
                    maximum: optionalScalar(p.maximum),
                    enum_values: p.enum_values.map(scalar),
                    uppercase: p.uppercase
                };
            }),
            parameter_sweep_allowed: true
        };
        const firstOutput = calculation.outputs[0];
        if (firstOutput === undefined) throw new Error("EXPECTED_DECLARED_OUTPUT");
        if (changed) firstOutput.nullable = !firstOutput.nullable;
        vi.stubGlobal(
            "fetch",
            vi.fn((input: RequestInfo | URL) => {
                const path =
                    typeof input === "string"
                        ? input
                        : input instanceof URL
                          ? input.href
                          : input.url;
                const body = path.includes("/capabilities")
                    ? { schema_version: 2, capabilities: [capability] }
                    : path === "/api/v2/private-assets"
                      ? {
                            schema_version: 1,
                            registry_fingerprint: "a".repeat(64),
                            entries: [],
                            factor_presentations: []
                        }
                      : { schema_version: 2, calculations: [calculation] };
                return Promise.resolve(
                    new Response(JSON.stringify(body), {
                        headers: { "content-type": "application/json", "cache-control": "no-store" }
                    })
                );
            })
        );
        render(
            <AppProviders>
                <FactorExplorerPage />
            </AppProviders>
        );
        expect(
            await screen.findByText(
                changed ? "Chart support unavailable" : "Chart display supported · DISPLAY_ONLY"
            )
        ).toBeInTheDocument();
        if (changed)
            expect(
                screen.queryByText("Chart display supported · DISPLAY_ONLY")
            ).not.toBeInTheDocument();
    }
);

test("searches private name and usage without turning presentation into an exact locator", async () => {
    render(
        <AppProviders>
            <FactorExplorerPage />
        </AppProviders>
    );
    await screen.findByText("价格动量 · 第 1 版");
    const search = screen.getByRole("searchbox", {
        name: "Search calculations and private Factors"
    });
    for (const text of ["价格动量", "观察价格变化", "daily", "private.factor.momentum"]) {
        fireEvent.change(search, { target: { value: text } });
        expect(screen.getByRole("button", { name: /价格动量 · 第 1 版/ })).toBeVisible();
    }
    fireEvent.change(search, { target: { value: "不存在的名称" } });
    expect(
        screen.getByText("No published private Factor metadata matches this search.")
    ).toBeVisible();
    expect(calls.some((path) => path.includes("/private-assets/search"))).toBe(false);
});
test("rejects incomplete or mismatched display projections before displaying successful absence", () => {
    const valid = {
        schema_version: 1,
        registry_fingerprint: "a".repeat(64),
        entries: [entry],
        factor_presentations: [presentation]
    };
    expect(registrySchema.safeParse(valid).success).toBe(true);
    for (const label of [
        { ...presentation, display_version: 0 },
        {
            ...presentation,
            locator: { ...presentation.locator, revision_fingerprint: "f".repeat(64) }
        },
        { ...presentation, display: { ...presentation.display, factor_id: "private.factor.other" } }
    ])
        expect(registrySchema.safeParse({ ...valid, factor_presentations: [label] }).success).toBe(
            false
        );
    expect(registrySchema.safeParse({ ...valid, factor_presentations: [] }).success).toBe(false);
    expect(
        registrySchema.safeParse({ ...valid, factor_presentations: [presentation, presentation] })
            .success
    ).toBe(false);
});

test("failed refresh retains exact content but never presents cached labels as current", async () => {
    function Refresh() {
        const client = useQueryClient();
        return (
            <button
                onClick={() => {
                    void client.invalidateQueries({
                        queryKey: ["calculation-library", "private-assets"]
                    });
                }}
            >
                Refresh inventory
            </button>
        );
    }
    render(
        <AppProviders>
            <FactorExplorerPage />
            <Refresh />
        </AppProviders>
    );
    await screen.findByText("价格动量 · 第 1 版");
    fireEvent.click(screen.getByRole("button", { name: /价格动量 · 第 1 版/ }));
    await screen.findByRole("article", { name: "Exact Factor metadata" });
    const read = vi.mocked(fetch).getMockImplementation();
    if (read === undefined) throw new Error("EXPECTED_FETCH_IMPLEMENTATION");
    vi.mocked(fetch).mockImplementation((input, init) => {
        if (input === "/api/v2/private-assets")
            return Promise.resolve(
                new Response(
                    JSON.stringify({
                        error: {
                            code: "PRIVATE_FACTOR_DISPLAY_UNAVAILABLE",
                            detail: "Display is unavailable"
                        }
                    }),
                    { status: 503, headers: { "cache-control": "no-store" } }
                )
            );
        return read(input, init);
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh inventory" }));
    await screen.findByText("Private Factor inventory is unavailable.");
    expect(screen.getByRole("heading", { name: "所选私有因子 · 第 1 版" })).toBeVisible();
    expect(
        screen.getByText("当前名称和用途不可用，请重试目录读取；所选精确内容未被替换。")
    ).toBeVisible();
    expect(screen.queryByText("观察价格变化")).not.toBeInTheDocument();
    expect(
        screen.queryByText("No published private Factor metadata matches this search.")
    ).not.toBeInTheDocument();
    expect(screen.getByText(revision)).toBeInTheDocument();
    expect(calls.filter((path) => path.includes("/private-assets/factors/"))).toHaveLength(1);
});
