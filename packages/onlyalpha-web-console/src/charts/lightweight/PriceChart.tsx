import {
    CandlestickSeries,
    ColorType,
    LineSeries,
    TickMarkType,
    createChart
} from "lightweight-charts";
import type { CandlestickData, ISeriesApi, Time, UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import type { MarketDataBarSemantic } from "../../api/marketData/model";
import { deriveTimeAxisPolicy } from "./timeAxisPolicy";
import {
    buildPlaceholderBars,
    buildPlaceholderOverlay,
    OVERLAY_COLORS,
    type OverlaySpec,
    type Timeframe
} from "./placeholderBars";

const EMPTY_OVERLAYS: readonly OverlaySpec[] = [];

const utcTime = (seconds: number) => new Date(seconds * 1_000).toISOString();

export function PriceChart({
    timeframe,
    barSemantic,
    overlays = EMPTY_OVERLAYS,
    mode,
    bars: productBars,
    liveBar = null,
    historyKey = null
}: {
    readonly timeframe?: Timeframe | undefined;
    readonly barSemantic?: MarketDataBarSemantic | undefined;
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
    const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const previousHistoryKey = useRef<string | null>(null);
    const lastRenderedTime = useRef<number | null>(null);
    const bars = useMemo(
        () => (mode === "synthetic" ? buildPlaceholderBars(timeframe ?? "1D") : productBars),
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
            localization: {
                timeFormatter: (time: Time) =>
                    typeof time === "number"
                        ? `${utcTime(time).slice(0, 16).replace("T", " ")} UTC`
                        : ""
            },
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
            timeScale: {
                borderColor: token("--line", "#e2e2dd"),
                timeVisible: false,
                secondsVisible: false,
                tickMarkFormatter: (time: Time, kind: TickMarkType) => {
                    if (typeof time !== "number") return null;
                    const value = utcTime(time);
                    return kind === TickMarkType.Time || kind === TickMarkType.TimeWithSeconds
                        ? value.slice(11, 16)
                        : value.slice(5, 10);
                }
            }
        });
        chartRef.current = chart;
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
        return () => {
            chartRef.current = null;
            candleSeries.current = null;
            overlaySeries.current = [];
            lastRenderedTime.current = null;
            chart.remove();
        };
    }, [renderedOverlays]);

    useEffect(() => {
        const chart = chartRef.current;
        if (chart === null || barSemantic === undefined) return;
        chart.timeScale().applyOptions({
            timeVisible: deriveTimeAxisPolicy(barSemantic, container.current?.clientWidth ?? 600)
                .timeVisible,
            secondsVisible: false
        });
    }, [barSemantic]);

    useEffect(() => {
        candleSeries.current?.setData([...bars]);
        lastRenderedTime.current = bars.at(-1)?.time ?? null;
        if (
            mode === "real" &&
            barSemantic !== undefined &&
            previousHistoryKey.current !== historyKey &&
            bars.length > 0
        ) {
            const visible = deriveTimeAxisPolicy(
                barSemantic,
                container.current?.clientWidth ?? 600
            ).visibleBars;
            chartRef.current?.timeScale().setVisibleLogicalRange({
                from: Math.max(0, bars.length - visible),
                to: bars.length + 4
            });
        }
        previousHistoryKey.current = historyKey;
        overlaySeries.current.forEach((series, index) => {
            const overlay = renderedOverlays[index];
            if (overlay !== undefined) series.setData(buildPlaceholderOverlay([...bars], overlay));
        });
    }, [barSemantic, bars, historyKey, mode, renderedOverlays]);

    useEffect(() => {
        if (mode !== "real" || liveBar === null || candleSeries.current === null) return;
        if (lastRenderedTime.current !== null && liveBar.time < lastRenderedTime.current) return;
        candleSeries.current.update(liveBar);
        lastRenderedTime.current = liveBar.time;
    }, [barSemantic, bars, historyKey, liveBar, mode]);

    return <div className="chart-region__canvas" ref={container} data-testid="price-chart" />;
}
