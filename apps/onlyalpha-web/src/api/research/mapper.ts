import { parseDecimalText } from "../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseResearchRunId,
    parseSha256Fingerprint,
    parseStatisticsFingerprint
} from "../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchCandidateCatalog,
    ResearchCandidateGraph,
    ResearchGraphScalar,
    ResearchPublishedSeriesCatalog,
    ResearchRun,
    ResearchRunPage,
    ResearchRunSubmission,
    ResearchRunSummary,
    ResearchStatisticSeriesPage,
    ResearchScientificSeriesPage,
    ResearchStatisticsCatalog,
    ResearchStatisticsDescriptor
} from "../../domain/research/model";
import { parseUnixNanoseconds } from "../../domain/research/time";
import type {
    ArtifactSummaryTransport,
    ResearchCandidateCatalogTransport,
    ResearchCandidateGraphTransport,
    ResearchPublishedSeriesCatalogTransport,
    ResearchScientificSeriesPageTransport,
    ResearchRunPageTransport,
    ResearchRunSubmissionTransport,
    ResearchRunSummaryTransport,
    ResearchRunTransport,
    StatisticSeriesPageTransport,
    StatisticsCatalogTransport
} from "./schemas";

const mapGraphScalar = (
    value: ResearchCandidateGraphTransport["graph"]["nodes"][number]["definition"]["parameters"][string]
): ResearchGraphScalar =>
    value.type === "DECIMAL" ? { ...value, value: parseDecimalText(value.value) } : value;

export const mapCandidateCatalog = (
    value: ResearchCandidateCatalogTransport
): ResearchCandidateCatalog => ({
    researchResultFingerprint: parseResearchResultFingerprint(value.research_result_fingerprint),
    candidates: value.candidates.map((candidate) => ({
        candidateFingerprint: parseSha256Fingerprint(candidate.candidate_fingerprint),
        candidateCalculationId: candidate.candidate_calculation_id,
        assignment: candidate.assignment,
        assignmentTypes: candidate.assignment_types,
        calculationFingerprint: parseSha256Fingerprint(candidate.calculation_fingerprint),
        graphFingerprint: parseSha256Fingerprint(candidate.graph_fingerprint),
        statisticsFingerprints: candidate.statistics_fingerprints.map(parseStatisticsFingerprint),
        signalRoles: candidate.signal_roles
    }))
});

export const mapPublishedSeriesCatalog = (
    value: ResearchPublishedSeriesCatalogTransport
): ResearchPublishedSeriesCatalog => ({
    researchResultFingerprint: parseResearchResultFingerprint(value.research_result_fingerprint),
    series: value.series.map((series) => ({
        candidateFingerprint:
            series.candidate_fingerprint === null
                ? null
                : parseSha256Fingerprint(series.candidate_fingerprint),
        calculationFingerprint: parseSha256Fingerprint(series.calculation_fingerprint),
        nodeFingerprint: parseSha256Fingerprint(series.node_fingerprint),
        outputName: series.output_name,
        valueKind: series.value_kind
    }))
});

export const mapScientificSeriesPage = (
    value: ResearchScientificSeriesPageTransport
): ResearchScientificSeriesPage => ({
    researchResultFingerprint: parseResearchResultFingerprint(value.research_result_fingerprint),
    points: value.points.map((point) => {
        const base = {
            instrumentId: point.instrument_id,
            tsEventNs: parseUnixNanoseconds(point.ts_event_ns)
        };
        if ("open" in point)
            return {
                kind: "MARKET" as const,
                ...base,
                open: parseDecimalText(point.open),
                high: parseDecimalText(point.high),
                low: parseDecimalText(point.low),
                close: parseDecimalText(point.close),
                volume: parseDecimalText(point.volume)
            };
        if ("value_kind" in point)
            return {
                kind: "VARIABLE" as const,
                ...base,
                valueKind: point.value_kind,
                decimalValue:
                    point.decimal_value === null ? null : parseDecimalText(point.decimal_value),
                integerValue: point.integer_value,
                booleanValue: point.boolean_value,
                stringValue: point.string_value
            };
        return { kind: "SIGNAL" as const, ...base, value: point.value };
    }),
    hasMore: value.has_more,
    nextAfterTsEventNs:
        value.next_after_ts_event_ns === null
            ? null
            : parseUnixNanoseconds(value.next_after_ts_event_ns)
});

export const mapCandidateGraph = (
    value: ResearchCandidateGraphTransport
): ResearchCandidateGraph => ({
    researchResultFingerprint: parseResearchResultFingerprint(value.research_result_fingerprint),
    candidateFingerprint: parseSha256Fingerprint(value.candidate_fingerprint),
    calculationFingerprint: parseSha256Fingerprint(value.calculation_fingerprint),
    graphFingerprint: parseSha256Fingerprint(value.graph_fingerprint),
    graph: {
        schemaVersion: value.graph.schema_version,
        nodes: value.graph.nodes.map((node) => ({
            nodeFingerprint: parseSha256Fingerprint(node.node_fingerprint),
            alias: node.alias,
            definition: {
                schemaVersion: node.definition.schema_version,
                kind: node.definition.kind,
                typeId: node.definition.type_id,
                semanticVersion: node.definition.semantic_version,
                parameters: Object.fromEntries(
                    Object.entries(node.definition.parameters).map(([name, scalar]) => [
                        name,
                        mapGraphScalar(scalar)
                    ])
                ),
                inputs: node.definition.inputs.map((port) => ({
                    name: port.name,
                    dataType: port.data_type,
                    nullable: port.nullable,
                    dimensions: port.dimensions,
                    semanticType: port.semantic_type,
                    unit: port.unit
                })),
                inputBindings: Object.fromEntries(
                    Object.entries(node.definition.input_bindings).map(([name, reference]) => [
                        name,
                        {
                            nodeFingerprint:
                                reference.node_fingerprint === null
                                    ? null
                                    : parseSha256Fingerprint(reference.node_fingerprint),
                            outputName: reference.output_name,
                            source: reference.source
                        }
                    ])
                ),
                outputs: node.definition.outputs.map((port) => ({
                    name: port.name,
                    dataType: port.data_type,
                    nullable: port.nullable,
                    dimensions: port.dimensions,
                    semanticType: port.semantic_type,
                    unit: port.unit
                })),
                warmup: {
                    minimumObservations: node.definition.warmup.minimum_observations,
                    readyCondition: node.definition.warmup.ready_condition,
                    preReadyOutput: node.definition.warmup.pre_ready_output,
                    initialization: node.definition.warmup.initialization
                },
                missingValues: node.definition.missing_values,
                timestamp: node.definition.timestamp,
                numeric: {
                    representation: node.definition.numeric.representation,
                    precision: node.definition.numeric.precision,
                    outputQuantum:
                        node.definition.numeric.output_quantum === null
                            ? null
                            : parseDecimalText(node.definition.numeric.output_quantum),
                    rounding: node.definition.numeric.rounding
                },
                factorKind: node.definition.factor_kind,
                extensions: Object.fromEntries(
                    Object.entries(node.definition.extensions).map(([name, scalar]) => [
                        name,
                        mapGraphScalar(scalar)
                    ])
                )
            }
        }))
    }
});

export const mapArtifactSummary = (value: ArtifactSummaryTransport): ResearchArtifactSummary => ({
    researchResultFingerprint: parseResearchResultFingerprint(value.research_result_fingerprint),
    researchResultPlanFingerprint: value.research_result_plan_fingerprint,
    researchResultContentFingerprint: value.research_result_content_fingerprint,
    datasetSnapshotFingerprint: value.dataset_snapshot_fingerprint,
    artifactContentFingerprint: value.artifact_content_fingerprint,
    researchResultSchemaVersion: value.research_result_schema_version,
    artifactProfile: value.artifact_profile,
    artifactSchemaVersion: value.artifact_schema_version,
    statisticsCount: value.statistics_count,
    rowCount: value.row_count,
    candidateCount: value.candidate_count,
    publishedSeriesCount: value.published_series_count,
    signalSeriesCount: value.signal_series_count,
    marketRowCount: value.market_row_count,
    instrumentIds: value.instrument_ids,
    createdAt: value.created_at
});

const mapDescriptor = (
    value: StatisticsCatalogTransport["statistics"][number]
): ResearchStatisticsDescriptor => ({
    statisticsFingerprint: parseStatisticsFingerprint(value.statistics_fingerprint),
    statisticsResultFingerprint: value.statistics_result_fingerprint,
    resultContentFingerprint: value.result_content_fingerprint,
    statisticsResultSchemaVersion: value.statistics_result_schema_version,
    rowCount: value.row_count,
    feature: {
        calculationFingerprint: value.feature.calculation_fingerprint,
        nodeFingerprint: value.feature.node_fingerprint,
        outputName: value.feature.output_name
    },
    target: {
        calculationFingerprint: value.target.calculation_fingerprint,
        nodeFingerprint: value.target.node_fingerprint,
        outputName: value.target.output_name
    },
    definition: {
        method: value.definition.method,
        minimumObservations: value.definition.minimum_observations,
        pairingPolicy: value.definition.pairing_policy,
        universePolicy: value.definition.universe_policy,
        rankTieMethod: value.definition.rank_tie_method,
        weighting: value.definition.weighting,
        numeric: {
            representation: value.definition.numeric.representation,
            precision: value.definition.numeric.precision,
            outputQuantum: parseDecimalText(value.definition.numeric.output_quantum),
            rounding: value.definition.numeric.rounding
        }
    }
});

export const mapStatisticsCatalog = (
    value: StatisticsCatalogTransport
): ResearchStatisticsCatalog => ({
    researchResultFingerprint: parseResearchResultFingerprint(value.research_result_fingerprint),
    statistics: value.statistics.map(mapDescriptor)
});

export const mapStatisticSeriesPage = (
    value: StatisticSeriesPageTransport
): ResearchStatisticSeriesPage => ({
    researchResultFingerprint: parseResearchResultFingerprint(value.research_result_fingerprint),
    statisticsFingerprint: parseStatisticsFingerprint(value.statistics_fingerprint),
    points: value.points.map((point) => ({
        tsEventNs: parseUnixNanoseconds(point.ts_event_ns),
        statisticValue:
            point.statistic_value === null ? null : parseDecimalText(point.statistic_value),
        sampleCount: point.sample_count,
        status: point.status
    })),
    hasMore: value.has_more,
    nextAfterTsEventNs:
        value.next_after_ts_event_ns === null
            ? null
            : parseUnixNanoseconds(value.next_after_ts_event_ns)
});

export const mapResearchRunSummary = (value: ResearchRunSummaryTransport): ResearchRunSummary => ({
    runId: parseResearchRunId(value.run_id),
    revision: BigInt(value.revision),
    state: value.state,
    specificationSchemaVersion: value.specification_schema_version,
    specificationFingerprint: value.specification_fingerprint,
    admissionResolutionFingerprint: value.admission_resolution_fingerprint,
    queuedAt: value.queued_at,
    startedAt: value.started_at,
    cancelRequestedAt: value.cancel_requested_at,
    finishedAt: value.finished_at,
    resultRef: value.result_ref,
    artifactRef: value.artifact_ref,
    failure: value.failure
});

export const mapResearchRun = (value: ResearchRunTransport): ResearchRun => ({
    ...mapResearchRunSummary(value),
    specification: value.specification
});

export const mapResearchRunPage = (value: ResearchRunPageTransport): ResearchRunPage => ({
    runs: value.runs.map(mapResearchRunSummary),
    hasMore: value.has_more,
    nextCursor: value.next_cursor
});

export const mapResearchRunSubmission = (
    value: ResearchRunSubmissionTransport
): ResearchRunSubmission => ({
    disposition: value.submission_disposition,
    run: mapResearchRun(value.run)
});
