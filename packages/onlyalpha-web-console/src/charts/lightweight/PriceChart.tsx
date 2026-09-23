import { CandlestickSeries, ColorType, createChart } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import { buildPlaceholderBars, type Timeframe } from "./placeholderBars";

export function PriceChart({ timeframe }: { readonly timeframe: Timeframe }) {
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
        const observer = new ResizeObserver(() => {
            chart.timeScale().fitContent();
        });
        observer.observe(element);
        chart.timeScale().fitContent();
        return () => {
            observer.disconnect();
            chart.remove();
        };
    }, [bars]);

    return <div className="chart-region__canvas" ref={container} data-testid="price-chart" />;
}
