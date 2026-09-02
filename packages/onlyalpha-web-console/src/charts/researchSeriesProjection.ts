import type { ResearchStatisticPoint } from "../domain/research/model";
import type { ChartProjection, ChartTimeSeconds, ResearchChartPoint } from "./model";

export function projectResearchSeries(points: readonly ResearchStatisticPoint[]): ChartProjection {
    const projected: ResearchChartPoint[] = [];
    let previousNs: bigint | undefined;
    let previousSecond: bigint | undefined;
    for (const point of points) {
        if (previousNs !== undefined && point.tsEventNs <= previousNs) {
            return {
                ok: false,
                code: "CHART_PROJECTION_ERROR",
                detail: "Exact timestamps are not strictly ordered"
            };
        }
        const second = point.tsEventNs / 1_000_000_000n;
        if (previousSecond === second) {
            return {
                ok: false,
                code: "CHART_PROJECTION_ERROR",
                detail: "Distinct nanosecond timestamps collide at chart-second resolution"
            };
        }
        const chartTime = Number(second);
        if (!Number.isSafeInteger(chartTime)) {
            return {
                ok: false,
                code: "CHART_PROJECTION_ERROR",
                detail: "Timestamp is outside safe chart range"
            };
        }
        const time = chartTime as ChartTimeSeconds;
        if (point.statisticValue === null) {
            projected.push({ time });
        } else {
            const value = Number(point.statisticValue);
            if (!Number.isFinite(value)) {
                return {
                    ok: false,
                    code: "CHART_PROJECTION_ERROR",
                    detail: "Exact Decimal cannot be represented as a finite chart coordinate"
                };
            }
            projected.push({ time, value });
        }
        previousNs = point.tsEventNs;
        previousSecond = second;
    }
    return { ok: true, points: projected };
}
