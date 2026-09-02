export type ChartTimeSeconds = number & { readonly __chartTimeSeconds: unique symbol };

export interface ChartValuePoint {
    readonly time: ChartTimeSeconds;
    readonly value: number;
}

export interface ChartWhitespacePoint {
    readonly time: ChartTimeSeconds;
}

export type ResearchChartPoint = ChartValuePoint | ChartWhitespacePoint;

export interface ChartProjectionFailure {
    readonly ok: false;
    readonly code: "CHART_PROJECTION_ERROR";
    readonly detail: string;
}

export interface ChartProjectionSuccess {
    readonly ok: true;
    readonly points: readonly ResearchChartPoint[];
}

export type ChartProjection = ChartProjectionSuccess | ChartProjectionFailure;
