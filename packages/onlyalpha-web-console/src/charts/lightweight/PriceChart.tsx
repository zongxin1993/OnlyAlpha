import {
    CandlestickSeries,
    ColorType,
    LineSeries,
    TickMarkType,
    createChart
} from "lightweight-charts";
import type {
    CandlestickData,
    ISeriesApi,
    LogicalRange,
    Time,
    UTCTimestamp
} from "lightweight-charts";
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

function publishVisibleAnchor(
    element: HTMLDivElement | null,
    bars: readonly CandlestickData<UTCTimestamp>[],
    range: LogicalRange | null
): void {
    if (element === null) return;
    const anchor = range === null ? undefined : bars[Math.max(0, Math.ceil(range.from))];
    element.dataset.visibleRangeFrom = range === null ? "" : String(range.from);
    element.dataset.visibleAnchorTime = anchor === undefined ? "" : String(anchor.time);
}

export function PriceChart({
    timeframe,
    barSemantic,
    overlays = EMPTY_OVERLAYS,
    mode,
    bars: productBars,
    liveBar = null,
    contextKey = null,
    onNearLeftEdge
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
    readonly contextKey?: string | null;
    readonly onNearLeftEdge?: (() => void) | undefined;
}) {
    const container = useRef<HTMLDivElement>(null);
    const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const overlaySeries = useRef<readonly ISeriesApi<"Line">[]>([]);
    const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const previousContextKey = useRef<string | null>(null);
    const initializedNonEmptyContext = useRef(false);
    const previousBars = useRef<readonly CandlestickData<UTCTimestamp>[]>([]);
    const rendererBars = useRef<readonly CandlestickData<UTCTimestamp>[]>([]);
    const placingHistory = useRef(false);
    const nearLeftEdgeArmed = useRef(false);
    const nearLeftEdgeCallback = useRef(onNearLeftEdge);
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
        nearLeftEdgeCallback.current = onNearLeftEdge;
    }, [onNearLeftEdge]);

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
        const timeScale = chart.timeScale();
        const handleVisibleRange = (range: LogicalRange | null) => {
            publishVisibleAnchor(container.current, rendererBars.current, range);
            if (placingHistory.current || !initializedNonEmptyContext.current) return;
            if (range === null) return;
            if (range.from <= 24) {
                if (nearLeftEdgeArmed.current) {
                    nearLeftEdgeArmed.current = false;
                    nearLeftEdgeCallback.current?.();
                }
            } else nearLeftEdgeArmed.current = true;
        };
        timeScale.subscribeVisibleLogicalRangeChange(handleVisibleRange);
        return () => {
            timeScale.unsubscribeVisibleLogicalRangeChange(handleVisibleRange);
            chartRef.current = null;
            candleSeries.current = null;
            overlaySeries.current = [];
            lastRenderedTime.current = null;
            previousBars.current = [];
            rendererBars.current = [];
            initializedNonEmptyContext.current = false;
            nearLeftEdgeArmed.current = false;
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
        const timeScale = chartRef.current?.timeScale();
        const visibleRange = timeScale?.getVisibleLogicalRange() ?? null;
        const priorBars = previousBars.current;
        const contextChanged = previousContextKey.current !== contextKey;
        if (contextChanged) {
            initializedNonEmptyContext.current = false;
            nearLeftEdgeArmed.current = false;
        }
        const firstNonEmptyHistory = !initializedNonEmptyContext.current && bars.length > 0;
        const prependCount =
            priorBars.length === 0 ? -1 : bars.findIndex((bar) => bar.time === priorBars[0]?.time);
        const strictPrepend =
            !contextChanged &&
            initializedNonEmptyContext.current &&
            priorBars.length > 0 &&
            prependCount > 0 &&
            priorBars.every((bar, index) => bar.time === bars[index + prependCount]?.time);
        placingHistory.current = true;
        rendererBars.current = bars;
        candleSeries.current?.setData([...bars]);
        lastRenderedTime.current = bars.at(-1)?.time ?? null;
        if (mode === "real" && barSemantic !== undefined && firstNonEmptyHistory) {
            const visible = deriveTimeAxisPolicy(
                barSemantic,
                container.current?.clientWidth ?? 600
            ).visibleBars;
            nearLeftEdgeArmed.current = false;
            timeScale?.setVisibleLogicalRange({
                from: Math.max(0, bars.length - visible),
                to: bars.length + 4
            });
        } else if (strictPrepend && visibleRange !== null) {
            const shifted = {
                from: visibleRange.from + prependCount,
                to: visibleRange.to + prependCount
            };
            timeScale?.setVisibleLogicalRange(shifted);
        }
        initializedNonEmptyContext.current = bars.length > 0;
        placingHistory.current = false;
        publishVisibleAnchor(
            container.current,
            rendererBars.current,
            timeScale?.getVisibleLogicalRange() ?? null
        );
        previousContextKey.current = contextKey;
        previousBars.current = bars;
        overlaySeries.current.forEach((series, index) => {
            const overlay = renderedOverlays[index];
            if (overlay !== undefined) series.setData(buildPlaceholderOverlay([...bars], overlay));
        });
    }, [barSemantic, bars, contextKey, mode, renderedOverlays]);

    useEffect(() => {
        if (mode !== "real" || liveBar === null || candleSeries.current === null) return;
        if (lastRenderedTime.current !== null && liveBar.time < lastRenderedTime.current) return;
        candleSeries.current.update(liveBar);
        rendererBars.current = [...bars.filter((bar) => bar.time !== liveBar.time), liveBar];
        publishVisibleAnchor(
            container.current,
            rendererBars.current,
            chartRef.current?.timeScale().getVisibleLogicalRange() ?? null
        );
        lastRenderedTime.current = liveBar.time;
    }, [barSemantic, bars, contextKey, liveBar, mode]);

    return <div className="chart-region__canvas" ref={container} data-testid="price-chart" />;
}
