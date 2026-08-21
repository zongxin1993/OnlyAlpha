import type { UnixNanoseconds } from "../../domain/research/time";

export interface ScientificSeriesPoint {
    readonly tsEventNs: UnixNanoseconds;
    readonly timeLabel: string;
    readonly value: number | null;
    readonly status: string;
    readonly sampleCount: number;
}

export interface CandidateSurfacePoint {
    readonly candidateFingerprint: string;
    readonly assignment: Readonly<Record<string, boolean | number | string | null>>;
    readonly numericCoordinates: Readonly<Record<string, number>>;
    readonly value: number | null;
    readonly status: string;
}

export interface CandidateSurface {
    readonly dimensions: readonly string[];
    readonly mode: "ONE_DIMENSION" | "TWO_DIMENSIONS" | "MULTI_DIMENSION" | "TABLE_ONLY";
    readonly exactTsEventNs: UnixNanoseconds;
    readonly points: readonly CandidateSurfacePoint[];
}
