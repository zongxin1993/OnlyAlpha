import type { DecimalText } from "./decimal";
import type {
    ResearchResultFingerprint,
    ResearchRunId,
    Sha256Fingerprint,
    StatisticsFingerprint
} from "./identity";
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
    readonly candidateCount: number;
    readonly publishedSeriesCount: number;
    readonly signalSeriesCount: number;
    readonly marketRowCount: number;
    readonly instrumentIds: readonly string[];
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

export type ResearchCandidateAssignmentValue = boolean | number | string | null;
export type ResearchCandidateAssignmentType = "NULL" | "BOOLEAN" | "INTEGER" | "DECIMAL" | "STRING";
export type ResearchSignalRole = "ELIGIBILITY" | "ENTRY_SIGNAL" | "EXIT_SIGNAL";

export interface ResearchCandidate {
    readonly candidateFingerprint: Sha256Fingerprint;
    readonly candidateCalculationId: string;
    readonly assignment: Readonly<Record<string, ResearchCandidateAssignmentValue>>;
    readonly assignmentTypes: Readonly<Record<string, ResearchCandidateAssignmentType>>;
    readonly calculationFingerprint: Sha256Fingerprint;
    readonly graphFingerprint: Sha256Fingerprint;
    readonly statisticsFingerprints: readonly StatisticsFingerprint[];
    readonly signalRoles: readonly ResearchSignalRole[];
}

export interface ResearchCandidateCatalog {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly candidates: readonly ResearchCandidate[];
}

export type ResearchValueKind = "DECIMAL" | "INTEGER" | "BOOLEAN" | "STRING";

export interface ResearchPublishedSeries {
    readonly candidateFingerprint: Sha256Fingerprint | null;
    readonly calculationFingerprint: Sha256Fingerprint;
    readonly nodeFingerprint: Sha256Fingerprint;
    readonly outputName: string;
    readonly valueKind: ResearchValueKind;
}

export interface ResearchPublishedSeriesCatalog {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly series: readonly ResearchPublishedSeries[];
}

export interface ResearchMarketPoint {
    readonly kind: "MARKET";
    readonly instrumentId: string;
    readonly tsEventNs: UnixNanoseconds;
    readonly open: DecimalText;
    readonly high: DecimalText;
    readonly low: DecimalText;
    readonly close: DecimalText;
    readonly volume: DecimalText;
}

export interface ResearchVariablePoint {
    readonly kind: "VARIABLE";
    readonly instrumentId: string;
    readonly tsEventNs: UnixNanoseconds;
    readonly valueKind: ResearchValueKind;
    readonly decimalValue: DecimalText | null;
    readonly integerValue: string | null;
    readonly booleanValue: boolean | null;
    readonly stringValue: string | null;
}

export interface ResearchSignalPoint {
    readonly kind: "SIGNAL";
    readonly instrumentId: string;
    readonly tsEventNs: UnixNanoseconds;
    readonly value: boolean | null;
}

export interface ResearchScientificSeriesPage {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly points: readonly (ResearchMarketPoint | ResearchVariablePoint | ResearchSignalPoint)[];
    readonly hasMore: boolean;
    readonly nextAfterTsEventNs: UnixNanoseconds | null;
}

export type ResearchGraphScalar =
    | { readonly type: "NULL"; readonly value: null }
    | { readonly type: "BOOLEAN"; readonly value: boolean }
    | { readonly type: "INTEGER"; readonly value: string }
    | { readonly type: "DECIMAL"; readonly value: DecimalText }
    | { readonly type: "STRING"; readonly value: string };

export interface ResearchGraphPort {
    readonly name: string;
    readonly dataType: ResearchValueKind;
    readonly nullable: boolean;
    readonly dimensions: readonly string[];
    readonly semanticType: string;
    readonly unit: string | null;
}

export interface ResearchGraphReference {
    readonly nodeFingerprint: Sha256Fingerprint | null;
    readonly outputName: string;
    readonly source: string | null;
}

export interface ResearchGraphNode {
    readonly nodeFingerprint: Sha256Fingerprint;
    readonly alias: string | null;
    readonly definition: {
        readonly schemaVersion: 2;
        readonly kind: "INDICATOR" | "FACTOR" | "TARGET" | "PREDICATE";
        readonly typeId: string;
        readonly semanticVersion: string;
        readonly parameters: Readonly<Record<string, ResearchGraphScalar>>;
        readonly inputs: readonly ResearchGraphPort[];
        readonly inputBindings: Readonly<Record<string, ResearchGraphReference>>;
        readonly outputs: readonly ResearchGraphPort[];
        readonly warmup: {
            readonly minimumObservations: number;
            readonly readyCondition: string;
            readonly preReadyOutput: "NULL" | "PARTIAL";
            readonly initialization: string;
        };
        readonly missingValues: "FAIL" | "SKIP" | "PROPAGATE" | "RESET";
        readonly timestamp:
            "BAR_OPEN" | "BAR_CLOSE" | "EVENT_TIME" | "OBSERVATION_TIME" | "AVAILABILITY_TIME";
        readonly numeric: {
            readonly representation: string;
            readonly precision: number;
            readonly outputQuantum: DecimalText | null;
            readonly rounding: string;
        };
        readonly factorKind: "TIME_SERIES" | "CROSS_SECTION" | null;
        readonly extensions: Readonly<Record<string, ResearchGraphScalar>>;
    };
}

export interface ResearchCandidateGraph {
    readonly researchResultFingerprint: ResearchResultFingerprint;
    readonly candidateFingerprint: Sha256Fingerprint;
    readonly calculationFingerprint: Sha256Fingerprint;
    readonly graphFingerprint: Sha256Fingerprint;
    readonly graph: { readonly schemaVersion: 1; readonly nodes: readonly ResearchGraphNode[] };
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
