import { z } from "zod";
import type { components } from "./generated";

type Dto<Name extends keyof components["schemas"]> = components["schemas"][Name];

const sha256 = z.string().regex(/^[0-9a-f]{64}$/);
const decimal = z.string().regex(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/);
const integer = z.string().regex(/^(?:0|-?[1-9][0-9]*)$/);
const nonnegative = z.number().int().nonnegative();
const positive = z.number().int().positive();

const referenceSchema = z.strictObject({
    calculation_fingerprint: sha256,
    node_fingerprint: sha256,
    output_name: z.string().min(1)
});

const numericSchema = z.strictObject({
    representation: z.string().min(1),
    precision: positive,
    output_quantum: decimal,
    rounding: z.string().min(1)
});

const definitionSchema = z.strictObject({
    method: z.string().min(1),
    minimum_observations: z.number().int().min(2),
    pairing_policy: z.string().min(1),
    universe_policy: z.string().min(1),
    rank_tie_method: z.string().min(1),
    weighting: z.string().min(1),
    numeric: numericSchema
});

export const statisticsDescriptorSchema = z.strictObject({
    statistics_fingerprint: sha256,
    statistics_result_fingerprint: sha256,
    result_content_fingerprint: sha256,
    statistics_result_schema_version: positive,
    row_count: nonnegative,
    feature: referenceSchema,
    target: referenceSchema,
    definition: definitionSchema
}) satisfies z.ZodType<Dto<"ResearchStatisticsDescriptorDto">>;

export const artifactSummarySchema = z.strictObject({
    schema_version: z.literal(2),
    research_result_plan_fingerprint: sha256,
    research_result_content_fingerprint: sha256,
    research_result_fingerprint: sha256,
    dataset_snapshot_fingerprint: sha256,
    artifact_content_fingerprint: sha256,
    research_result_schema_version: positive,
    artifact_profile: z.string().min(1),
    artifact_schema_version: positive,
    statistics_count: nonnegative,
    row_count: nonnegative,
    created_at: z.iso.datetime({ offset: true })
}) satisfies z.ZodType<Dto<"ResearchArtifactSummaryDto">>;

export const statisticsCatalogSchema = z.strictObject({
    schema_version: z.literal(2),
    research_result_fingerprint: sha256,
    statistics: z.array(statisticsDescriptorSchema)
}) satisfies z.ZodType<Dto<"ResearchStatisticsCatalogDto">>;

export const statisticPointSchema = z.strictObject({
    ts_event_ns: integer,
    statistic_value: decimal.nullable(),
    sample_count: nonnegative,
    status: z.string().min(1)
}) satisfies z.ZodType<Dto<"ResearchStatisticPointDto">>;

export const statisticSeriesPageSchema = z.strictObject({
    schema_version: z.literal(2),
    research_result_fingerprint: sha256,
    statistics_fingerprint: sha256,
    points: z.array(statisticPointSchema),
    has_more: z.boolean(),
    next_after_ts_event_ns: integer.nullable()
}) satisfies z.ZodType<Dto<"ResearchStatisticSeriesPageDto">>;

export const researchErrorSchema = z.strictObject({
    schema_version: z.literal(2),
    code: z.enum([
        "INVALID_QUERY",
        "INVALID_TIME_RANGE",
        "INVALID_PAGE_LIMIT",
        "RESEARCH_ARTIFACT_NOT_FOUND",
        "RESEARCH_ARTIFACT_CORRUPT",
        "STATISTICS_NOT_FOUND"
    ]),
    detail: z.string().min(1)
}) satisfies z.ZodType<Dto<"ResearchErrorDto">>;

const uuid4 = z
    .string()
    .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
const timestamp = z.iso.datetime({ offset: true });
const runState = z.enum([
    "QUEUED",
    "RUNNING",
    "CANCEL_REQUESTED",
    "COMPLETED",
    "FAILED",
    "CANCELLED"
]);
const runFailureSchema = z.strictObject({
    phase: z.string().min(1),
    code: z.string().min(1),
    detail: z.string().min(1)
});
const runSummaryShape = {
    schema_version: z.literal(2),
    run_id: uuid4,
    revision: z.string().regex(/^(?:0|[1-9][0-9]*)$/),
    state: runState,
    specification_schema_version: positive,
    specification_fingerprint: sha256,
    admission_resolution_fingerprint: sha256,
    queued_at: timestamp,
    started_at: timestamp.nullable(),
    cancel_requested_at: timestamp.nullable(),
    finished_at: timestamp.nullable(),
    result_ref: sha256.nullable(),
    artifact_ref: sha256.nullable(),
    failure: runFailureSchema.nullable()
} as const;

export const researchRunSummarySchema = z.strictObject(runSummaryShape) satisfies z.ZodType<
    Dto<"ResearchRunSummaryDto">
>;

export const researchRunSchema = z.strictObject({
    ...runSummaryShape,
    specification: z.record(z.string(), z.unknown())
}) satisfies z.ZodType<Dto<"ResearchRunDto">>;

export const researchRunPageSchema = z.strictObject({
    schema_version: z.literal(2),
    runs: z.array(researchRunSummarySchema),
    has_more: z.boolean(),
    next_cursor: z.string().min(1).nullable()
}) satisfies z.ZodType<Dto<"ResearchRunPageDto">>;

export const researchRunSubmissionSchema = z.strictObject({
    submission_disposition: z.enum(["CREATED", "REUSED"]),
    run: researchRunSchema
}) satisfies z.ZodType<Dto<"SubmitResearchRunResponse">>;

export const researchRunErrorSchema = z.strictObject({
    error: z.strictObject({
        phase: z.string().min(1),
        code: z.string().min(1),
        detail: z.string().min(1)
    })
}) satisfies z.ZodType<Dto<"ResearchRunErrorEnvelopeDto">>;

const researchScalarSchema = z.strictObject({
    type: z.enum(["NULL", "BOOLEAN", "INTEGER", "DECIMAL", "STRING"]),
    value: z.union([z.boolean(), z.number().int(), z.string(), z.null()])
});
const calculationTypeReferenceSchema = z.strictObject({
    kind: z.enum(["INDICATOR", "FACTOR", "TARGET"]),
    type_id: z.string().min(1),
    semantic_version: z.string().min(1)
});
const calculationPortSchema = z.strictObject({
    name: z.string().min(1),
    data_type: z.string().min(1),
    nullable: z.boolean(),
    semantic_type: z.string().min(1),
    dimensions: z.array(z.string().min(1)),
    unit: z.string().nullable()
});
const calculationParameterSchema = z.strictObject({
    name: z.string().min(1),
    type: z.string().min(1),
    required: z.boolean(),
    default: researchScalarSchema,
    minimum: researchScalarSchema.nullable(),
    maximum: researchScalarSchema.nullable(),
    enum_values: z.array(researchScalarSchema),
    uppercase: z.boolean()
});

export const researchCalculationCatalogSchema = z.strictObject({
    schema_version: z.literal(2),
    calculations: z.array(
        z.strictObject({
            kind: z.string().min(1),
            type_reference: calculationTypeReferenceSchema,
            parameters: z.array(calculationParameterSchema),
            inputs: z.array(calculationPortSchema),
            outputs: z.array(calculationPortSchema),
            parameter_sweep_allowed: z.boolean()
        })
    )
}) satisfies z.ZodType<Dto<"ResearchCalculationCatalogDto">>;

export const researchDatasetFieldCatalogSchema = z.strictObject({
    schema_version: z.literal(2),
    dataset_fields: z.array(
        z.strictObject({
            source: z.string().min(1),
            field_name: z.string().min(1),
            data_type: z.string().min(1),
            semantic_roles: z.array(z.string().min(1)),
            dimensions: z.array(z.string().min(1)),
            unit: z.string().nullable()
        })
    )
}) satisfies z.ZodType<Dto<"ResearchDatasetFieldCatalogDto">>;

export const researchUniverseCatalogSchema = z.strictObject({
    schema_version: z.literal(2),
    selection_kinds: z.array(z.string().min(1)),
    registered_universes: z.array(
        z.strictObject({
            registered_id: z.string().min(1),
            kind: z.string().min(1),
            display_metadata: z.record(z.string(), z.unknown())
        })
    )
}) satisfies z.ZodType<Dto<"ResearchUniverseCatalogDto">>;

export const researchStatisticsCapabilityCatalogSchema = z.strictObject({
    schema_version: z.literal(2),
    statistics: z.array(
        z.strictObject({
            statistic_type: z.string().min(1),
            variable_kinds: z.array(z.string().min(1)),
            variable_semantic_roles: z.array(z.string().min(1)),
            target_semantic_roles: z.array(z.string().min(1)),
            target_required: z.boolean(),
            executable: z.boolean()
        })
    )
}) satisfies z.ZodType<Dto<"ResearchStatisticsCapabilityCatalogDto">>;

const definitionCandidateSchema = z.strictObject({
    ordinal: nonnegative,
    candidate_fingerprint: sha256,
    assignment: z.record(z.string(), researchScalarSchema),
    calculation_fingerprint: sha256,
    graph_fingerprint: sha256
});

export const researchDefinitionResolutionSchema = z.strictObject({
    schema_version: z.literal(2),
    authoring_definition_fingerprint: sha256,
    resolved_definition_fingerprint: sha256,
    dataset_snapshot_fingerprint: sha256,
    specification_fingerprint: sha256,
    resolved_dataset_definition: z.record(z.string(), z.unknown()),
    instrument_count: positive,
    candidate_count: positive,
    candidates: z.array(definitionCandidateSchema),
    published_variables: z.array(
        z.strictObject({
            instance_key: z.string().min(1),
            output_name: z.string().min(1),
            data_type: z.string().min(1),
            semantic_type: z.string().min(1)
        })
    ),
    exact_specification: z.record(z.string(), z.unknown()),
    diagnostics: z.array(z.unknown())
}) satisfies z.ZodType<Dto<"ResearchDefinitionResolutionDto">>;

export const researchDefinitionErrorSchema = z.strictObject({
    error: z.strictObject({
        phase: z.string().min(1),
        code: z.string().min(1),
        path: z.string().min(1),
        detail: z.string().min(1)
    })
}) satisfies z.ZodType<Dto<"ResearchDefinitionErrorEnvelopeDto">>;

export type ArtifactSummaryTransport = z.infer<typeof artifactSummarySchema>;
export type StatisticsCatalogTransport = z.infer<typeof statisticsCatalogSchema>;
export type StatisticSeriesPageTransport = z.infer<typeof statisticSeriesPageSchema>;
export type ResearchRunTransport = z.infer<typeof researchRunSchema>;
export type ResearchRunSummaryTransport = z.infer<typeof researchRunSummarySchema>;
export type ResearchRunPageTransport = z.infer<typeof researchRunPageSchema>;
export type ResearchRunSubmissionTransport = z.infer<typeof researchRunSubmissionSchema>;
export type ResearchCalculationCatalogTransport = z.infer<typeof researchCalculationCatalogSchema>;
export type ResearchDatasetFieldCatalogTransport = z.infer<
    typeof researchDatasetFieldCatalogSchema
>;
export type ResearchUniverseCatalogTransport = z.infer<typeof researchUniverseCatalogSchema>;
export type ResearchStatisticsCapabilityCatalogTransport = z.infer<
    typeof researchStatisticsCapabilityCatalogSchema
>;
export type ResearchDefinitionResolutionTransport = z.infer<
    typeof researchDefinitionResolutionSchema
>;
export type ResearchDefinitionTransport = Dto<"ResearchDefinitionRequestDto">;
