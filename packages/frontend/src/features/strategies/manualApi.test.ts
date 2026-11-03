import { afterEach, expect, it, vi } from "vitest";
import type { z } from "zod";
import type * as ChatApi from "../factorChat/api";
import { request } from "../factorChat/api";
import * as authoring from "./api";
import { loadFactors, loadManualContext, saveManualDefinition } from "./manualApi";
vi.mock("../factorChat/api", async (original) => ({
    ...(await original<typeof ChatApi>()),
    request: vi.fn()
}));
vi.mock("./api", async (original) => ({
    ...(await original<typeof authoring>()),
    saveAuthoredDefinition: vi.fn()
}));
const sha = "a".repeat(64),
    rev = "b".repeat(64);
const locator = {
    private_asset_kind: "FACTOR" as const,
    private_asset_id: "private.factor.momentum",
    revision_fingerprint: rev,
    content_fingerprint: sha
};
const draft = {
    schema_version: 1 as const,
    strategy_id: "private.strategy.btc_momentum",
    semantic_version: "1",
    base_revision_fingerprint: null,
    definition: { factor: "close" },
    description: "价量动量",
    tags: []
};
const context = {
    schema_version: 1 as const,
    factor_locator: locator,
    factor_name: "价量动量",
    formula: "close",
    draft,
    release_manifest_fingerprint: sha,
    expected_active_generation: sha,
    initialize_fresh_runtime: false as const,
    existing_preparations: []
};
afterEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
});
it("selects the officially published exact factor and presentation without a chat or Study", async () => {
    const calls: string[] = [];
    vi.mocked(request).mockImplementation(<T>(path: string, schema: z.ZodType<T>) => {
        calls.push(path);
        return Promise.resolve(
            schema.parse({
                schema_version: 1,
                registry_fingerprint: sha,
                entries: [
                    {
                        locator,
                        semantic_version: "1",
                        description: "价量动量",
                        category: "动量",
                        tags: []
                    }
                ],
                factor_presentations: [
                    {
                        locator,
                        display: {
                            schema_version: 1,
                            factor_id: locator.private_asset_id,
                            display_name: "价量动量",
                            usage_summary: "1 分钟价格与成交量",
                            edit_number: 1
                        },
                        display_fingerprint: sha,
                        display_version: 1
                    }
                ]
            })
        );
    });
    expect(await loadFactors()).toEqual([
        { locator, name: "价量动量", summary: "1 分钟价格与成交量", display_version: 1 }
    ]);
    expect(calls).toEqual(["/api/v2/private-assets"]);
});
it("requests context by all exact factor pins and optional existing private strategy identity", async () => {
    vi.mocked(request).mockImplementation(<T>(path: string, schema: z.ZodType<T>) => {
        expect(
            Object.fromEntries(new URL(path, "https://workstation.invalid").searchParams)
        ).toEqual({
            factor_id: locator.private_asset_id,
            factor_revision_fingerprint: rev,
            factor_content_fingerprint: sha,
            strategy_id: draft.strategy_id
        });
        expect(path.startsWith("/api/v2/backtest/strategy-context?")).toBe(true);
        return Promise.resolve(schema.parse(context));
    });
    expect(await loadManualContext(locator, draft.strategy_id)).toEqual(context);
});
it.each(["factor", "strategy"])(
    "rejects foreign %s context rather than replacing the selection",
    async (mode) => {
        vi.mocked(request).mockImplementation(<T>(_path: string, schema: z.ZodType<T>) =>
            Promise.resolve(
                schema.parse(
                    mode === "factor"
                        ? {
                              ...context,
                              factor_locator: { ...locator, revision_fingerprint: "c".repeat(64) }
                          }
                        : {
                              ...context,
                              draft: { ...draft, strategy_id: "private.strategy.foreign" }
                          }
                )
            )
        );
        await expect(loadManualContext(locator, draft.strategy_id)).rejects.toThrow();
        expect(authoring.saveAuthoredDefinition).not.toHaveBeenCalled();
    }
);
it("reuses the existing draft and publication commands with an exact Manual Factor binding", async () => {
    const saved = {
        schema_version: 1 as const,
        strategy_id: draft.strategy_id,
        draft,
        draft_fingerprint: sha,
        current_revision_fingerprint: rev,
        revisions: []
    };
    vi.mocked(authoring.saveAuthoredDefinition).mockResolvedValue(saved);
    expect(await saveManualDefinition(context, " BTC 多头 ")).toEqual(saved);
    expect(authoring.saveAuthoredDefinition).toHaveBeenCalledExactlyOnceWith(
        { ...draft, description: "BTC 多头" },
        {
            kind: "MANUAL_FACTOR",
            factor_id: locator.private_asset_id,
            revision_fingerprint: rev,
            content_fingerprint: sha
        }
    );
});
