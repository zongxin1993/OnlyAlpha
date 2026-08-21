import { z } from "zod";
import type { components } from "./generated";

type Dto<Name extends keyof components["schemas"]> = components["schemas"][Name];

const sha256 = z.string().regex(/^[0-9a-f]{64}$/);
const decimal = z.string().regex(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/);
const integer = z.string().regex(/^(?:0|-?[1-9][0-9]*)$/);
const nonnegative = z.number().int().nonnegative();
const positive = z.number().int().positive();
const strictlyIncreasing = (values: readonly bigint[]): boolean =>
    values.every((value, index) => {
        const previous = values[index - 1];
        return previous === undefined || value > previous;
    });
const calculationDataType = z.enum(["DECIMAL", "INTEGER", "BOOLEAN", "STRING"]);
const calculationKind = z.enum(["INDICATOR", "FACTOR", "TARGET"]);
const universeKind = z.enum([
    "SINGLE_INSTRUMENT",
    "EXPLICIT_INSTRUMENT_SET",
    "REGISTERED_POOL",
    "REGISTERED_UNIVERSE"
]);

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

export const artifactSummarySchema = z
    .strictObject({
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
        candidate_count: nonnegative,
        published_series_count: nonnegative,
        signal_series_count: nonnegative,
        market_row_count: nonnegative,
        instrument_ids: z.array(z.string().min(1)),
        created_at: z.iso.datetime({ offset: true })
    })
    .superRefine((value, context) => {
        if (
            new Set(value.instrument_ids).size !== value.instrument_ids.length ||
            value.instrument_ids.join("\0") !== [...value.instrument_ids].sort().join("\0")
        )
            context.addIssue({ code: "custom", message: "Instrument membership is not canonical" });
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

export const statisticSeriesPageSchema = z
    .strictObject({
        schema_version: z.literal(2),
        research_result_fingerprint: sha256,
        statistics_fingerprint: sha256,
        points: z.array(statisticPointSchema),
        has_more: z.boolean(),
        next_after_ts_event_ns: integer.nullable()
    })
    .superRefine((value, context) => {
        const timestamps = value.points.map((point) => BigInt(point.ts_event_ns));
        if (!strictlyIncreasing(timestamps))
            context.addIssue({
                code: "custom",
                message: "Statistics timestamps are not canonical"
            });
        const expected = value.has_more ? value.points.at(-1)?.ts_event_ns : undefined;
        if (value.has_more && expected === undefined)
            context.addIssue({
                code: "custom",
                message: "Statistics page cannot continue from empty evidence"
            });
        if (
            (expected === undefined && value.next_after_ts_event_ns !== null) ||
            (expected !== undefined && value.next_after_ts_event_ns !== expected)
        )
            context.addIssue({ code: "custom", message: "Statistics cursor mismatch" });
    }) satisfies z.ZodType<Dto<"ResearchStatisticSeriesPageDto">>;

const researchCandidateSchema = z
    .strictObject({
        candidate_fingerprint: sha256,
        candidate_calculation_id: z.string().min(1),
        assignment: z.record(
            z.string(),
            z.union([z.boolean(), z.number().int(), z.string(), z.null()])
        ),
        assignment_types: z.record(
            z.string(),
            z.enum(["NULL", "BOOLEAN", "INTEGER", "DECIMAL", "STRING"])
        ),
        calculation_fingerprint: sha256,
        graph_fingerprint: sha256,
        statistics_fingerprints: z.array(sha256),
        signal_roles: z.array(z.string().min(1))
    })
    .superRefine((value, context) => {
        const assignment = Object.keys(value.assignment).sort();
        const types = Object.keys(value.assignment_types).sort();
        if (assignment.join("\0") !== types.join("\0"))
            context.addIssue({ code: "custom", message: "Candidate assignment types mismatch" });
        for (const name of assignment) {
            const item = value.assignment[name];
            const type = value.assignment_types[name];
            const valid =
                (type === "NULL" && item === null) ||
                (type === "BOOLEAN" && typeof item === "boolean") ||
                (type === "INTEGER" && typeof item === "number" && Number.isInteger(item)) ||
                (type === "DECIMAL" &&
                    typeof item === "string" &&
                    decimal.safeParse(item).success) ||
                (type === "STRING" && typeof item === "string");
            if (!valid)
                context.addIssue({
                    code: "custom",
                    message: `Candidate assignment ${name} type mismatch`
                });
        }
        if (new Set(value.statistics_fingerprints).size !== value.statistics_fingerprints.length)
            context.addIssue({
                code: "custom",
                message: "Candidate Statistics membership is duplicated"
            });
        if (new Set(value.signal_roles).size !== value.signal_roles.length)
            context.addIssue({
                code: "custom",
                message: "Candidate Signal membership is duplicated"
            });
    });

export const researchCandidateCatalogSchema = z
    .strictObject({
        schema_version: z.literal(2),
        research_result_fingerprint: sha256,
        candidates: z.array(researchCandidateSchema)
    })
    .superRefine((value, context) => {
        const identities = value.candidates.map((candidate) => candidate.candidate_fingerprint);
        if (new Set(identities).size !== identities.length)
            context.addIssue({ code: "custom", message: "Candidate membership is duplicated" });
    }) satisfies z.ZodType<Dto<"ResearchCandidateCatalogDto">>;

export const researchPublishedSeriesCatalogSchema = z
    .strictObject({
        schema_version: z.literal(2),
        research_result_fingerprint: sha256,
        series: z.array(
            z.strictObject({
                candidate_fingerprint: sha256.nullable(),
                calculation_fingerprint: sha256,
                node_fingerprint: sha256,
                output_name: z.string().min(1),
                value_kind: z.enum(["DECIMAL", "INTEGER", "BOOLEAN", "STRING"])
            })
        )
    })
    .superRefine((value, context) => {
        const keys = value.series.map((series) =>
            [
                series.candidate_fingerprint,
                series.calculation_fingerprint,
                series.node_fingerprint,
                series.output_name
            ].join(":")
        );
        if (new Set(keys).size !== keys.length)
            context.addIssue({
                code: "custom",
                message: "Published Series membership is duplicated"
            });
    }) satisfies z.ZodType<Dto<"ResearchPublishedSeriesCatalogDto">>;

const marketPointSchema = z.strictObject({
    instrument_id: z.string().min(1),
    ts_event_ns: integer,
    open: decimal,
    high: decimal,
    low: decimal,
    close: decimal,
    volume: decimal
});
const variablePointSchema = z
    .strictObject({
        instrument_id: z.string().min(1),
        ts_event_ns: integer,
        value_kind: z.enum(["DECIMAL", "INTEGER", "BOOLEAN", "STRING"]),
        decimal_value: decimal.nullable(),
        integer_value: integer.nullable(),
        boolean_value: z.boolean().nullable(),
        string_value: z.string().nullable()
    })
    .superRefine((value, context) => {
        const fields = {
            DECIMAL: value.decimal_value,
            INTEGER: value.integer_value,
            BOOLEAN: value.boolean_value,
            STRING: value.string_value
        };
        for (const [kind, field] of Object.entries(fields))
            if (kind !== value.value_kind && field !== null)
                context.addIssue({ code: "custom", message: "Variable value_kind mismatch" });
    });
const signalPointSchema = z.strictObject({
    instrument_id: z.string().min(1),
    ts_event_ns: integer,
    value: z.boolean().nullable()
});

export const researchScientificSeriesPageSchema = z
    .strictObject({
        schema_version: z.literal(2),
        research_result_fingerprint: sha256,
        points: z.array(z.union([marketPointSchema, variablePointSchema, signalPointSchema])),
        has_more: z.boolean(),
        next_after_ts_event_ns: integer.nullable()
    })
    .superRefine((value, context) => {
        const timestamps = value.points.map((point) => BigInt(point.ts_event_ns));
        if (!strictlyIncreasing(timestamps))
            context.addIssue({
                code: "custom",
                message: "Scientific timestamps are not canonical"
            });
        const expected = value.has_more ? value.points.at(-1)?.ts_event_ns : undefined;
        if (value.has_more && expected === undefined)
            context.addIssue({
                code: "custom",
                message: "Scientific page cannot continue from empty evidence"
            });
        if (
            (expected === undefined && value.next_after_ts_event_ns !== null) ||
            (expected !== undefined && value.next_after_ts_event_ns !== expected)
        )
            context.addIssue({ code: "custom", message: "Scientific cursor mismatch" });
    }) satisfies z.ZodType<Dto<"ResearchScientificSeriesPageDto">>;

const graphScalarSchema = z.discriminatedUnion("type", [
    z.strictObject({ type: z.literal("NULL"), value: z.null() }),
    z.strictObject({ type: z.literal("BOOLEAN"), value: z.boolean() }),
    z.strictObject({ type: z.literal("INTEGER"), value: z.number().int() }),
    z.strictObject({ type: z.literal("DECIMAL"), value: decimal }),
    z.strictObject({ type: z.literal("STRING"), value: z.string() })
]);
const graphPortSchema = z.strictObject({
    name: z.string().min(1),
    data_type: z.enum(["DECIMAL", "INTEGER", "BOOLEAN", "STRING"]),
    nullable: z.boolean(),
    dimensions: z.array(z.string().min(1)),
    semantic_type: z.string().min(1),
    unit: z.string().nullable()
});
const graphReferenceSchema = z
    .strictObject({
        node_fingerprint: sha256.nullable(),
        output_name: z.string().min(1),
        source: z.string().min(1).nullable()
    })
    .refine((value) => (value.node_fingerprint === null) !== (value.source === null), {
        message: "Graph input must select exactly one node or external source"
    });
const graphDefinitionSchema = z.strictObject({
    schema_version: z.literal(2),
    kind: z.enum(["INDICATOR", "FACTOR", "TARGET", "PREDICATE"]),
    type_id: z.string().min(1),
    semantic_version: z.string().min(1),
    parameters: z.record(z.string(), graphScalarSchema),
    inputs: z.array(graphPortSchema),
    input_bindings: z.record(z.string(), graphReferenceSchema),
    outputs: z.array(graphPortSchema).min(1),
    warmup: z.strictObject({
        minimum_observations: positive,
        ready_condition: z.string().min(1),
        pre_ready_output: z.enum(["NULL", "PARTIAL"]),
        initialization: z.string().min(1)
    }),
    missing_values: z.enum(["FAIL", "SKIP", "PROPAGATE", "RESET"]),
    timestamp: z.enum([
        "BAR_OPEN",
        "BAR_CLOSE",
        "EVENT_TIME",
        "OBSERVATION_TIME",
        "AVAILABILITY_TIME"
    ]),
    numeric: z.strictObject({
        representation: z.string().min(1),
        precision: positive,
        output_quantum: decimal.nullable(),
        rounding: z.string().min(1)
    }),
    factor_kind: z.enum(["TIME_SERIES", "CROSS_SECTION"]).nullable(),
    extensions: z.record(z.string(), graphScalarSchema)
});
const calculationGraphSchema = z
    .strictObject({
        schema_version: z.literal(1),
        nodes: z.array(
            z.strictObject({
                node_fingerprint: sha256,
                definition: graphDefinitionSchema,
                alias: z.string().nullable()
            })
        )
    })
    .superRefine((value, context) => {
        const identities = new Set(value.nodes.map((node) => node.node_fingerprint));
        if (identities.size !== value.nodes.length)
            context.addIssue({ code: "custom", message: "Graph nodes are duplicated" });
        for (const node of value.nodes) {
            const inputs = node.definition.inputs.map((port) => port.name).sort();
            const bindings = Object.keys(node.definition.input_bindings).sort();
            if (inputs.join("\0") !== bindings.join("\0"))
                context.addIssue({ code: "custom", message: "Graph input bindings mismatch" });
            for (const reference of Object.values(node.definition.input_bindings))
                if (
                    reference.node_fingerprint !== null &&
                    !identities.has(reference.node_fingerprint)
                )
                    context.addIssue({ code: "custom", message: "Graph dependency is missing" });
        }
    });

export const researchCandidateGraphSchema = z.strictObject({
    schema_version: z.literal(2),
    research_result_fingerprint: sha256,
    candidate_fingerprint: sha256,
    calculation_fingerprint: sha256,
    graph_fingerprint: sha256,
    graph: calculationGraphSchema
}) satisfies z.ZodType<Dto<"ResearchCandidateGraphDto">>;

export const researchErrorSchema = z.strictObject({
    schema_version: z.literal(2),
    code: z.enum([
        "INVALID_QUERY",
        "INVALID_TIME_RANGE",
        "INVALID_PAGE_LIMIT",
        "RESEARCH_ARTIFACT_NOT_FOUND",
        "RESEARCH_ARTIFACT_CORRUPT",
        "STATISTICS_NOT_FOUND",
        "SCIENTIFIC_EVIDENCE_NOT_AVAILABLE",
        "CANDIDATE_NOT_FOUND",
        "SERIES_NOT_FOUND"
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
    kind: calculationKind,
    type_id: z.string().min(1),
    semantic_version: z.string().min(1)
});
const calculationPortSchema = z.strictObject({
    name: z.string().min(1),
    data_type: calculationDataType,
    nullable: z.boolean(),
    semantic_type: z.string().min(1),
    dimensions: z.array(z.string().min(1)),
    unit: z.string().nullable()
});
const calculationParameterSchema = z.strictObject({
    name: z.string().min(1),
    type: calculationDataType,
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
            kind: calculationKind,
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
            data_type: calculationDataType,
            semantic_roles: z.array(z.string().min(1)),
            dimensions: z.array(z.string().min(1)),
            unit: z.string().nullable()
        })
    )
}) satisfies z.ZodType<Dto<"ResearchDatasetFieldCatalogDto">>;

export const researchUniverseCatalogSchema = z.strictObject({
    schema_version: z.literal(2),
    selection_kinds: z.array(universeKind),
    registered_universes: z.array(
        z.strictObject({
            registered_id: z.string().min(1),
            kind: universeKind,
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
export type ResearchCandidateCatalogTransport = z.infer<typeof researchCandidateCatalogSchema>;
export type ResearchPublishedSeriesCatalogTransport = z.infer<
    typeof researchPublishedSeriesCatalogSchema
>;
export type ResearchScientificSeriesPageTransport = z.infer<
    typeof researchScientificSeriesPageSchema
>;
export type ResearchCandidateGraphTransport = z.infer<typeof researchCandidateGraphSchema>;
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
export type ResearchCalculationCatalogItemTransport = Dto<"ResearchCalculationCatalogItemDto">;
export type ResearchCalculationInstanceTransport = Dto<"ResearchCalculationInstanceDto">;
export type ResearchScalarTransport = Dto<"ResearchScalarDto">;
export type ResearchExpressionTransport =
    | Dto<"ResearchComparisonDto">
    | Dto<"ResearchNotDto">
    | Dto<"ResearchAndDto">
    | Dto<"ResearchOrDto">;
