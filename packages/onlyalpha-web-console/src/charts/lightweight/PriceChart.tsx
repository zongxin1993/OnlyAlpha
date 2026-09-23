import { CandlestickSeries, ColorType, LineSeries, createChart } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import {
    buildPlaceholderBars,
    buildPlaceholderOverlay,
    OVERLAY_COLORS,
    type OverlaySpec,
    type Timeframe
} from "./placeholderBars";

export function PriceChart({
    timeframe,
    overlays = []
}: {
    readonly timeframe: Timeframe;
    readonly overlays?: readonly OverlaySpec[];
}) {
    const container = useRef<HTMLDivElement>(null);
    const bars = useMemo(() => buildPlaceholderBars(timeframe), [timeframe]);

    useEffect(() => {
        const element = container.current;
        if (element === null) return;
        const tokens = getComputedStyle(element);
        const token = (name: string, fallback: string) =>
            tokens.getPropertyValue(name).trim() || fallback;
        const chart = createChart(element, {
            autoSize: true,
            layout: {
                background: { type: ColorType.Solid, color: token("--surface", "#ffffff") },
                textColor: token("--muted", "#5f6874"),
                fontFamily: token("--font-mono", "ui-monospace, monospace")
            },
            grid: {
                vertLines: { color: token("--line-soft", "#eceae4") },
                horzLines: { color: token("--line-soft", "#eceae4") }
            },
            rightPriceScale: { borderColor: token("--line", "#e2e2dd") },
            timeScale: { borderColor: token("--line", "#e2e2dd") }
        });
        const series = chart.addSeries(CandlestickSeries, {
            upColor: token("--up", "#c8332a"),
            downColor: token("--down", "#2f7d47"),
            borderUpColor: token("--up", "#c8332a"),
            borderDownColor: token("--down", "#2f7d47"),
            wickUpColor: token("--up", "#c8332a"),
            wickDownColor: token("--down", "#2f7d47")
        });
        series.setData(bars);
        overlays.forEach((overlay, index) => {
            const line = chart.addSeries(
                LineSeries,
                {
                    color: OVERLAY_COLORS[index % OVERLAY_COLORS.length] ?? "#1f5f8b",
                    lineWidth: 2,
                    priceLineVisible: false,
                    lastValueVisible: overlay.kind === "indicator",
                    title: overlay.label
                },
                overlay.kind === "factor" ? 1 : 0
            );
            line.setData(buildPlaceholderOverlay(bars, overlay));
        });
        const observer = new ResizeObserver(() => {
            chart.timeScale().fitContent();
        });
        observer.observe(element);
        chart.timeScale().fitContent();
        return () => {
            observer.disconnect();
            chart.remove();
        };
    }, [bars, overlays]);

    return <div className="chart-region__canvas" ref={container} data-testid="price-chart" />;
}
