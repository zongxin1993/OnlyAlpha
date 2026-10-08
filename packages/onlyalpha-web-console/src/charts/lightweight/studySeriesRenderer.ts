import {
    LineSeries,
    type IChartApi,
    type IPaneApi,
    type ISeriesApi,
    type LineWidth,
    type Time
} from "lightweight-charts";
import type { ChartStudyInstance } from "../../features/workspace/chartStudy";
import { validPresentation } from "../../features/workspace/chartStudy";
import type { StudySeriesView } from "./studySeriesProjection";

interface Resource {
    readonly lines: ISeriesApi<"Line">[];
    pane: IPaneApi<Time> | null;
    label: HTMLParagraphElement | null;
    projection: StudySeriesView | null;
}

/** One chart, one private pane per instance. Stable refs survive index compaction. */
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
        const wanted = new Set(
            instances
                .filter((item) => item.presentation.visible && validPresentation(item.presentation))
                .map((item) => item.instanceId)
        );
        for (const [id, resource] of this.resources)
            if (!wanted.has(id)) {
                this.release(resource);
                this.resources.delete(id);
            }
        for (const instance of instances) {
            if (!instance.presentation.visible || !validPresentation(instance.presentation))
                continue;
            const view = views.get(instance.instanceId);
            if (view === undefined) continue;
            let resource = this.resources.get(instance.instanceId);
            if (resource === undefined) {
                resource = { lines: [], pane: null, label: null, projection: null };
                this.resources.set(instance.instanceId, resource);
            }
            if (instance.presentation.placement === "SEPARATE_PANE" && resource.pane === null) {
                resource.pane = this.chart.addPane(true);
                resource.pane.setStretchFactor(0.25);
            }
            const destination = resource.pane ?? this.pricePane;
            // Move before deleting the old preserved pane; its index may compact.
            if (instance.presentation.placement === "PRICE_OVERLAY" && resource.pane !== null) {
                for (const line of resource.lines) line.moveToPane(this.pricePane.paneIndex());
                this.removePane(resource);
            } else for (const line of resource.lines) line.moveToPane(destination.paneIndex());
            const segments = view.status === "PROJECTED" ? view.projection.segments : [];
            while (resource.lines.length > segments.length) {
                const line = resource.lines.pop();
                if (line !== undefined) this.chart.removeSeries(line);
            }
            while (resource.lines.length < segments.length)
                resource.lines.push(
                    this.chart.addSeries(
                        LineSeries,
                        {
                            lastValueVisible: false,
                            priceLineVisible: false,
                            crosshairMarkerVisible: true
                        },
                        (resource.pane ?? this.pricePane).paneIndex()
                    )
                );
            const style = instance.presentation;
            const color = `${style.color}${Math.round(style.opacity * 255)
                .toString(16)
                .padStart(2, "0")}`;
            resource.lines.forEach((line, index) => {
                line.applyOptions({
                    color,
                    lineWidth: Math.min(
                        4,
                        Math.max(
                            1,
                            Math.round(style.lineWidth) +
                                (selectedId === instance.instanceId ? 1 : 0)
                        )
                    ) as LineWidth
                });
                const segment = segments[index];
                if (segment !== undefined && resource.projection !== view)
                    line.setData([...segment]);
            });
            resource.projection = view;
            if (resource.pane !== null && segments.length === 0) {
                if (resource.label === null) {
                    resource.label = document.createElement("p");
                    resource.label.className = "study-pane-empty";
                    resource.label.dataset.instanceId = instance.instanceId;
                }
                resource.label.textContent = `${instance.configuration.outputName} · ${view.status === "PROJECTED" ? "无可绘制点" : view.detail}`;
            } else {
                resource.label?.remove();
                resource.label = null;
            }
        }
        if (this.frame !== null) cancelAnimationFrame(this.frame);
        // Pane DOM is installed by the renderer on its next paint, not addPane().
        this.frame = requestAnimationFrame(() => {
            this.frame = null;
            for (const resource of this.resources.values())
                if (resource.label !== null)
                    // v5.2.1 exposes a native table row. Text belongs inside its
                    // relative plot wrapper, never an extra anonymous table cell.
                    resource.pane
                        ?.getHTMLElement()
                        ?.querySelector("td > div")
                        ?.append(resource.label);
        });
    }
    get seriesCount(): number {
        return [...this.resources.values()].reduce((sum, item) => sum + item.lines.length, 0);
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
        for (const line of resource.lines) this.chart.removeSeries(line);
        resource.lines.length = 0;
        this.removePane(resource);
    }
}
