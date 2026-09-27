import { CandlestickSeries, ColorType, LineSeries, createChart } from "lightweight-charts";
import type { CandlestickData, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import {
    buildPlaceholderBars,
    buildPlaceholderOverlay,
    OVERLAY_COLORS,
    type OverlaySpec,
    type Timeframe
} from "./placeholderBars";

const EMPTY_OVERLAYS: readonly OverlaySpec[] = [];

export function PriceChart({
    timeframe,
    overlays = EMPTY_OVERLAYS,
    mode,
    bars: productBars,
    liveBar = null,
    historyKey = null
}: {
    readonly timeframe: Timeframe;
    readonly overlays?: readonly OverlaySpec[];
    /**
     * `synthetic` renders the deterministic W0 placeholder series. `real` renders only
     * canonical Product bars and never invents a price, an overlay or an indicator.
     */
    readonly mode: "synthetic" | "real";
    readonly bars: readonly CandlestickData<UTCTimestamp>[];
    readonly liveBar?: CandlestickData<UTCTimestamp> | null;
    readonly historyKey?: string | null;
}) {
    const container = useRef<HTMLDivElement>(null);
    const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const overlaySeries = useRef<readonly ISeriesApi<"Line">[]>([]);
    const bars = useMemo(
        () => (mode === "synthetic" ? buildPlaceholderBars(timeframe) : productBars),
        [mode, productBars, timeframe]
    );
    const renderedOverlays = useMemo(
        () => (mode === "synthetic" ? overlays : EMPTY_OVERLAYS),
        [mode, overlays]
    );

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
        candleSeries.current = series;
        overlaySeries.current = renderedOverlays.map((overlay, index) => {
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
            return line;
        });
        const observer = new ResizeObserver(() => {
            chart.timeScale().fitContent();
        });
        observer.observe(element);
        chart.timeScale().fitContent();
        return () => {
            observer.disconnect();
            candleSeries.current = null;
            overlaySeries.current = [];
            chart.remove();
        };
    }, [renderedOverlays]);

    useEffect(() => {
        candleSeries.current?.setData([...bars]);
        overlaySeries.current.forEach((series, index) => {
            const overlay = renderedOverlays[index];
            if (overlay !== undefined) series.setData(buildPlaceholderOverlay([...bars], overlay));
        });
    }, [bars, historyKey, renderedOverlays]);

    useEffect(() => {
        if (liveBar !== null) candleSeries.current?.update(liveBar);
    }, [liveBar]);

    return <div className="chart-region__canvas" ref={container} data-testid="price-chart" />;
}
