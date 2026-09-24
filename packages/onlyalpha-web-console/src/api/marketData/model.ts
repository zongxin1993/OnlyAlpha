import { z } from "zod";

const sha256 = z.string().regex(/^[0-9a-f]{64}$/);

export const marketDataSourceSelectionSchema = z.strictObject({
    integration_id: z.string().min(1),
    integration_revision_fingerprint: sha256,
    type_id: z.string().min(1),
    source_id: z.string().min(1)
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
    start_ns: z.number().int(),
    end_ns: z.number().int()
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
    bar_start_ns: z.number().int(),
    bar_end_ns: z.number().int(),
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
    source_id: z.string().min(1),
    type_id: z.string().min(1),
    instruments: z.array(marketDataInstrumentSchema)
});

export const marketDataBarsSchema = z.strictObject({
    schema_version: z.literal(1),
    source_selection: marketDataSourceSelectionSchema,
    instrument_id: z.string().min(1),
    display_symbol: z.string().min(1),
    venue: z.string().min(1),
    market: z.string().min(1),
    bar_specification: z.string().min(1),
    aggregation_source: z.string().min(1),
    adjustment: z.string().min(1),
    closed_only: z.boolean(),
    start_ns: z.number().int(),
    end_ns: z.number().int(),
    coverage: marketDataCoverageSchema,
    revision_id: z.string().nullable(),
    revision_fingerprint: sha256.nullable(),
    seal_id: z.string().nullable(),
    bars: z.array(marketDataBarSchema)
});

export const marketDataAcquisitionSchema = z.strictObject({
    schema_version: z.literal(1),
    acquisition_id: z.string().min(1),
    status: z.enum(["PENDING", "RUNNING", "COMPLETE", "FAILED"]),
    source_id: z.string().min(1),
    integration_binding_fingerprint: sha256.nullable(),
    instrument_id: z.string().min(1),
    bar_specification: z.string().min(1),
    start_ns: z.number().int(),
    end_ns: z.number().int(),
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
export type MarketDataInstrument = z.infer<typeof marketDataInstrumentSchema>;
export type MarketDataCoverage = z.infer<typeof marketDataCoverageSchema>;
export type MarketDataCoverageGap = z.infer<typeof marketDataCoverageGapSchema>;
export type MarketDataBar = z.infer<typeof marketDataBarSchema>;
export type MarketDataBars = z.infer<typeof marketDataBarsSchema>;
export type MarketDataAcquisition = z.infer<typeof marketDataAcquisitionSchema>;
