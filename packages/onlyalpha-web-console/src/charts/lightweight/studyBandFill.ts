import type {
    IPrimitivePaneRenderer,
    IPrimitivePaneView,
    ISeriesPrimitive,
    SeriesAttachedParameter,
    UTCTimestamp
} from "lightweight-charts";
import type { StudySeriesProjection } from "./studySeriesProjection";

export interface BandPoint {
    readonly time: UTCTimestamp;
    readonly upper: number;
    readonly lower: number;
}
/** Geometry only: joins admitted display values; never derives indicator values. */
export function bandPolygons(
    upper: StudySeriesProjection,
    lower: StudySeriesProjection
): readonly (readonly BandPoint[])[] {
    const result: BandPoint[][] = [];
    for (const segment of upper.segments) {
        let run: BandPoint[] = [];
        const flush = () => {
            if (run.length > 0) result.push(run);
            run = [];
        };
        for (const point of segment) {
            const below = lower.pointsByTime.get(Number(point.time));
            if (!("value" in point) || below?.value == null) flush();
            else run.push({ time: point.time, upper: point.value, lower: Number(below.value) });
        }
        flush();
    }
    return result;
}

/** Native Lightweight Charts primitive paints the declared band on its owning scale. */
export class StudyBandFill implements ISeriesPrimitive {
    private owner: SeriesAttachedParameter | null = null;
    private readonly view: IPrimitivePaneView;
    constructor(
        private readonly polygons: readonly (readonly BandPoint[])[],
        private readonly color: string
    ) {
        const renderer: IPrimitivePaneRenderer = {
            draw: (target) => {
                target.useMediaCoordinateSpace(({ context }) => {
                    const owner = this.owner;
                    if (owner === null) return;
                    context.fillStyle = this.color;
                    for (const polygon of this.polygons) {
                        const points = polygon.flatMap((point) => {
                            const x = owner.chart.timeScale().timeToCoordinate(point.time);
                            const upper = owner.series.priceToCoordinate(point.upper);
                            const lower = owner.series.priceToCoordinate(point.lower);
                            return x === null || upper === null || lower === null
                                ? []
                                : [{ x, upper, lower }];
                        });
                        if (points.length < 2 || points.length !== polygon.length) continue;
                        context.beginPath();
                        points.forEach((point, index) => {
                            if (index === 0) context.moveTo(point.x, point.upper);
                            else context.lineTo(point.x, point.upper);
                        });
                        [...points].reverse().forEach((point) => {
                            context.lineTo(point.x, point.lower);
                        });
                        context.closePath();
                        context.fill();
                    }
                });
            }
        };
        this.view = { zOrder: () => "bottom", renderer: () => renderer };
    }
    attached(owner: SeriesAttachedParameter): void {
        this.owner = owner;
        owner.requestUpdate();
    }
    detached(): void {
        this.owner = null;
    }
    paneViews(): readonly IPrimitivePaneView[] {
        return [this.view];
    }
}
