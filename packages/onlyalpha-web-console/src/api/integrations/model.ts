import { z } from "zod";
import type { components } from "../research/generated";

type Dto<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type IntegrationType = Dto<"IntegrationTypeDto">;
export type Integration = Dto<"IntegrationDto">;
export type IntegrationSummary = Dto<"IntegrationSummaryDto">;
export type IntegrationDraft = Dto<"IntegrationDraftDto">;
export type IntegrationCommandResponse = Dto<"IntegrationCommandResponseDto">;
export type IntegrationOperationalStatus = Dto<"IntegrationOperationalStatusDto">;
export type IntegrationProbeAttempt = Dto<"IntegrationProbeAttemptDto">;
export type IntegrationRevisionSummary = Dto<"IntegrationRevisionSummaryDto">;

const sha256 = z.string().regex(/^[0-9a-f]{64}$/);
const jsonRecord = z.record(z.string(), z.json());
const lifecycle = z.enum(["ACTIVE", "DISABLED", "ARCHIVED"]);
const category = z.enum(["DATA_SOURCE", "BROKER", "AGENT_PROVIDER"]);
const valueKind = z.enum([
    "STRING",
    "INTEGER",
    "NUMBER",
    "BOOLEAN",
    "ENUM",
    "DURATION",
    "PATH",
    "STRING_INTEGER_MAP"
]);

const fieldSchema = z.strictObject({
    field_id: z.string().min(1),
    display_name: z.string().min(1),
    description: z.string(),
    value_kind: valueKind,
    required: z.boolean(),
    secret: z.boolean(),
    advanced: z.boolean(),
    default: z.union([z.string(), z.number(), z.boolean(), z.null()]),
    enum_values: z.array(z.string()),
    minimum: z.number().nullable(),
    maximum: z.number().nullable(),
    exclusive_minimum: z.boolean()
});

export const integrationTypeSchema = z.strictObject({
    schema_version: z.literal(1),
    type_id: z.string().min(1),
    category,
    display_name: z.string().min(1),
    description: z.string(),
    provider_id: z.string().min(1),
    implementation_id: z.string().min(1),
    implementation_version: z.string().min(1),
    public_api_version: z.string().min(1),
    capabilities: z.array(z.string()),
    configuration_contract: z.strictObject({
        schema_version: z.literal(1),
        fingerprint: sha256,
        fields: z.array(fieldSchema)
    }),
    probe_contract: z
        .strictObject({
            probe_version: z.literal(1),
            probe_mode: z.literal("DEFAULT_INSTRUMENT"),
            default_probe_instrument: z.string().nullable(),
            user_selectable_probe_instrument: z.boolean(),
            probe_checks: z.array(
                z.enum([
                    "CONNECTIVITY",
                    "AUTHENTICATION",
                    "REFERENCE_DATA",
                    "HISTORICAL_DATA",
                    "REALTIME_DATA"
                ])
            ),
            fingerprint: sha256
        })
        .nullable(),
    fingerprint: sha256
}) satisfies z.ZodType<IntegrationType>;

const integrationSchema = z.strictObject({
    schema_version: z.literal(1),
    integration_id: z.uuid(),
    type_id: z.string().min(1),
    display_name: z.string().min(1),
    lifecycle_state: lifecycle,
    current_revision_fingerprint: sha256.nullable(),
    created_at: z.string().min(1),
    updated_at: z.string().min(1)
});

const summarySchema = integrationSchema.extend({
    category,
    draft_version: z.number().int().positive(),
    pinned_type_descriptor_fingerprint: sha256
});

const secretStatusSchema = z.strictObject({
    field_id: z.string().min(1),
    configured: z.boolean(),
    generation: z.number().int().positive().nullable()
});

export const integrationDraftSchema = z.strictObject({
    schema_version: z.literal(1),
    integration_id: z.uuid(),
    base_revision_fingerprint: sha256.nullable(),
    pinned_type_descriptor_fingerprint: sha256,
    type_descriptor: integrationTypeSchema,
    public_configuration: jsonRecord,
    probe_configuration: jsonRecord.nullable(),
    draft_version: z.number().int().positive(),
    draft_fingerprint: sha256,
    secret_statuses: z.array(secretStatusSchema),
    created_at: z.string().min(1),
    updated_at: z.string().min(1)
}) satisfies z.ZodType<IntegrationDraft>;

const checkSchema = z.strictObject({
    check: z.string().min(1),
    status: z.enum(["PASS", "FAIL", "SKIPPED"]),
    latency_ms: z.number().int().nonnegative(),
    failure_kind: z.enum(["DEGRADED", "OFFLINE", "FAILED"]).nullable(),
    error_code: z.string().nullable(),
    detail: z.string(),
    observations: z.array(z.string())
});

export const probeAttemptSchema = z.strictObject({
    schema_version: z.literal(1),
    probe_attempt_id: z.uuid(),
    integration_id: z.uuid(),
    revision_fingerprint: sha256,
    type_id: z.string().min(1),
    type_descriptor_fingerprint: sha256,
    probe_contract_fingerprint: sha256,
    probe_configuration_fingerprint: sha256.nullable(),
    runtime_configuration_fingerprint: sha256,
    started_at: z.string().min(1),
    completed_at: z.string().min(1),
    overall_status: z.enum(["READY", "DEGRADED", "OFFLINE", "FAILED"]),
    probe_instrument: z.string().nullable(),
    checks: z.array(checkSchema)
}) satisfies z.ZodType<IntegrationProbeAttempt>;

export const schemas = {
    types: z.strictObject({ items: z.array(integrationTypeSchema) }),
    integrations: z.strictObject({ items: z.array(summarySchema) }),
    integration: integrationSchema,
    draft: integrationDraftSchema,
    command: z.strictObject({
        schema_version: z.literal(1),
        command_id: z.uuid(),
        integration_id: z.uuid(),
        replayed: z.boolean(),
        outcome_kind: z.string(),
        outcome_id: z.string()
    }),
    operational: z.strictObject({
        schema_version: z.literal(1),
        integration_id: z.uuid(),
        revision_fingerprint: sha256.nullable(),
        status: z.enum(["UNKNOWN", "READY", "DEGRADED", "OFFLINE", "FAILED"]),
        probe_attempt_id: z.uuid().nullable(),
        checked_at: z.string().nullable(),
        probe_supported: z.boolean()
    }),
    attempt: probeAttemptSchema,
    attempts: z.strictObject({ items: z.array(probeAttemptSchema) }),
    revisions: z.strictObject({
        items: z.array(
            z.strictObject({
                revision_fingerprint: sha256,
                revision_sequence: z.number().int().positive(),
                type_id: z.string(),
                type_descriptor_fingerprint: sha256,
                configuration_fingerprint: sha256,
                runtime_configuration_fingerprint: sha256,
                probe_configuration_fingerprint: sha256.nullable(),
                secret_binding_fingerprint: sha256,
                created_at: z.string().min(1)
            })
        )
    }),
    error: z.strictObject({
        schema_version: z.literal(1),
        error: z.strictObject({ code: z.string().min(1), detail: z.string() })
    })
};
