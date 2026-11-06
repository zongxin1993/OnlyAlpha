/** Technical wire conformance only: no server, fixture responses or UI state. */
import { readFileSync } from "node:fs";
import { z } from "zod";
import {
    ChartStudyCapabilitiesSchema,
    ChartStudyEvaluateSchema
} from "../src/api/chartStudies/http.generated";
import {
    marketDataAcquisitionSchema,
    marketDataBarsSchema,
    marketDataInstrumentListSchema,
    marketDataSourceListSchema
} from "../src/api/marketData/model";
import { searchSchema, quotesSchema } from "../src/api/marketData/discovery";
import { marketDataStreamEventSchema } from "../src/api/marketData/stream.generated";
import { registry, revision } from "../src/api/privateAssets/client";
import { researchCalculationCatalogSchema } from "../src/api/research/schemas";
import { probeAttemptSchema } from "../src/api/integrations/model";

// The source owner emits the original document before Product enrichment.
// Reuse the actual Shipping wire schema for its original fields.
const probeResultSchema = probeAttemptSchema
    .pick({
        probe_attempt_id: true,
        integration_id: true,
        revision_fingerprint: true,
        overall_status: true,
        started_at: true,
        completed_at: true,
        probe_instrument: true,
        checks: true
    })
    .extend({
        started_at: z.iso.datetime({ offset: true }),
        completed_at: z.iso.datetime({ offset: true })
    });

const schemas: Readonly<Partial<Record<string, z.ZodType>>> = {
    probe_result: probeResultSchema,
    private_registry: registry,
    private_factor: revision,
    chart_capabilities: ChartStudyCapabilitiesSchema,
    chart_evaluation: ChartStudyEvaluateSchema,
    chart_catalog: researchCalculationCatalogSchema,
    sources: marketDataSourceListSchema,
    instruments: marketDataInstrumentListSchema,
    search: searchSchema,
    quotes: quotesSchema,
    window: marketDataBarsSchema,
    acquisition: marketDataAcquisitionSchema,
    stream: marketDataStreamEventSchema
};
const path = process.argv.at(2);
if (path === undefined) throw new Error("NATIVE_PAYLOAD_FILE_REQUIRED");
const lines = readFileSync(path, "utf8")
    .split("\n")
    .filter((line) => line.length > 0);
if (lines.length === 0) throw new Error("NATIVE_PAYLOAD_FILE_EMPTY");
const counts = new Map<string, number>();
for (const [index, line] of lines.entries()) {
    const frame: unknown = JSON.parse(line);
    if (
        frame === null ||
        typeof frame !== "object" ||
        Array.isArray(frame) ||
        !("kind" in frame) ||
        typeof frame.kind !== "string" ||
        !("value" in frame)
    )
        throw new Error(`NATIVE_PAYLOAD_ENVELOPE_INVALID:${String(index + 1)}`);
    if (!Object.hasOwn(schemas, frame.kind))
        throw new Error(`NATIVE_PAYLOAD_KIND_UNKNOWN:${frame.kind}`);
    const schema = schemas[frame.kind];
    if (schema === undefined) throw new Error(`NATIVE_PAYLOAD_SCHEMA_MISSING:${frame.kind}`);
    try {
        schema.parse(frame.value);
        if (frame.kind === "probe_result") {
            for (const field of ["started_at", "completed_at"] as const) {
                for (const invalidDate of ["not-a-date", "2026-02-30T00:00:00Z"]) {
                    if (
                        schema.safeParse({ ...(frame.value as object), [field]: invalidDate })
                            .success
                    )
                        throw new Error("NATIVE_PROBE_DATETIME_VALIDATION_LOST");
                }
            }
        }
        for (const invalid of [
            null,
            [frame.value],
            { ...(frame.value as object), __unexpected_native_wire_member: true }
        ]) {
            if (schema.safeParse(invalid).success)
                throw new Error("NATIVE_PAYLOAD_STRICTNESS_LOST");
        }
    } catch (error) {
        throw new Error(`NATIVE_PAYLOAD_REJECTED:${String(index + 1)}:${frame.kind}`, {
            cause: error
        });
    }
    counts.set(frame.kind, (counts.get(frame.kind) ?? 0) + 1);
}
for (const kind of Object.keys(schemas)) {
    if (!counts.has(kind)) throw new Error(`NATIVE_PAYLOAD_KIND_MISSING:${kind}`);
}
console.log(JSON.stringify({ frames: lines.length, validated: Object.fromEntries(counts) }));
