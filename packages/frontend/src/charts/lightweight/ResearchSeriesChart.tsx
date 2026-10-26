import {
    ColorType,
    createChart,
    LineSeries,
    type LineData,
    type UTCTimestamp,
    type WhitespaceData
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { ResearchChartPoint } from "../model";

export function ResearchSeriesChart({
    points
}: {
    readonly points: readonly ResearchChartPoint[];
}) {
    const container = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const element = container.current;
        if (element === null) return;
        const chart = createChart(element, {
            autoSize: true,
            height: 320,
            layout: {
                background: { type: ColorType.Solid, color: "#111827" },
                textColor: "#dbeafe"
            },
            grid: { vertLines: { color: "#243047" }, horzLines: { color: "#243047" } }
        });
        const series = chart.addSeries(LineSeries, { color: "#67e8f9", lineWidth: 2 });
        const data: (LineData | WhitespaceData)[] = points.map((point) =>
            "value" in point
                ? { time: point.time.valueOf() as UTCTimestamp, value: point.value }
                : { time: point.time.valueOf() as UTCTimestamp }
        );
        series.setData(data);
        const observer = new ResizeObserver(() => {
            chart.timeScale().fitContent();
        });
        observer.observe(element);
        chart.timeScale().fitContent();
        return () => {
            observer.disconnect();
            chart.remove();
        };
    }, [points]);

    return (
        <section aria-label="Statistics chart">
            <div className="chart" ref={container} data-testid="research-chart" />
            <p className="attribution">
                Charting by{" "}
                <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
                    TradingView
                </a>
            </p>
        </section>
    );
}
