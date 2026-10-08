import { z } from "zod";
import type { components } from "./generated";

type Dto<N extends keyof components["schemas"]> = components["schemas"][N];
const sha = z.string().regex(/^[0-9a-f]{64}$/);
const text = z.string().min(1);
const kind = z.enum(["INDICATOR", "FACTOR", "TARGET", "PREDICATE"]);
const providerKind = z.enum(["OPERATOR", "INDICATOR", "FACTOR", "STRATEGY"]);
const backend = z.enum(["RESEARCH", "TRADING"]);
const scalar = z.union([z.string(), z.number().int(), z.boolean(), z.null()]);
const parameter = z.strictObject({
    name: text,
    parameter_type: z.enum(["INTEGER", "DECIMAL", "STRING", "BOOLEAN"]),
    required: z.boolean(),
    default: scalar,
    minimum: scalar,
    maximum: scalar,
    enum_values: z.array(scalar),
    uppercase: z.boolean()
});
const port = z.strictObject({
    name: text,
    data_type: z.enum(["DECIMAL", "INTEGER", "BOOLEAN", "STRING"]),
    nullable: z.boolean(),
    dimensions: z.array(text),
    semantic_type: text,
    unit: z.string().nullable()
});
const descriptor = z.strictObject({
    kind,
    type_id: text,
    semantic_version: text,
    parameters: z.array(parameter),
    inputs: z.array(port),
    outputs: z.array(port).min(1),
    missing_values: z.enum(["FAIL", "SKIP", "PROPAGATE", "RESET"]),
    timestamp: z.enum([
        "BAR_OPEN",
        "BAR_CLOSE",
        "EVENT_TIME",
        "OBSERVATION_TIME",
        "AVAILABILITY_TIME"
    ]),
    numeric: z.strictObject({
        representation: text,
        precision: z.number().int().positive(),
        output_quantum: z.string().nullable(),
        rounding: text
    }),
    factor_kind: z.enum(["TIME_SERIES", "CROSS_SECTION"]).nullable(),
    execution_shape: z.enum(["TIME_SERIES", "CROSS_SECTION"]),
    semantic_bounds: z.record(text, z.tuple([z.string(), z.string()]).nullable())
});
const capability = z.strictObject({
    provider_id: text,
    provider_version: text,
    provider_kind: providerKind,
    kind,
    type_id: text,
    semantic_version: text,
    backend,
    type_descriptor: descriptor,
    implementation_fingerprint: sha,
    state_capability: z.enum(["STATELESS", "CHECKPOINTABLE"]).nullable(),
    checkpoint_schema_version: z.number().int().positive().nullable()
});
const activeSchema = z.strictObject({
    schema_version: z.literal(1),
    runtime_generation_fingerprint: sha
}) satisfies z.ZodType<Dto<"ActiveRuntimeGenerationDto">>;
const runtimeSchema = activeSchema.extend({
    catalog_generation_fingerprint: sha
}) satisfies z.ZodType<Dto<"ExactRuntimeGenerationDto">>;
const jsonObject = z.record(z.string(), z.json());
const catalogSchema = z.strictObject({
    schema_version: z.literal(1),
    catalog_generation_fingerprint: sha,
    ordered_providers: z.array(
        z.strictObject({
            provider_id: text,
            provider_version: text,
            kind: providerKind,
            provider_source: jsonObject,
            provider_content_fingerprint: sha
        })
    ),
    ordered_calculation_capabilities: z.array(capability),
    ordered_dataset_field_contracts: z.array(jsonObject),
    ordered_registered_universes: z.array(jsonObject),
    ordered_statistics_capabilities: z.array(jsonObject),
    projection_fingerprint: sha,
    projection_schema_fingerprint: sha
}) satisfies z.ZodType<Dto<"ExactCatalogContextResponseDto">>;
const readinessRow = z.strictObject({
    schema_version: z.literal(1),
    catalog_generation_fingerprint: sha,
    provider_id: text,
    provider_version: text,
    provider_kind: providerKind,
    kind,
    type_id: text,
    semantic_version: text,
    backend,
    implementation_fingerprint: sha,
    readiness_contract_versions: z.array(z.number().int().positive()),
    capability_fingerprint: sha
}) satisfies z.ZodType<Dto<"ExactCatalogCalculationReadinessCapabilityDto">>;
const readinessSchema = z.strictObject({
    schema_version: z.literal(1),
    catalog_generation_fingerprint: sha,
    exact_catalog_context_projection_fingerprint: sha,
    exact_catalog_context_projection_schema_fingerprint: sha,
    ordered_calculation_readiness_capabilities: z.array(readinessRow),
    projection_fingerprint: sha,
    projection_schema_fingerprint: sha
}) satisfies z.ZodType<Dto<"ExactCatalogReadinessProjectionResponseDto">>;

export type CatalogCapability = z.infer<typeof capability>;
export interface ChartCatalogEntry {
    readonly capability: CatalogCapability;
    readonly readiness: z.infer<typeof readinessRow> | null;
    readonly availability: "AVAILABLE" | "NOT_CONNECTED" | "UNSUPPORTED";
}
export interface ChartCatalog {
    readonly runtimeGenerationFingerprint: string;
    readonly catalogGenerationFingerprint: string;
    readonly projectionFingerprint: string;
    readonly entries: readonly ChartCatalogEntry[];
}
/** Browser-only handoff, never execution/admission evidence or a persisted study. */
export interface ChartCalculationDraft {
    readonly catalog: ChartCatalog;
    readonly entry: ChartCatalogEntry;
}
export class ChartCatalogError extends Error {
    constructor(
        readonly code: "NO_RUNTIME" | "MISSING_CATALOG" | "STALE" | "INVALID" | "TRANSPORT"
    ) {
        super(code);
    }
}

async function read<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
    let response: Response;
    try {
        response = await fetch(`/api/v2/research/${path}`, {
            headers: { Accept: "application/json" },
            ...(signal === undefined ? {} : { signal })
        });
    } catch (error) {
        if (signal?.aborted) throw error;
        throw new ChartCatalogError("TRANSPORT");
    }
    let body: unknown;
    try {
        body = await response.json();
    } catch {
        throw new ChartCatalogError("INVALID");
    }
    if (!response.ok) {
        if (
            path === "runtime-generations/active" &&
            response.status === 503 &&
            z.strictObject({ detail: z.literal("RUNTIME_GENERATION_NOT_ACTIVE") }).safeParse(body)
                .success
        )
            throw new ChartCatalogError("NO_RUNTIME");
        if (path.startsWith("catalog-context/") && response.status === 404)
            throw new ChartCatalogError("MISSING_CATALOG");
        throw new ChartCatalogError("TRANSPORT");
    }
    const result = schema.safeParse(body);
    if (!result.success) throw new ChartCatalogError("INVALID");
    return result.data;
}

export async function readActiveRuntime(signal?: AbortSignal): Promise<string> {
    return (await read("runtime-generations/active", activeSchema, signal))
        .runtime_generation_fingerprint;
}

function identity(
    row: Pick<CatalogCapability, "kind" | "type_id" | "semantic_version" | "backend">
): string {
    return JSON.stringify([row.kind, row.type_id, row.semantic_version, row.backend]);
}
function provider(row: {
    provider_kind: string;
    provider_id: string;
    provider_version: string;
}): string {
    return JSON.stringify([row.provider_kind, row.provider_id, row.provider_version]);
}
function unique(values: readonly string[]): void {
    if (new Set(values).size !== values.length) throw new ChartCatalogError("INVALID");
}

export async function readChartCatalog(signal?: AbortSignal): Promise<ChartCatalog> {
    const runtime = await readActiveRuntime(signal);
    const binding = await read(`runtime-generations/${runtime}`, runtimeSchema, signal);
    if (binding.runtime_generation_fingerprint !== runtime) throw new ChartCatalogError("INVALID");
    const catalogId = binding.catalog_generation_fingerprint;
    const context = await read(`catalog-context/exact/${catalogId}`, catalogSchema, signal);
    const readiness = await read(
        `catalog-context/exact/${catalogId}/readiness`,
        readinessSchema,
        signal
    );
    if (
        context.catalog_generation_fingerprint !== catalogId ||
        readiness.catalog_generation_fingerprint !== catalogId ||
        readiness.exact_catalog_context_projection_fingerprint !== context.projection_fingerprint ||
        readiness.exact_catalog_context_projection_schema_fingerprint !==
            context.projection_schema_fingerprint
    )
        throw new ChartCatalogError("INVALID");
    const providers = context.ordered_providers.map((row) =>
        JSON.stringify([row.kind, row.provider_id, row.provider_version])
    );
    unique(providers);
    const capabilities = context.ordered_calculation_capabilities;
    unique(capabilities.map(identity));
    const rows = readiness.ordered_calculation_readiness_capabilities;
    unique(rows.map(identity));
    for (const row of rows) {
        const owner = capabilities.find((item) => identity(item) === identity(row));
        if (
            row.catalog_generation_fingerprint !== catalogId ||
            owner === undefined ||
            provider(owner) !== provider(row) ||
            owner.implementation_fingerprint !== row.implementation_fingerprint
        )
            throw new ChartCatalogError("INVALID");
        unique(row.readiness_contract_versions.map(String));
    }
    const entries = capabilities.map((item): ChartCatalogEntry => {
        const type = item.type_descriptor;
        if (
            !providers.includes(provider(item)) ||
            type.kind !== item.kind ||
            type.type_id !== item.type_id ||
            type.semantic_version !== item.semantic_version ||
            (item.provider_kind === "FACTOR") !== (item.kind === "FACTOR") ||
            item.provider_kind === "STRATEGY"
        )
            throw new ChartCatalogError("INVALID");
        unique(type.parameters.map((row) => row.name));
        unique(type.inputs.map((row) => row.name));
        unique(type.outputs.map((row) => row.name));
        const witness = rows.find((row) => identity(row) === identity(item)) ?? null;
        return {
            capability: item,
            readiness: witness,
            availability:
                witness === null
                    ? "NOT_CONNECTED"
                    : item.backend === "RESEARCH" &&
                        type.execution_shape === "TIME_SERIES" &&
                        witness.readiness_contract_versions.includes(1)
                      ? "AVAILABLE"
                      : "UNSUPPORTED"
        };
    });
    // Active is mutable. Never publish a mixed-generation response as current.
    if ((await readActiveRuntime(signal)) !== runtime) throw new ChartCatalogError("STALE");
    return {
        runtimeGenerationFingerprint: runtime,
        catalogGenerationFingerprint: catalogId,
        projectionFingerprint: context.projection_fingerprint,
        entries
    };
}
