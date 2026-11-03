import { z } from "zod";
import { registry } from "../../api/privateAssets/client";
import { request } from "../factorChat/api";
import { preparationSchema } from "../backtest/api";
import { draftSchema, saveAuthoredDefinition } from "./api";
export { loadWorkflow, loadWorkflows, pendingManualDefinition } from "./api";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
export const factorLocator = z.strictObject({
    private_asset_kind: z.literal("FACTOR"),
    private_asset_id: z.string().min(1),
    revision_fingerprint: sha,
    content_fingerprint: sha
});
export type FactorLocator = z.infer<typeof factorLocator>;
const contextSchema = z.strictObject({
    schema_version: z.literal(1),
    factor_locator: factorLocator,
    factor_name: z.string(),
    formula: z.string().nullable(),
    draft: draftSchema,
    release_manifest_fingerprint: sha,
    expected_active_generation: sha.nullable(),
    initialize_fresh_runtime: z.literal(false),
    existing_preparations: z.array(preparationSchema)
});
export type ManualContext = z.infer<typeof contextSchema>;
function same(left: unknown, right: unknown) {
    return JSON.stringify(left) === JSON.stringify(right);
}
export async function loadFactors() {
    const value = await request("/api/v2/private-assets", registry);
    return value.factor_presentations.map((item) => ({
        locator: factorLocator.parse(item.locator),
        name: item.display.display_name,
        summary: item.display.usage_summary,
        display_version: item.display_version
    }));
}
export async function loadManualContext(
    raw: FactorLocator,
    strategyId?: string
): Promise<ManualContext> {
    const selected = factorLocator.parse(raw);
    const query = new URLSearchParams({
        factor_id: selected.private_asset_id,
        factor_revision_fingerprint: selected.revision_fingerprint,
        factor_content_fingerprint: selected.content_fingerprint,
        ...(strategyId === undefined ? {} : { strategy_id: strategyId })
    });
    const context = await request(
        `/api/v2/backtest/strategy-context?${query.toString()}`,
        contextSchema
    );
    if (
        !same(context.factor_locator, selected) ||
        (strategyId !== undefined && context.draft.strategy_id !== strategyId)
    )
        throw new Error("策略资料与所选因子不一致，请重新查看。");
    return context;
}
export async function saveManualDefinition(raw: ManualContext, name: string) {
    const context = contextSchema.parse(raw);
    const locator = context.factor_locator;
    return saveAuthoredDefinition(
        { ...context.draft, description: name.trim() },
        {
            kind: "MANUAL_FACTOR",
            factor_id: locator.private_asset_id,
            revision_fingerprint: locator.revision_fingerprint,
            content_fingerprint: locator.content_fingerprint
        }
    );
}
