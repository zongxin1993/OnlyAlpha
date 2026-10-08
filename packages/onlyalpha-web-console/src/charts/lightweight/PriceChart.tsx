import {
    CandlestickSeries,
    ColorType,
    LineSeries,
    HistogramSeries,
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
import { useEffect, useMemo, useRef, useState } from "react";
import {
    studyDescriptor,
    validPresentation,
    type ChartStudyInstance
} from "../../features/workspace/chartStudy";
import {
    projectStudySeries,
    isStudySeriesEvidence,
    studyHover,
    type StudySeriesEvidence
} from "./studySeriesProjection";
import { StudySeriesRenderer } from "./studySeriesRenderer";
import { rebaseChartRange } from "./chartViewport";
import "./PriceChart.css";
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
const noStudies: readonly ChartStudyInstance[] = [];
const noEvidence: readonly StudySeriesEvidence[] = [];

function publishVisibleAnchor(
    element: HTMLDivElement | null,
    bars: readonly RenderBar[],
    range: LogicalRange | null,
    timeline: readonly number[] = bars.map((bar) => bar.time)
): void {
    if (element === null) return;
    const time = range === null ? undefined : timeline[Math.max(0, Math.ceil(range.from))];
    const anchor = bars.find((bar) => bar.time === time);
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
    onNearLeftEdge,
    studies = noStudies,
    selectedStudyId = null,
    incarnationKey = "",
    studyEvidence = noEvidence
}: {
    readonly barSemantic?: MarketDataBarSemantic | undefined;
    readonly bars: readonly MarketDataChartBarProjection[];
    readonly liveBar?: MarketDataChartBarProjection | null;
    readonly chartType?: FinancialChartType;
    readonly onSelection?: ((selection: MarketDataChartSelection | null) => void) | undefined;
    readonly contextKey?: string | null;
    readonly onNearLeftEdge?: (() => void) | undefined;
    readonly studies?: readonly ChartStudyInstance[];
    readonly selectedStudyId?: string | null;
    readonly incarnationKey?: string;
    readonly studyEvidence?: readonly StudySeriesEvidence[];
}) {
    const container = useRef<HTMLDivElement>(null);
    const priceSeries = useRef<ISeriesApi<"Candlestick" | "Line"> | null>(null);
    const volumeSeries = useRef<ISeriesApi<"Histogram"> | null>(null);
    const studyRenderer = useRef<StudySeriesRenderer | null>(null);
    const extraTimes = useRef<readonly number[]>([]);
    const axisTimes = useRef<readonly number[]>([]);
    const [hover, setHover] = useState<{
        readonly context: string | null;
        readonly incarnation: string;
        readonly time: number | null;
    }>({ context: null, incarnation: "", time: null });
    const timeline = useMemo(
        () => [
            ...new Set([
                ...productBars.map((bar) => bar.time),
                ...(liveBar === null ? [] : [liveBar.time])
            ])
        ],
        [productBars, liveBar]
    );
    const views = useMemo(() => {
        const entries = studies.filter((instance) => instance.context.key === contextKey);
        const duplicateInstances =
            new Set(entries.map((item) => item.instanceId)).size !== entries.length;
        const malformedEvidence = studyEvidence.some(
            (evidence) => !isStudySeriesEvidence(evidence)
        );
        return new Map(
            entries.map((instance) => {
                const matches = studyEvidence.filter(
                    (evidence) =>
                        isStudySeriesEvidence(evidence) &&
                        evidence.instanceId === instance.instanceId
                );
                return [
                    instance.instanceId,
                    duplicateInstances ||
                    matches.length > 1 ||
                    malformedEvidence ||
                    !validPresentation(instance.presentation)
                        ? { status: "INVALID" as const, detail: "重复身份 / 非法展示证据或样式" }
                        : projectStudySeries(instance, incarnationKey, timeline, matches[0])
                ] as const;
            })
        );
    }, [studies, contextKey, studyEvidence, incarnationKey, timeline]);
    const activeType = useRef<FinancialChartType>("CANDLESTICK");
    const selectionContext = useRef({
        contextKey,
        incarnationKey,
        productBars,
        liveBar,
        onSelection
    });
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
        selectionContext.current = {
            contextKey,
            incarnationKey,
            productBars,
            liveBar,
            onSelection
        };
    }, [contextKey, incarnationKey, productBars, liveBar, onSelection]);

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
        const pricePane = series.getPane();
        pricePane.setPreserveEmptyPane(true);
        pricePane.setStretchFactor(0.8);
        const volumePane = chart.addPane(true);
        volumePane.setStretchFactor(0.2);
        volumeSeries.current = chart.addSeries(
            HistogramSeries,
            {
                priceFormat: { type: "volume" },
                lastValueVisible: false,
                priceLineVisible: false,
                color: token("--accent", "#1f5f8b")
            },
            volumePane.paneIndex()
        );
        studyRenderer.current = new StudySeriesRenderer(chart, pricePane);
        activeType.current = "CANDLESTICK";
        const timeScale = chart.timeScale();
        const handleVisibleRange = (range: LogicalRange | null) => {
            publishVisibleAnchor(container.current, rendererBars.current, range, axisTimes.current);
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
            setHover({
                context: current.contextKey,
                incarnation: current.incarnationKey,
                time:
                    event.point === undefined || typeof event.time !== "number" ? null : event.time
            });
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
            studyRenderer.current?.dispose();
            studyRenderer.current = null;
            volumeSeries.current = null;
            priceSeries.current = null;
            lastRenderedTime.current = null;
            previousBars.current = [];
            rendererBars.current = [];
            initializedNonEmptyContext.current = false;
            extraTimes.current = [];
            axisTimes.current = [];
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
        const pricePane = series.getPane();
        placingHistory.current = true;
        chart.removeSeries(series);
        const tokens = getComputedStyle(element);
        const up = tokens.getPropertyValue("--up").trim() || "#c8332a";
        const down = tokens.getPropertyValue("--down").trim() || "#2f7d47";
        priceSeries.current =
            chartType === "LINE"
                ? chart.addSeries(
                      LineSeries,
                      {
                          color: tokens.getPropertyValue("--accent").trim() || "#1f5f8b",
                          lineWidth: 2
                      },
                      pricePane.paneIndex()
                  )
                : chart.addSeries(
                      CandlestickSeries,
                      {
                          upColor: up,
                          downColor: down,
                          borderUpColor: up,
                          borderDownColor: down,
                          wickUpColor: up,
                          wickDownColor: down
                      },
                      pricePane.paneIndex()
                  );
        activeType.current = chartType;
        priceSeries.current.setData(
            rendererBars.current.map((bar) =>
                chartType === "LINE" ? { time: bar.time, value: bar.close } : bar
            )
        );
        if (range !== null) chart.timeScale().setVisibleLogicalRange(range);
        publishVisibleAnchor(element, rendererBars.current, range, axisTimes.current);
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
        const beforeAxis = axisTimes.current;
        const nextAxis = [...new Set([...bars.map((bar) => bar.time), ...extraTimes.current])].sort(
            (a, b) => a - b
        );
        axisTimes.current = nextAxis;
        rendererBars.current = bars;
        priceSeries.current?.setData(
            bars.map((bar) =>
                activeType.current === "LINE" ? { time: bar.time, value: bar.close } : bar
            )
        );
        volumeSeries.current?.setData(
            productBars.map((bar) => ({ time: bar.time, value: bar.numeric.volume }))
        );
        if (container.current !== null) {
            container.current.dataset.volumePointCount = String(productBars.length);
            container.current.dataset.volumeLatest = productBars.at(-1)?.volume ?? "";
        }
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
            const shifted = rebaseChartRange(visibleRange, beforeAxis, nextAxis);
            timeScale?.setVisibleLogicalRange(shifted);
        }
        initializedNonEmptyContext.current = bars.length > 0;
        placingHistory.current = false;
        publishVisibleAnchor(
            container.current,
            rendererBars.current,
            timeScale?.getVisibleLogicalRange() ?? null,
            axisTimes.current
        );
        previousContextKey.current = contextKey;
        previousBars.current = bars;
    }, [barSemantic, bars, contextKey, productBars]);

    useEffect(() => {
        if (liveBar === null || priceSeries.current === null) return;
        if (lastRenderedTime.current !== null && liveBar.time < lastRenderedTime.current) return;
        const rendered = { ...toCandlestick(liveBar), barStartNs: liveBar.barStartNs };
        priceSeries.current.update(activeType.current === "LINE" ? toCloseLine(liveBar) : rendered);
        volumeSeries.current?.update({ time: liveBar.time, value: liveBar.numeric.volume });
        if (container.current !== null) {
            container.current.dataset.volumeLatest = liveBar.volume;
            container.current.dataset.volumePointCount = String(
                bars.filter((bar) => bar.time !== liveBar.time).length + 1
            );
        }
        rendererBars.current = [...bars.filter((bar) => bar.time !== liveBar.time), rendered];
        axisTimes.current = [
            ...new Set([...rendererBars.current.map((bar) => bar.time), ...extraTimes.current])
        ].sort((a, b) => a - b);
        publishVisibleAnchor(
            container.current,
            rendererBars.current,
            chartRef.current?.timeScale().getVisibleLogicalRange() ?? null,
            axisTimes.current
        );
        lastRenderedTime.current = liveBar.time;
    }, [barSemantic, bars, contextKey, liveBar]);

    useEffect(() => {
        const chart = chartRef.current,
            renderer = studyRenderer.current;
        if (chart === null || renderer === null) return;
        const range = chart.timeScale().getVisibleLogicalRange();
        const beforeAxis = axisTimes.current;
        const wasEmpty =
            extraTimes.current.length === 0 && renderer.seriesCount === 0 && studies.length === 0;
        const nextExtra = [
            ...new Set(
                studies
                    .filter(
                        (instance) =>
                            instance.context.key === contextKey &&
                            instance.presentation.visible &&
                            validPresentation(instance.presentation)
                    )
                    .flatMap((instance) => {
                        const view = views.get(instance.instanceId);
                        return view?.status === "PROJECTED" && view.projection.segments.length > 0
                            ? [...view.projection.pointsByTime.keys()]
                            : [];
                    })
            )
        ];
        const nextAxis = [
            ...new Set([...rendererBars.current.map((bar) => bar.time), ...nextExtra])
        ].sort((a, b) => a - b);
        placingHistory.current = true;
        renderer.sync(
            studies.filter((instance) => instance.context.key === contextKey),
            views,
            selectedStudyId
        );
        extraTimes.current = nextExtra;
        axisTimes.current = nextAxis;
        if (range !== null && !wasEmpty)
            chart.timeScale().setVisibleLogicalRange(rebaseChartRange(range, beforeAxis, nextAxis));
        placingHistory.current = false;
        if (container.current !== null) {
            container.current.dataset.studySeriesCount = String(renderer.seriesCount);
            container.current.dataset.paneCount = String(chart.panes().length);
        }
        publishVisibleAnchor(
            container.current,
            rendererBars.current,
            chart.timeScale().getVisibleLogicalRange(),
            axisTimes.current
        );
    }, [studies, views, selectedStudyId, contextKey]);

    return (
        <div className="price-chart-surface">
            <div className="study-hover" aria-label="指标悬浮信息">
                <span>Volume · 正式 Market Data Bars</span>
                {studies
                    .filter(
                        (instance) =>
                            instance.context.key === contextKey && instance.presentation.visible
                    )
                    .map((instance) => {
                        const view = views.get(instance.instanceId);
                        if (view === undefined) return null;
                        return (
                            <span
                                key={instance.instanceId}
                                data-testid="study-hover"
                                data-instance-id={instance.instanceId}
                                data-selected={selectedStudyId === instance.instanceId}
                            >
                                {studyDescriptor(instance.selection).typeId} ·{" "}
                                {instance.configuration.outputName} ·{" "}
                                {studyHover(
                                    view,
                                    hover.context === contextKey &&
                                        hover.incarnation === incarnationKey
                                        ? hover.time
                                        : null
                                )}
                            </span>
                        );
                    })}
            </div>
            <div
                className="chart-region__canvas"
                ref={container}
                data-testid="price-chart"
                data-chart-type={chartType}
                onMouseLeave={() => {
                    onSelection?.(null);
                    setHover({ context: contextKey, incarnation: incarnationKey, time: null });
                }}
            />
        </div>
    );
}
