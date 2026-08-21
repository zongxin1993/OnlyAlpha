import type { EChartsOption, EChartsType } from "echarts";
import { useEffect, useRef, useState } from "react";
import type { CandidateSurface, ScientificSeriesPoint } from "../../model/scientific";
import { candidateAxis } from "../../projection/scientificProjection";

type ScientificEvidence =
    | {
          readonly kind: "TIME_SERIES";
          readonly name: string;
          readonly points: readonly ScientificSeriesPoint[];
      }
    | { readonly kind: "CANDIDATE_SURFACE"; readonly surface: CandidateSurface };

export function ScientificEvidenceChart({ evidence }: { readonly evidence: ScientificEvidence }) {
    const container = useRef<HTMLDivElement>(null);
    const [failure, setFailure] = useState<string | null>(null);
    useEffect(() => {
        const element = container.current;
        if (element === null) return;
        let active = true;
        let chart: EChartsType | undefined;
        let observer: ResizeObserver | undefined;
        void import("echarts")
            .then(({ init }) => {
                if (!active) return;
                chart = init(element, "dark", { renderer: "canvas" });
                chart.setOption(optionFor(evidence), { notMerge: true });
                observer = new ResizeObserver(() => chart?.resize());
                observer.observe(element);
                setFailure(null);
            })
            .catch(() => {
                if (active)
                    setFailure("SCIENTIFIC_RENDER_ERROR: ECharts rejected the admitted projection");
            });
        return () => {
            active = false;
            observer?.disconnect();
            chart?.dispose();
        };
    }, [evidence]);
    return (
        <>
            {failure === null ? null : (
                <p className="error" role="alert">
                    {failure}
                </p>
            )}
            <div className="scientific-chart" ref={container} data-testid="scientific-chart" />
        </>
    );
}

function optionFor(evidence: ScientificEvidence): EChartsOption {
    if (evidence.kind === "TIME_SERIES")
        return {
            animation: false,
            tooltip: { trigger: "axis" },
            xAxis: {
                type: "category",
                data: evidence.points.map((point) => point.timeLabel),
                axisLabel: { hideOverlap: true }
            },
            yAxis: { type: "value", scale: true },
            series: [
                {
                    name: evidence.name,
                    type: "line",
                    showSymbol: false,
                    connectNulls: false,
                    data: evidence.points.map((point) => point.value)
                }
            ],
            dataZoom: [{ type: "inside" }, { type: "slider" }]
        };
    const { surface } = evidence;
    if (surface.mode === "TWO_DIMENSIONS") {
        const [x = "x", y = "y"] = surface.dimensions;
        const xValues = candidateAxis(surface, x);
        const yValues = candidateAxis(surface, y);
        return {
            animation: false,
            tooltip: { position: "top" },
            xAxis: { type: "category", name: x, data: xValues.map((item) => item.label) },
            yAxis: { type: "category", name: y, data: yValues.map((item) => item.label) },
            visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center" },
            series: [
                {
                    type: "heatmap",
                    data: surface.points.map((point) => [
                        xValues.findIndex(
                            (item) => item.coordinate === point.numericCoordinates[x]
                        ),
                        yValues.findIndex(
                            (item) => item.coordinate === point.numericCoordinates[y]
                        ),
                        point.value
                    ])
                }
            ]
        };
    }
    if (surface.mode === "MULTI_DIMENSION")
        return {
            animation: false,
            parallelAxis: [
                ...surface.dimensions.map((dimension, index) => ({
                    dim: index,
                    name: dimension,
                    type: "value" as const
                })),
                { dim: surface.dimensions.length, name: "Exact statistic", type: "value" as const }
            ],
            parallel: { left: 60, right: 60, bottom: 40, top: 40 },
            series: [
                {
                    type: "parallel",
                    data: surface.points.map((point) => [
                        ...surface.dimensions.map(
                            (dimension) => point.numericCoordinates[dimension]
                        ),
                        point.value
                    ])
                }
            ]
        };
    const dimension = surface.dimensions[0] ?? "Candidate";
    return {
        animation: false,
        tooltip: { trigger: "item" },
        xAxis: { type: "value", name: dimension, scale: true },
        yAxis: { type: "value", name: "Exact statistic", scale: true },
        series: [
            {
                type: "scatter",
                data: surface.points.map((point) => [
                    point.numericCoordinates[dimension],
                    point.value
                ])
            }
        ]
    };
}
