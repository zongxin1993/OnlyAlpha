import {
    HistogramSeries,
    LineSeries,
    type IChartApi,
    type IPaneApi,
    type ISeriesApi,
    type LineWidth,
    type Time
} from "lightweight-charts";
import {
    studySeriesColor,
    validPresentation,
    type ChartStudyInstance
} from "../../features/workspace/chartStudy";
import { StudyBandFill, bandPolygons } from "./studyBandFill";
import type { StudySeriesProjection, StudySeriesView } from "./studySeriesProjection";

interface Curve {
    readonly series: ISeriesApi<"Line" | "Histogram">;
    readonly kind: "LINE" | "HISTOGRAM";
    data: StudySeriesProjection["segments"][number];
}
interface Resource {
    readonly curves: Map<string, Curve>;
    pane: IPaneApi<Time> | null;
    label: HTMLParagraphElement | null;
    fill: { series: ISeriesApi<"Line" | "Histogram">; primitive: StudyBandFill } | null;
}

/** Each display instance owns one pane; outputs retain their backend-defined role and unit. */
export class StudySeriesRenderer {
    private readonly resources = new Map<string, Resource>();
    private frame: number | null = null;
    constructor(
        private readonly chart: IChartApi,
        private readonly pricePane: IPaneApi<Time>
    ) {}
    sync(
        instances: readonly ChartStudyInstance[],
        views: ReadonlyMap<string, StudySeriesView>,
        selectedId: string | null
    ): void {
        const visible = instances.filter(
            (instance) => instance.presentation.visible && validPresentation(instance.presentation)
        );
        const wanted = new Set(visible.map((instance) => instance.instanceId));
        for (const [id, resource] of this.resources)
            if (!wanted.has(id)) {
                this.release(resource);
                this.resources.delete(id);
            }
        for (const instance of visible) {
            let resource = this.resources.get(instance.instanceId);
            if (resource === undefined) {
                resource = { curves: new Map(), pane: null, label: null, fill: null };
                this.resources.set(instance.instanceId, resource);
            }
            const metadata =
                instance.selection.source === "CHART_STUDY_TRANSIENT"
                    ? instance.selection.capability.presentation.series
                    : [];
            const outputs = instance.configuration.outputNames
                .filter((name) => instance.presentation.seriesStyles?.[name]?.visible !== false)
                .map((name) => ({
                    name,
                    view: views.get(JSON.stringify([instance.instanceId, name])),
                    metadata: metadata.find((row) => row.output_name === name)
                }));
            const overlay =
                instance.presentation.placement === "PRICE_OVERLAY" &&
                outputs.every(
                    (output) =>
                        output.view?.status === "PROJECTED" &&
                        output.view.projection.outputUnit === "PRICE"
                );
            if (!overlay && resource.pane === null) {
                resource.pane = this.chart.addPane(true);
                resource.pane.setStretchFactor(0.25);
            }
            const destination = overlay ? this.pricePane : (resource.pane ?? this.pricePane);
            for (const curve of resource.curves.values())
                curve.series.moveToPane(destination.paneIndex());
            if (overlay && resource.pane !== null) this.removePane(resource);
            if (resource.fill !== null) {
                resource.fill.series.detachPrimitive(resource.fill.primitive);
                resource.fill = null;
            }
            const curveKeys = new Set<string>();
            for (const output of outputs) {
                const kind = output.metadata?.kind ?? "LINE";
                const segments =
                    output.view?.status === "PROJECTED" ? output.view.projection.segments : [];
                for (const [index, segment] of segments.entries()) {
                    const key = JSON.stringify([output.name, index]);
                    curveKeys.add(key);
                    let curve = resource.curves.get(key);
                    if (curve !== undefined && curve.kind !== kind) {
                        this.chart.removeSeries(curve.series);
                        resource.curves.delete(key);
                        curve = undefined;
                    }
                    const style = instance.presentation;
                    const color = studySeriesColor(instance, output.name);
                    if (curve === undefined) {
                        const options = { lastValueVisible: false, priceLineVisible: false, color };
                        curve = {
                            kind,
                            data: [],
                            series:
                                kind === "HISTOGRAM"
                                    ? this.chart.addSeries(
                                          HistogramSeries,
                                          options,
                                          destination.paneIndex()
                                      )
                                    : this.chart.addSeries(
                                          LineSeries,
                                          { ...options, crosshairMarkerVisible: true },
                                          destination.paneIndex()
                                      )
                        };
                        resource.curves.set(key, curve);
                    }
                    curve.series.applyOptions({
                        color,
                        priceScaleId:
                            output.view?.status === "PROJECTED" &&
                            output.view.projection.outputUnit === "PRICE"
                                ? "right"
                                : (output.metadata?.unit ?? "right"),
                        ...(kind === "LINE"
                            ? {
                                  lineWidth: Math.min(
                                      4,
                                      Math.max(
                                          1,
                                          Math.round(style.lineWidth) +
                                              (selectedId === instance.instanceId ? 1 : 0)
                                      )
                                  ) as LineWidth
                              }
                            : {})
                    });
                    const previous = curve.data;
                    const samePoint = (a: (typeof segment)[number], b: (typeof segment)[number]) =>
                        a.time === b.time &&
                        ("value" in a ? a.value : undefined) ===
                            ("value" in b ? b.value : undefined);
                    const incremental =
                        previous.length > 0 &&
                        segment.length >= previous.length &&
                        previous.every((point, index) => {
                            const next = segment[index];
                            return (
                                point.time === next?.time &&
                                (index === previous.length - 1 || samePoint(point, next))
                            );
                        });
                    if (incremental) {
                        for (let index = previous.length - 1; index < segment.length; index++) {
                            const point = segment[index];
                            const prior = previous[index];
                            if (
                                point !== undefined &&
                                (prior === undefined || !samePoint(prior, point))
                            )
                                curve.series.update(point);
                        }
                    } else curve.series.setData([...segment]);
                    curve.data = segment;
                }
            }
            const fill =
                instance.selection.source === "CHART_STUDY_TRANSIENT"
                    ? instance.selection.capability.presentation.fill
                    : null;
            if (fill !== null) {
                const upper = outputs.find((output) => output.name === fill[0]);
                const lower = outputs.find((output) => output.name === fill[1]);
                const owner = resource.curves.get(JSON.stringify([fill[0], 0]));
                if (
                    upper?.view?.status === "PROJECTED" &&
                    lower?.view?.status === "PROJECTED" &&
                    owner !== undefined
                ) {
                    const primitive = new StudyBandFill(
                        bandPolygons(upper.view.projection, lower.view.projection),
                        `${upper.metadata?.color ?? instance.presentation.color}22`
                    );
                    owner.series.attachPrimitive(primitive);
                    resource.fill = { series: owner.series, primitive };
                }
            }
            for (const [key, curve] of resource.curves)
                if (!curveKeys.has(key)) {
                    this.chart.removeSeries(curve.series);
                    resource.curves.delete(key);
                }
            if (resource.pane !== null && resource.curves.size === 0) {
                resource.label ??= Object.assign(document.createElement("p"), {
                    className: "study-pane-empty"
                });
                resource.label.dataset.instanceId = instance.instanceId;
                resource.label.textContent = outputs
                    .map(
                        (output) =>
                            `${output.name} · ${output.view?.status === "PROJECTED" ? "无可绘制点" : (output.view?.detail ?? "尚未计算")}`
                    )
                    .join(" · ");
            } else {
                resource.label?.remove();
                resource.label = null;
            }
        }
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        this.frame = requestAnimationFrame(() => {
            this.frame = null;
            for (const resource of this.resources.values())
                if (resource.label !== null)
                    resource.pane
                        ?.getHTMLElement()
                        ?.querySelector("td > div")
                        ?.append(resource.label);
        });
    }
    get seriesCount(): number {
        return [...this.resources.values()].reduce((sum, item) => sum + item.curves.size, 0);
    }
    dispose(): void {
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        for (const resource of this.resources.values()) this.release(resource);
        this.resources.clear();
    }
    private removePane(resource: Resource): void {
        resource.label?.remove();
        resource.label = null;
        if (resource.pane !== null) this.chart.removePane(resource.pane.paneIndex());
        resource.pane = null;
    }
    private release(resource: Resource): void {
        if (resource.fill !== null) resource.fill.series.detachPrimitive(resource.fill.primitive);
        for (const curve of resource.curves.values()) this.chart.removeSeries(curve.series);
        resource.curves.clear();
        this.removePane(resource);
    }
}
