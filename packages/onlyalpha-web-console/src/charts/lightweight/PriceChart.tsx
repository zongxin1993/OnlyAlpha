import {
    CandlestickSeries,
    ColorType,
    LineSeries,
    HistogramSeries,
    createChart
} from "lightweight-charts";
import type {
    CandlestickData,
    ISeriesApi,
    LogicalRange,
    MouseEventParams,
    UTCTimestamp
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import {
    studyDescriptor,
    studyDisplayLabel,
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
    type FinancialChartType,
    type MarketDataChartBarProjection,
    type MarketDataChartSelection
} from "./marketDataChartProjection";
import {
    chartTimeFormatters,
    displayTimezoneKey,
    isDisplayTimezone,
    readDisplayTimezone
} from "./chartDisplayTime";
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
    const [display, setDisplay] = useState(readDisplayTimezone);
    const volumeColors = useRef({ up: "#c8332a", down: "#2f7d47" });
    const container = useRef<HTMLDivElement>(null);
    const priceSeries = useRef<ISeriesApi<"Candlestick" | "Line"> | null>(null);
    const volumeSeries = useRef<ISeriesApi<"Histogram"> | null>(null);
    const studyRenderer = useRef<StudySeriesRenderer | null>(null);
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
            entries.flatMap((instance) =>
                instance.configuration.outputNames
                    .filter((name) => instance.presentation.seriesStyles?.[name]?.visible !== false)
                    .map((outputName) => {
                        const matches = studyEvidence.filter(
                            (evidence) =>
                                isStudySeriesEvidence(evidence) &&
                                evidence.instanceId === instance.instanceId &&
                                evidence.outputName === outputName
                        );
                        return [
                            JSON.stringify([instance.instanceId, outputName]),
                            duplicateInstances ||
                            matches.length > 1 ||
                            malformedEvidence ||
                            !validPresentation(instance.presentation)
                                ? {
                                      status: "INVALID" as const,
                                      detail: "重复身份 / 非法展示证据或样式"
                                  }
                                : projectStudySeries(instance, incarnationKey, timeline, matches[0])
                        ] as const;
                    })
            )
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
    const rendererBars = useRef<readonly RenderBar[]>([]);
    const previousBars = useRef<readonly RenderBar[]>([]);
    const acceptedPreview = useRef<MarketDataChartBarProjection | null>(null);
    const placingHistory = useRef(false);
    const nearLeftEdgeArmed = useRef(false);
    const nearLeftEdgeCallback = useRef(onNearLeftEdge);
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
            localization: { timeFormatter: chartTimeFormatters("UTC").timeFormatter },
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
                shiftVisibleRangeOnNewBar: false,
                allowShiftVisibleRangeOnWhitespaceReplacement: false,
                tickMarkFormatter: chartTimeFormatters("UTC").tickMarkFormatter
            }
        });
        chartRef.current = chart;
        volumeColors.current = { up: token("--up", "#c8332a"), down: token("--down", "#2f7d47") };
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
                priceLineVisible: false
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
            rendererBars.current = [];
            previousBars.current = [];
            acceptedPreview.current = null;
            initializedNonEmptyContext.current = false;
            axisTimes.current = [];
            nearLeftEdgeArmed.current = false;
            chart.remove();
        };
    }, []);

    useEffect(() => {
        const formatter = chartTimeFormatters(display.zone);
        chartRef.current?.applyOptions({
            localization: { timeFormatter: formatter.timeFormatter },
            timeScale: { tickMarkFormatter: formatter.tickMarkFormatter }
        });
    }, [display.zone]);

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
        const contextChanged = previousContextKey.current !== contextKey;
        if (contextChanged) {
            acceptedPreview.current = null;
            previousBars.current = [];
            initializedNonEmptyContext.current = false;
            nearLeftEdgeArmed.current = false;
        }
        const firstNonEmptyHistory = !initializedNonEmptyContext.current && bars.length > 0;
        placingHistory.current = true;
        const beforeAxis = axisTimes.current;
        const lastClosed = bars.at(-1);
        const previousPreview = acceptedPreview.current;
        if (liveBar === null) acceptedPreview.current = null;
        else if (
            (lastClosed === undefined || liveBar.time >= lastClosed.time) &&
            (previousPreview === null || liveBar.time >= previousPreview.time)
        )
            acceptedPreview.current = liveBar;
        const currentPreview = acceptedPreview.current;
        const preview =
            currentPreview !== null &&
            (lastClosed === undefined || currentPreview.time >= lastClosed.time)
                ? currentPreview
                : null;
        const displayed =
            preview === null
                ? bars
                : [
                      ...bars.filter((bar) => bar.time !== preview.time),
                      { ...toCandlestick(preview), barStartNs: preview.barStartNs }
                  ];
        const displayedProduct =
            preview === null
                ? productBars
                : [...productBars.filter((bar) => bar.time !== preview.time), preview];
        const priorBars = previousBars.current;
        const firstPrior = priorBars[0];
        const offset =
            firstPrior === undefined
                ? -1
                : bars.findIndex((bar) => barIdentity(bar) === barIdentity(firstPrior));
        const orderedPrior =
            offset >= 0 &&
            priorBars.every((bar, index) => {
                const next = bars[index + offset];
                return next !== undefined && barIdentity(next) === barIdentity(bar);
            });
        const nextExtra = [
            ...new Set(
                studies
                    .filter(
                        (instance) =>
                            instance.context.key === contextKey &&
                            instance.presentation.visible &&
                            validPresentation(instance.presentation)
                    )
                    .flatMap((instance) =>
                        instance.configuration.outputNames
                            .filter(
                                (name) =>
                                    instance.presentation.seriesStyles?.[name]?.visible !== false
                            )
                            .flatMap((outputName) => {
                                const view = views.get(
                                    JSON.stringify([instance.instanceId, outputName])
                                );
                                return view?.status === "PROJECTED" &&
                                    view.projection.segments.length > 0
                                    ? [...view.projection.pointsByTime.keys()]
                                    : [];
                            })
                    )
            )
        ];
        const nextAxis = [...new Set([...displayed.map((bar) => bar.time), ...nextExtra])].sort(
            (a, b) => a - b
        );
        axisTimes.current = nextAxis;
        rendererBars.current = displayed;
        priceSeries.current?.setData(
            displayed.map((bar) =>
                activeType.current === "LINE" ? { time: bar.time, value: bar.close } : bar
            )
        );
        volumeSeries.current?.setData(
            displayedProduct.map((bar) => ({
                time: bar.time,
                value: bar.numeric.volume,
                color:
                    bar.numeric.close >= bar.numeric.open
                        ? volumeColors.current.up
                        : volumeColors.current.down
            }))
        );
        if (container.current !== null) {
            container.current.dataset.volumePointCount = String(displayedProduct.length);
            container.current.dataset.volumeLatest = displayedProduct.at(-1)?.volume ?? "";
        }
        // Native logical-range writes are applied on the next paint. Sync every
        // series first, then issue one viewport write; a sibling effect would
        // read the old range and overwrite the pending live-bar advance.
        studyRenderer.current?.sync(
            studies.filter((instance) => instance.context.key === contextKey),
            views,
            selectedStudyId
        );
        if (container.current !== null) {
            container.current.dataset.studySeriesCount = String(
                studyRenderer.current?.seriesCount ?? 0
            );
            container.current.dataset.paneCount = String(chartRef.current?.panes().length ?? 0);
        }
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
        } else if (visibleRange !== null && !contextChanged && orderedPrior) {
            const shifted = rebaseChartRange(visibleRange, beforeAxis, nextAxis, offset === 0);
            if (shifted.from !== visibleRange.from || shifted.to !== visibleRange.to)
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
    }, [barSemantic, bars, contextKey, productBars, liveBar, studies, views, selectedStudyId]);

    return (
        <div className="price-chart-surface">
            <div className="study-hover" aria-label="指标悬浮信息">
                <span aria-label="成交量悬浮信息">
                    成交量{" "}
                    {hover.context === contextKey &&
                    hover.incarnation === incarnationKey &&
                    hover.time !== null
                        ? ((liveBar !== null &&
                          liveBar.time === hover.time &&
                          liveBar.time >= (productBars.at(-1)?.time ?? -Infinity)
                              ? liveBar
                              : productBars.find((bar) => bar.time === hover.time)
                          )?.volume ?? "此时间无对应结果")
                        : "请移动十字线查看精确点"}
                </span>
                {studies
                    .filter(
                        (instance) =>
                            instance.context.key === contextKey && instance.presentation.visible
                    )
                    .flatMap((instance) =>
                        instance.configuration.outputNames
                            .filter(
                                (name) =>
                                    instance.presentation.seriesStyles?.[name]?.visible !== false
                            )
                            .map((outputName) => {
                                const view = views.get(
                                    JSON.stringify([instance.instanceId, outputName])
                                );
                                if (view === undefined) return null;
                                const time =
                                    hover.context === contextKey &&
                                    hover.incarnation === incarnationKey
                                        ? hover.time
                                        : null;
                                const point =
                                    view.status === "PROJECTED" && time !== null
                                        ? view.projection.pointsByTime.get(time)
                                        : undefined;
                                const value =
                                    view.status !== "PROJECTED"
                                        ? view.detail
                                        : time === null
                                          ? "—"
                                          : point === undefined
                                            ? "此时间无对应结果"
                                            : `${point.value ?? "暂无数值"}${point.readiness === "PARTIAL" ? " · 部分可用" : point.readiness === "PRE_READY" ? " · 预热中" : ""}`;
                                return (
                                    <div
                                        key={JSON.stringify([instance.instanceId, outputName])}
                                        data-testid="study-hover"
                                        data-instance-id={instance.instanceId}
                                        data-selected={selectedStudyId === instance.instanceId}
                                    >
                                        <span>
                                            {studyDisplayLabel(instance)} · {outputName} · {value}
                                        </span>
                                        <details className="study-hover__details">
                                            <summary
                                                aria-label={`指标点详情 ${studyDescriptor(instance.selection).typeId.split(".").at(-1)?.toUpperCase() ?? studyDescriptor(instance.selection).typeId}`}
                                            >
                                                详情
                                            </summary>
                                            <span>
                                                {studyDescriptor(instance.selection).typeId} ·{" "}
                                                {outputName} ·{" "}
                                                {view.status === "PROJECTED"
                                                    ? view.projection.outputUnit === "PRICE"
                                                        ? "PRICE"
                                                        : `${view.projection.outputUnit ?? "单位未知"} · 独立纵轴`
                                                    : "无有效结果"}{" "}
                                                · {studyHover(view, time)}
                                            </span>
                                        </details>
                                    </div>
                                );
                            })
                    )}
            </div>
            <div
                className="chart-region__canvas"
                ref={container}
                data-testid="price-chart"
                data-chart-type={chartType}
                data-study-preview-count={
                    studyEvidence.filter(
                        (row) =>
                            isStudySeriesEvidence(row) &&
                            row.chartContextKey === contextKey &&
                            row.incarnationKey === incarnationKey &&
                            row.previewPoint !== undefined
                    ).length
                }
                onMouseLeave={() => {
                    onSelection?.(null);
                    setHover({ context: contextKey, incarnation: incarnationKey, time: null });
                }}
            />
            <div className="chart-display-controls">
                {display.notice !== "" && <span role="status">{display.notice}</span>}
                <label>
                    显示时区{" "}
                    <select
                        aria-label="显示时区"
                        value={display.zone}
                        onChange={(event) => {
                            const zone = event.target.value;
                            if (!isDisplayTimezone(zone)) return;
                            let notice = "";
                            try {
                                localStorage.setItem(displayTimezoneKey, zone);
                            } catch {
                                notice = "无法保存时区偏好；仅本次显示生效";
                            }
                            setDisplay({ zone, notice });
                        }}
                    >
                        <option value="UTC">UTC</option>
                        <option value="Asia/Shanghai">北京时间</option>
                        <option value="USER_LOCAL">本地时区</option>
                    </select>
                </label>
            </div>
        </div>
    );
}
