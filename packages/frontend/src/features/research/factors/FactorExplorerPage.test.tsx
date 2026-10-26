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
                    ? { schema_version: 1, registry_fingerprint: "a".repeat(64), entries: [entry] }
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
    expect(await screen.findByText("private.factor.momentum @2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Configure Research · unavailable" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run Research" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open published results" })).toBeDisabled();
    expect(calls.some((path) => /\/runs|\/results|\/resolve/.test(path))).toBe(false);
    expect(calls.some((path) => path.includes("/factors/"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /private.factor.momentum @2/ }));
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
                      ? { schema_version: 1, registry_fingerprint: "a".repeat(64), entries: [] }
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
