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
    MouseEventParams,
    Time,
    UTCTimestamp
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import type { MarketDataBarSemantic } from "../../api/marketData/model";
import { deriveTimeAxisPolicy } from "./timeAxisPolicy";
import {
    toCandlestick,
    toCloseLine,
    type FinancialChartType,
    type MarketDataChartBarProjection,
    type MarketDataChartSelection
} from "./marketDataChartProjection";
const utcTime = (seconds: number) => new Date(seconds * 1_000).toISOString();
type RenderBar = CandlestickData<UTCTimestamp> & { readonly barStartNs?: string };
const barIdentity = (bar: RenderBar) => bar.barStartNs ?? String(bar.time);

function publishVisibleAnchor(
    element: HTMLDivElement | null,
    bars: readonly RenderBar[],
    range: LogicalRange | null
): void {
    if (element === null) return;
    const anchor = range === null ? undefined : bars[Math.max(0, Math.ceil(range.from))];
    element.dataset.visibleRangeFrom = range === null ? "" : String(range.from);
    element.dataset.visibleRangeTo = range === null ? "" : String(range.to);
    element.dataset.visibleAnchorTime = anchor === undefined ? "" : String(anchor.time);
    element.dataset.visibleAnchorStartNs = anchor?.barStartNs ?? "";
}

export function PriceChart({
    barSemantic,
    bars: productBars,
    liveBar = null,
    contextKey = null,
    chartType = "CANDLESTICK",
    onSelection,
    onNearLeftEdge
}: {
    readonly barSemantic?: MarketDataBarSemantic | undefined;
    readonly bars: readonly MarketDataChartBarProjection[];
    readonly liveBar?: MarketDataChartBarProjection | null;
    readonly chartType?: FinancialChartType;
    readonly onSelection?: ((selection: MarketDataChartSelection | null) => void) | undefined;
    readonly contextKey?: string | null;
    readonly onNearLeftEdge?: (() => void) | undefined;
}) {
    const container = useRef<HTMLDivElement>(null);
    const priceSeries = useRef<ISeriesApi<"Candlestick" | "Line"> | null>(null);
    const activeType = useRef<FinancialChartType>("CANDLESTICK");
    const selectionContext = useRef({ contextKey, productBars, liveBar, onSelection });
    const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const previousContextKey = useRef<string | null>(null);
    const initializedNonEmptyContext = useRef(false);
    const previousBars = useRef<readonly RenderBar[]>([]);
    const rendererBars = useRef<readonly RenderBar[]>([]);
    const placingHistory = useRef(false);
    const nearLeftEdgeArmed = useRef(false);
    const nearLeftEdgeCallback = useRef(onNearLeftEdge);
    const lastRenderedTime = useRef<number | null>(null);
    const bars = useMemo(
        () => productBars.map((bar) => ({ ...toCandlestick(bar), barStartNs: bar.barStartNs })),
        [productBars]
    );

    useEffect(() => {
        nearLeftEdgeCallback.current = onNearLeftEdge;
    }, [onNearLeftEdge]);

    useEffect(() => {
        selectionContext.current = { contextKey, productBars, liveBar, onSelection };
    }, [contextKey, productBars, liveBar, onSelection]);

    useEffect(() => {
        onSelection?.(null);
    }, [contextKey, onSelection]);

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
        priceSeries.current = series;
        activeType.current = "CANDLESTICK";
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
        const handleCrosshair = (event: MouseEventParams) => {
            const current = selectionContext.current;
            const selected =
                event.point === undefined || typeof event.time !== "number"
                    ? undefined
                    : current.liveBar?.time === event.time
                      ? current.liveBar
                      : current.productBars.find((bar) => bar.time === event.time);
            current.onSelection?.(
                selected === undefined || current.contextKey === null
                    ? null
                    : { contextKey: current.contextKey, barStartNs: selected.barStartNs }
            );
        };
        chart.subscribeCrosshairMove(handleCrosshair);
        return () => {
            chart.unsubscribeCrosshairMove(handleCrosshair);
            timeScale.unsubscribeVisibleLogicalRangeChange(handleVisibleRange);
            chartRef.current = null;
            priceSeries.current = null;
            lastRenderedTime.current = null;
            previousBars.current = [];
            rendererBars.current = [];
            initializedNonEmptyContext.current = false;
            nearLeftEdgeArmed.current = false;
            chart.remove();
        };
    }, []);

    useEffect(() => {
        const chart = chartRef.current;
        const series = priceSeries.current;
        const element = container.current;
        if (
            chart === null ||
            series === null ||
            element === null ||
            activeType.current === chartType
        )
            return;
        const range = chart.timeScale().getVisibleLogicalRange();
        placingHistory.current = true;
        chart.removeSeries(series);
        const tokens = getComputedStyle(element);
        const up = tokens.getPropertyValue("--up").trim() || "#c8332a";
        const down = tokens.getPropertyValue("--down").trim() || "#2f7d47";
        priceSeries.current =
            chartType === "LINE"
                ? chart.addSeries(LineSeries, {
                      color: tokens.getPropertyValue("--accent").trim() || "#1f5f8b",
                      lineWidth: 2
                  })
                : chart.addSeries(CandlestickSeries, {
                      upColor: up,
                      downColor: down,
                      borderUpColor: up,
                      borderDownColor: down,
                      wickUpColor: up,
                      wickDownColor: down
                  });
        activeType.current = chartType;
        priceSeries.current.setData(
            rendererBars.current.map((bar) =>
                chartType === "LINE" ? { time: bar.time, value: bar.close } : bar
            )
        );
        if (range !== null) chart.timeScale().setVisibleLogicalRange(range);
        publishVisibleAnchor(element, rendererBars.current, range);
        placingHistory.current = false;
    }, [chartType]);

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
        const firstPrior = priorBars[0];
        const prependCount =
            firstPrior === undefined
                ? -1
                : bars.findIndex((bar) => barIdentity(bar) === barIdentity(firstPrior));
        const strictPrepend =
            !contextChanged &&
            initializedNonEmptyContext.current &&
            priorBars.length > 0 &&
            prependCount > 0 &&
            priorBars.every((bar, index) => {
                const current = bars[index + prependCount];
                return current !== undefined && barIdentity(bar) === barIdentity(current);
            });
        placingHistory.current = true;
        rendererBars.current = bars;
        priceSeries.current?.setData(
            bars.map((bar) =>
                activeType.current === "LINE" ? { time: bar.time, value: bar.close } : bar
            )
        );
        lastRenderedTime.current = bars.at(-1)?.time ?? null;
        if (barSemantic !== undefined && firstNonEmptyHistory) {
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
    }, [barSemantic, bars, contextKey]);

    useEffect(() => {
        if (liveBar === null || priceSeries.current === null) return;
        if (lastRenderedTime.current !== null && liveBar.time < lastRenderedTime.current) return;
        const rendered = { ...toCandlestick(liveBar), barStartNs: liveBar.barStartNs };
        priceSeries.current.update(activeType.current === "LINE" ? toCloseLine(liveBar) : rendered);
        rendererBars.current = [...bars.filter((bar) => bar.time !== liveBar.time), rendered];
        publishVisibleAnchor(
            container.current,
            rendererBars.current,
            chartRef.current?.timeScale().getVisibleLogicalRange() ?? null
        );
        lastRenderedTime.current = liveBar.time;
    }, [barSemantic, bars, contextKey, liveBar]);

    return (
        <div
            className="chart-region__canvas"
            ref={container}
            data-testid="price-chart"
            data-chart-type={chartType}
            onMouseLeave={() => onSelection?.(null)}
        />
    );
}
