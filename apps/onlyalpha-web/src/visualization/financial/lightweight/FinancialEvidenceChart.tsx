import {
    CandlestickSeries,
    ColorType,
    createChart,
    createSeriesMarkers,
    HistogramSeries,
    LineSeries,
    type CandlestickData,
    type HistogramData,
    type LineData,
    type SeriesMarker,
    type UTCTimestamp,
    type WhitespaceData
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type {
    FinancialCandle,
    FinancialLinePoint,
    FinancialSignalMarker,
    FinancialVolume
} from "../../model/financial";

export function FinancialEvidenceChart({
    candles,
    volume,
    variable,
    markers
}: {
    readonly candles: readonly FinancialCandle[];
    readonly volume: readonly FinancialVolume[];
    readonly variable: readonly FinancialLinePoint[];
    readonly markers: readonly FinancialSignalMarker[];
}) {
    const container = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const element = container.current;
        if (element === null) return;
        const chart = createChart(element, {
            autoSize: true,
            height: 480,
            layout: {
                background: { type: ColorType.Solid, color: "#091524" },
                textColor: "#dbeafe"
            },
            grid: { vertLines: { color: "#243047" }, horzLines: { color: "#243047" } }
        });
        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: "#34d399",
            downColor: "#fb7185",
            borderVisible: false,
            wickUpColor: "#34d399",
            wickDownColor: "#fb7185"
        });
        candleSeries.setData(
            candles.map((point): CandlestickData => ({
                ...point,
                time: point.time.valueOf() as UTCTimestamp
            }))
        );
        const volumeSeries = chart.addSeries(HistogramSeries, {
            priceScaleId: "volume",
            priceFormat: { type: "volume" }
        });
        volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
        volumeSeries.setData(
            volume.map((point): HistogramData => ({
                time: point.time.valueOf() as UTCTimestamp,
                value: point.value,
                color: point.direction === "UP" ? "#34d39980" : "#fb718580"
            }))
        );
        if (variable.length > 0) {
            const line = chart.addSeries(LineSeries, { color: "#67e8f9", lineWidth: 2 });
            line.setData(
                variable.map((point): LineData | WhitespaceData =>
                    point.value === undefined
                        ? { time: point.time.valueOf() as UTCTimestamp }
                        : {
                              time: point.time.valueOf() as UTCTimestamp,
                              value: point.value
                          }
                )
            );
        }
        createSeriesMarkers(
            candleSeries,
            markers.map((marker): SeriesMarker<UTCTimestamp> => ({
                time: marker.time.valueOf() as UTCTimestamp,
                position: marker.position,
                shape: marker.shape,
                color: marker.position === "belowBar" ? "#34d399" : "#fb7185",
                text: marker.role
            }))
        );
        chart.timeScale().fitContent();
        return () => {
            chart.remove();
        };
    }, [candles, markers, variable, volume]);
    return (
        <section aria-label="Financial evidence chart">
            <div className="financial-chart" ref={container} data-testid="financial-chart" />
            <p className="attribution">
                Charting by <a href="https://www.tradingview.com/">TradingView</a>
            </p>
        </section>
    );
}
