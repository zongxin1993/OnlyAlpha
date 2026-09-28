import { z } from "zod";

export { marketDataBarsSchema } from "./http.generated";
export type { MarketDataBars } from "./http.generated";

const sha256 = z.string().regex(/^[0-9a-f]{64}$/);
/** Exact nanoseconds travel as canonical decimal strings; JSON numbers lose int64 precision. */
const nanos = z.string().regex(/^(?:0|[1-9][0-9]*)$/);

export const marketDataBarSpecificationSchema = z.strictObject({
    aggregation: z.literal("TIME"),
    step: z.number().int().min(1).max(240),
    price_type: z.literal("LAST")
});
export type MarketDataBarSpecification = z.infer<typeof marketDataBarSpecificationSchema>;
export const marketDataBarSpecification = (step: number): MarketDataBarSpecification =>
    marketDataBarSpecificationSchema.parse({ aggregation: "TIME", step, price_type: "LAST" });
export const formatBarSpecification = (spec: MarketDataBarSpecification): string =>
    spec.step % 60 === 0 ? `${String(spec.step / 60)}H` : `${String(spec.step)}m`;

/** Client request reference. The browser asserts no canonical Market Source identity. */
export const marketDataSourceReferenceSchema = z.strictObject({
    integration_id: z.string().min(1),
    integration_revision_fingerprint: sha256,
    expected_type_id: z.string().min(1).optional()
});

/** Server-derived canonical Market Source identity reported back by the Product API. */
export const marketDataSourceSelectionSchema = z.strictObject({
    integration_id: z.string().min(1),
    integration_revision_fingerprint: sha256,
    type_id: z.string().min(1),
    source_id: z.string().min(1),
    environment: z.string().min(1)
});

export const marketDataSourceSchema = z.strictObject({
    integration_id: z.string().min(1),
    integration_revision_fingerprint: sha256,
    display_name: z.string().min(1),
    type_id: z.string().min(1),
    source_id: z.string().min(1),
    environment: z.string().min(1),
    time_bar_capability: z.strictObject({
        aggregation: z.literal("TIME"),
        external_base_step_minutes: z.literal(1),
        derived_supported: z.boolean(),
        minimum_step_minutes: z.number().int().positive(),
        maximum_step_minutes: z.number().int().positive()
    })
});

export const marketDataSourceListSchema = z.strictObject({
    schema_version: z.literal(1),
    sources: z.array(marketDataSourceSchema)
});

export const marketDataInstrumentSchema = z.strictObject({
    instrument_id: z.string().min(1),
    display_symbol: z.string().min(1),
    venue: z.string().min(1),
    market: z.string().min(1),
    asset_class: z.string().min(1),
    instrument_type: z.string().min(1),
    status: z.string().min(1),
    market_data_capabilities: z.array(z.string())
});

export const marketDataCoverageGapSchema = z.strictObject({
    start_ns: nanos,
    end_ns: nanos
});

export const marketDataCoverageSchema = z.strictObject({
    status: z.enum(["COMPLETE", "INCOMPLETE", "UNPROVABLE"]),
    manifest_id: z.string().nullable(),
    manifest_fingerprint: sha256.nullable(),
    expected_bar_count: z.number().int(),
    actual_bar_count: z.number().int(),
    issues: z.array(z.string()),
    gaps: z.array(marketDataCoverageGapSchema),
    planned_acquisition_ranges: z.array(marketDataCoverageGapSchema)
});

export const marketDataBarSchema = z.strictObject({
    bar_start_ns: nanos,
    bar_end_ns: nanos,
    open: z.string(),
    high: z.string(),
    low: z.string(),
    close: z.string(),
    volume: z.string(),
    closed: z.boolean()
});

export const marketDataInstrumentListSchema = z.strictObject({
    schema_version: z.literal(1),
    source_selection: marketDataSourceSelectionSchema,
    instruments: z.array(marketDataInstrumentSchema)
});

export const marketDataAcquisitionSchema = z.strictObject({
    schema_version: z.literal(1),
    acquisition_id: z.string().min(1),
    status: z.enum(["PENDING", "RUNNING", "COMPLETE", "FAILED"]),
    source_id: z.string().min(1),
    integration_binding_fingerprint: sha256.nullable(),
    instrument_id: z.string().min(1),
    bar_specification: marketDataBarSpecificationSchema,
    start_ns: nanos,
    end_ns: nanos,
    provenance: z.string().min(1),
    coverage: marketDataCoverageSchema,
    revision_id: z.string().nullable(),
    revision_fingerprint: sha256.nullable(),
    seal_id: z.string().nullable(),
    failure_detail: z.string().nullable()
});

export const marketDataErrorSchema = z.strictObject({
    error: z.strictObject({
        phase: z.enum(["QUERY", "COMMAND"]),
        code: z.string().min(1),
        detail: z.string()
    })
});

export type MarketDataSourceSelection = z.infer<typeof marketDataSourceSelectionSchema>;
export type MarketDataSourceReference = z.infer<typeof marketDataSourceReferenceSchema>;
export type MarketDataSource = z.infer<typeof marketDataSourceSchema>;
export type MarketDataInstrument = z.infer<typeof marketDataInstrumentSchema>;
export type MarketDataCoverage = z.infer<typeof marketDataCoverageSchema>;
export type MarketDataCoverageGap = z.infer<typeof marketDataCoverageGapSchema>;
export type MarketDataBar = z.infer<typeof marketDataBarSchema>;
export type MarketDataAcquisition = z.infer<typeof marketDataAcquisitionSchema>;
