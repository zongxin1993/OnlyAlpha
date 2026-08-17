import type { DecimalText } from "./decimal";
import type { ResearchResultFingerprint, StatisticsFingerprint } from "./identity";
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
