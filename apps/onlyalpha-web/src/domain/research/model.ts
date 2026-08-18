import type { DecimalText } from "./decimal";
import type { ResearchResultFingerprint, ResearchRunId, StatisticsFingerprint } from "./identity";
import type { UnixNanoseconds } from "./time";

export interface ResearchArtifactSummary {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly researchResultPlanFingerprint: string;
    readonly researchResultContentFingerprint: string;
    readonly datasetSnapshotFingerprint: string;
    readonly artifactContentFingerprint: string;
    readonly researchResultSchemaVersion: number;
    readonly artifactProfile: string;
    readonly artifactSchemaVersion: number;
    readonly statisticsCount: number;
    readonly rowCount: number;
    readonly createdAt: string;
}

export interface ResearchSeriesReference {
    readonly calculationFingerprint: string;
    readonly nodeFingerprint: string;
    readonly outputName: string;
}

export interface ResearchNumericDefinition {
    readonly representation: string;
    readonly precision: number;
    readonly outputQuantum: DecimalText;
    readonly rounding: string;
}

export interface ResearchStatisticsDescriptor {
    readonly statisticsFingerprint: StatisticsFingerprint;
    readonly statisticsResultFingerprint: string;
    readonly resultContentFingerprint: string;
    readonly statisticsResultSchemaVersion: number;
    readonly rowCount: number;
    readonly feature: ResearchSeriesReference;
    readonly target: ResearchSeriesReference;
    readonly definition: {
        readonly method: string;
        readonly minimumObservations: number;
        readonly pairingPolicy: string;
        readonly universePolicy: string;
        readonly rankTieMethod: string;
        readonly weighting: string;
        readonly numeric: ResearchNumericDefinition;
    };
}

export interface ResearchStatisticsCatalog {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly statistics: readonly ResearchStatisticsDescriptor[];
}

export interface ResearchStatisticPoint {
    readonly tsEventNs: UnixNanoseconds;
    readonly statisticValue: DecimalText | null;
    readonly sampleCount: number;
    readonly status: string;
}

export interface ResearchStatisticSeriesPage {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly statisticsFingerprint: StatisticsFingerprint;
    readonly points: readonly ResearchStatisticPoint[];
    readonly hasMore: boolean;
    readonly nextAfterTsEventNs: UnixNanoseconds | null;
}

export type ResearchRunState =
    "QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface ResearchRunFailure {
    readonly phase: string;
    readonly code: string;
    readonly detail: string;
}

export interface ResearchRunSummary {
    readonly runId: ResearchRunId;
    readonly revision: bigint;
    readonly state: ResearchRunState;
    readonly specificationSchemaVersion: number;
    readonly specificationFingerprint: string;
    readonly admissionResolutionFingerprint: string;
    readonly queuedAt: string;
    readonly startedAt: string | null;
    readonly cancelRequestedAt: string | null;
    readonly finishedAt: string | null;
    readonly resultRef: string | null;
    readonly artifactRef: string | null;
    readonly failure: ResearchRunFailure | null;
}

export interface ResearchRun extends ResearchRunSummary {
    readonly specification: Readonly<Record<string, unknown>>;
}

export interface ResearchRunPage {
    readonly runs: readonly ResearchRunSummary[];
    readonly hasMore: boolean;
    readonly nextCursor: string | null;
}

export interface ResearchRunSubmission {
    readonly disposition: "CREATED" | "REUSED";
    readonly run: ResearchRun;
}
