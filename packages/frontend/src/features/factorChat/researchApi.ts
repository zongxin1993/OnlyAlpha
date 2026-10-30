// Human-only Research preparation and original Run read projections.
import { z } from "zod";
import { studyAdviceSchema } from "./api";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
const revision = z.string().regex(/^(?:0|[1-9][0-9]*)$/);
const estimateSchema = z.strictObject({
    point_status: z.string(),
    value: z.string().nullable(),
    uncertainty_status: z.string(),
    interval: z.tuple([z.string(), z.string()]).nullable(),
    undefined_replicates: z.number().int().nonnegative()
});
const diagnosticsSchema = z.strictObject({
    expected_rows: z.number().int().nonnegative(),
    observed_rows: z.number().int().nonnegative(),
    boundary_excluded: z.number().int().nonnegative(),
    complete_pairs: z.number().int().nonnegative(),
    missing_feature: z.number().int().nonnegative(),
    missing_target: z.number().int().nonnegative(),
    axis_gaps: z.number().int().nonnegative()
});
export const researchRunSchema = z.strictObject({
    schema_version: z.literal(1),
    run_id: z.uuid(),
    state: z.string(),
    revision,
    name_snapshot: z.record(z.string(), z.unknown()),
    current_name: z.string().nullable(),
    accepted_at: z.string(),
    specification_fingerprint: sha,
    runtime_generation_fingerprint: sha,
    report: z
        .strictObject({
            research_result_fingerprint: sha,
            artifact_content_fingerprint: sha,
            instrument_id: z.string(),
            timeframe_minutes: z.number().int().positive(),
            horizon_bars: z.number().int().positive(),
            samples: z.array(
                z.strictObject({
                    role: z.string(),
                    start_at: studyAdviceSchema.shape.start_at,
                    end_at: studyAdviceSchema.shape.end_at,
                    diagnostics: diagnosticsSchema,
                    pearson: estimateSchema,
                    spearman: estimateSchema
                })
            ),
            confidence_bps: z.number().int(),
            expected_block_length: z.number().int(),
            replicates: z.number().int(),
            comparison_count: z.number().int(),
            limitations: z.array(z.string()),
            canonical_artifact: z.string(),
            canonical_specification: z.string()
        })
        .nullable(),
    report_status: z.strictObject({
        state: z.enum(["VERIFIED", "UNAVAILABLE", "NOT_APPLICABLE"]),
        code: z.enum(["RESEARCH_REPORT_UNAVAILABLE"]).nullable()
    }),
    decision_provenance: z.strictObject({
        state: z.enum(["VERIFIED", "UNAVAILABLE", "NOT_CHECKED"]),
        code: z.enum(["HISTORICAL_PROOF_UNAVAILABLE"]).nullable(),
        command_id: z.uuid(),
        group_fingerprint: sha,
        policy_id: z.string(),
        policy_version: z.string()
    }),
    failure: z.unknown().nullable(),
    worker_observation: z.unknown()
});
export const preparationSchema = z.strictObject({
    schema_version: z.literal(1),
    command_id: z.uuid(),
    revision,
    state: z.enum([
        "ACCEPTED",
        "RUNNING",
        "INPUT_PENDING",
        "READY",
        "BLOCKED",
        "UNKNOWN",
        "CANCEL_REQUESTED",
        "CANCELLED"
    ]),
    phase: z.string(),
    study_proposal_fingerprint: sha,
    research_command_id: z.uuid(),
    reserved_run_id: z.uuid(),
    prepared_study_fingerprint: sha.nullable(),
    research_outcome: z.string(),
    run_id: z.uuid().nullable(),
    accepted_at: z.string(),
    advice: studyAdviceSchema,
    detail: z.unknown(),
    readiness: z.strictObject({
        state: z.enum(["VERIFIED", "UNAVAILABLE", "NOT_APPLICABLE"]),
        code: z.string().nullable()
    })
});
export const preparationSummarySchema = preparationSchema.pick({
    command_id: true,
    revision: true,
    state: true,
    study_proposal_fingerprint: true,
    accepted_at: true
});
export const preparationContextSchema = z.strictObject({
    schema_version: z.literal(1),
    study_proposal_fingerprint: sha,
    factor_proposal_fingerprint: sha,
    factor_name: z.string(),
    usage_summary: z.string(),
    source_label: z.string().nullable(),
    advice: studyAdviceSchema,
    is_current: z.boolean(),
    withdrawn: z.boolean(),
    release_manifest_fingerprint: sha,
    backend_version: z.string(),
    algorithm_artifact_fingerprint: sha.nullable(),
    expected_active_generation: sha.nullable(),
    initialize_fresh_runtime: z.boolean(),
    profile: z.unknown(),
    policy: z.unknown(),
    new_work_status: z.strictObject({
        state: z.enum(["AVAILABLE", "UNAVAILABLE"]),
        code: z.string().nullable()
    }),
    existing_preparations: z.array(preparationSummarySchema)
});
export const confirmationSchema = z.strictObject({
    schema_version: z.literal(1),
    research_command_id: z.uuid(),
    state: z.enum(["ACCEPTED", "OUTCOME_UNKNOWN"]),
    run_id: z.uuid().nullable()
});
export const prepareInputSchema = z.strictObject({
    schema_version: z.literal(1),
    study_proposal_fingerprint: sha,
    release_manifest_fingerprint: sha,
    expected_active_generation: sha.nullable(),
    initialize_fresh_runtime: z.boolean(),
    research_command_id: z.uuid()
});
export const researchPendingSchema = z.discriminatedUnion("kind", [
    z.strictObject({ kind: z.literal("prepare"), command: z.uuid(), body: prepareInputSchema }),
    z.strictObject({
        kind: z.literal("confirm"),
        command: z.uuid(),
        body: z.strictObject({
            schema_version: z.literal(1),
            preparation_command_id: z.uuid(),
            prepared_study_fingerprint: sha
        })
    }),
    z.strictObject({
        kind: z.enum(["resume", "cancel-preparation"]),
        command: z.uuid(),
        body: z.strictObject({
            schema_version: z.literal(1),
            preparation_command_id: z.uuid(),
            expected_revision: revision
        })
    }),
    z.strictObject({
        kind: z.literal("cancel-run"),
        command: z.uuid(),
        body: z.strictObject({ schema_version: z.literal(1), run_id: z.uuid() })
    })
]);
