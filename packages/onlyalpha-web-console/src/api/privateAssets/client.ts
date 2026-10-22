import { nativeErrorSchema } from "../errors.generated";
import { z } from "zod";
import type { components } from "../research/generated";
import { researchCalculationCatalogSchema } from "../research/schemas";
import { ProductWebError } from "../research/errors";
import type { LocalReadCredentials } from "../marketData/localReadCredentials";

const fingerprint = z.string().regex(/^[0-9a-f]{64}$/);
const locator = z.strictObject({
    private_asset_kind: z.enum(["FACTOR", "STRATEGY"]),
    private_asset_id: z.string().min(1),
    revision_fingerprint: fingerprint,
    content_fingerprint: fingerprint
});
const entry = z.strictObject({
    locator,
    semantic_version: z.string().min(1),
    description: z.string(),
    category: z.string().nullable(),
    tags: z.array(z.string().min(1))
});
export const registry = z
    .strictObject({
        schema_version: z.literal(1),
        registry_fingerprint: fingerprint,
        entries: z.array(entry)
    })
    .superRefine((value, context) => {
        const keys = value.entries.map(
            (item) => `${item.locator.private_asset_kind}:${item.locator.private_asset_id}`
        );
        if (
            new Set(keys).size !== keys.length ||
            keys.some((key, index) => {
                const previous = keys[index - 1];
                return previous !== undefined && key <= previous;
            })
        ) {
            context.addIssue({ code: "custom", message: "PRIVATE_ASSET_REGISTRY_INVALID" });
        }
    });
export const revision = z.strictObject({
    schema_version: z.literal(1),
    factor_id: z.string().min(1),
    semantic_version: z.string().min(1),
    revision_fingerprint: fingerprint,
    parent_revision_fingerprint: fingerprint.nullable(),
    source_text: z.string().min(1),
    source_sha256: fingerprint,
    factor_api_version: z.literal(1),
    factor_api_contract_fingerprint: fingerprint,
    input_contract: z.record(z.string(), z.unknown()),
    parameter_contract: z.record(z.string(), z.unknown()),
    output_contract: z.record(z.string(), z.unknown()),
    description: z.string(),
    economic_rationale: z.string(),
    category: z.string().min(1),
    tags: z.array(z.string().min(1))
});
export type PrivateAssetLocator = components["schemas"]["PrivateAssetLocatorDto"];
export type PrivateAssetRegistry = components["schemas"]["PrivateAssetRegistryDto"];
export type PrivateFactorRevision = components["schemas"]["PrivateFactorRevisionDto"];

export class FetchPrivateAssetsApiClient {
    constructor(private readonly credentials: LocalReadCredentials) {}
    private async read<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
        const captured = this.credentials.capture();
        if (captured.bearer === null && !this.credentials.localSession)
            throw new ProductWebError(
                "UNAUTHORIZED",
                "Sign in to view the calculation library.",
                401,
                "QUERY"
            );
        const response = await fetch(path, {
            cache: "no-store",
            credentials: this.credentials.localSession ? "same-origin" : "omit",
            headers: {
                Accept: "application/json",
                ...(captured.bearer === null ? {} : { Authorization: `Bearer ${captured.bearer}` })
            },
            ...(signal === undefined ? {} : { signal })
        });
        if (!this.credentials.isCurrent(captured.generation) || signal?.aborted)
            throw new ProductWebError("STALE", "The current session changed.", 409, "QUERY");
        const body: unknown = await response.json();
        if (!this.credentials.isCurrent(captured.generation) || signal?.aborted)
            throw new ProductWebError("STALE", "The current session changed.", 409, "QUERY");
        if (!response.ok) {
            const error = nativeErrorSchema.safeParse(body);
            throw new ProductWebError(
                error.success ? error.data.error.code : "CONTRACT_ERROR",
                error.success ? error.data.error.detail : "Metadata is unavailable.",
                response.status,
                "QUERY"
            );
        }
        if (response.headers.get("cache-control") !== "no-store")
            throw new ProductWebError(
                "CONTRACT_ERROR",
                "Metadata response is not admissible.",
                response.status,
                "QUERY"
            );
        const parsed = schema.safeParse(body);
        if (!parsed.success)
            throw new ProductWebError(
                "CONTRACT_ERROR",
                "Metadata response is invalid.",
                response.status,
                "QUERY"
            );
        return parsed.data;
    }
    current(signal?: AbortSignal): Promise<PrivateAssetRegistry> {
        return this.read("/api/v2/private-assets", registry, signal);
    }
    catalog(signal?: AbortSignal) {
        return this.read(
            "/api/v2/research/catalog/calculations",
            researchCalculationCatalogSchema,
            signal
        );
    }
    async factor(
        selected: PrivateAssetLocator,
        signal?: AbortSignal
    ): Promise<PrivateFactorRevision> {
        if (selected.private_asset_kind !== "FACTOR")
            throw new Error("PRIVATE_ASSET_KIND_UNSUPPORTED");
        const value = await this.read(
            `/api/v2/private-assets/factors/${encodeURIComponent(selected.private_asset_id)}/revisions/${selected.revision_fingerprint}?content_fingerprint=${selected.content_fingerprint}`,
            revision,
            signal
        );
        if (
            value.factor_id !== selected.private_asset_id ||
            value.revision_fingerprint !== selected.revision_fingerprint ||
            value.source_sha256 !== selected.content_fingerprint
        )
            throw new ProductWebError(
                "PRIVATE_ASSET_EXACT_READ_MISMATCH",
                "The selected Factor revision does not match.",
                409,
                "QUERY"
            );
        return value;
    }
}
