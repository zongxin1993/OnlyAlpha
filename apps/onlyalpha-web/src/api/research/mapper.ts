import { parseDecimalText } from "../../domain/research/decimal";
import {
    parseResearchResultFingerprint,
    parseResearchRunId,
    parseStatisticsFingerprint
} from "../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchRun,
    ResearchRunPage,
    ResearchRunSubmission,
    ResearchRunSummary,
    ResearchStatisticSeriesPage,
    ResearchStatisticsCatalog,
    ResearchStatisticsDescriptor
} from "../../domain/research/model";
import { parseUnixNanoseconds } from "../../domain/research/time";
import type {
    ArtifactSummaryTransport,
    ResearchRunPageTransport,
    ResearchRunSubmissionTransport,
    ResearchRunSummaryTransport,
    ResearchRunTransport,
    StatisticSeriesPageTransport,
    StatisticsCatalogTransport
} from "./schemas";

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
