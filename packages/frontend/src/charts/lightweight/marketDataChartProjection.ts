import type { CandlestickData, LineData, UTCTimestamp } from "lightweight-charts";
import type { MarketDataBar } from "../../api/marketData/model";

export type FinancialChartType = "CANDLESTICK" | "LINE";

export interface MarketDataChartSelection {
    readonly contextKey: string;
    readonly barStartNs: string;
}

export interface MarketDataChartBarProjection {
    readonly time: UTCTimestamp;
    readonly barStartNs: string;
    readonly barEndNs: string;
    readonly open: string;
    readonly high: string;
    readonly low: string;
    readonly close: string;
    readonly volume: string;
    readonly closed: boolean;
    readonly numeric: {
        readonly open: number;
        readonly high: number;
        readonly low: number;
        readonly close: number;
        readonly volume: number;
    };
}

export class MarketDataChartProjectionError extends Error {
    readonly code = "MARKET_DATA_CHART_PROJECTION_INVALID";
    constructor(detail: string) {
        super(`MARKET_DATA_CHART_PROJECTION_INVALID: ${detail}`);
        this.name = "MarketDataChartProjectionError";
    }
}

/** Validate before mutating the Ledger; distinct identities must not alias in the renderer. */
export function admitMarketDataChartBars(bars: readonly MarketDataBar[]): void {
    const identityByTime = new Map<number, string>();
    for (const bar of bars) {
        const projection = projectMarketDataBar(bar);
        const identity = identityByTime.get(projection.time);
        if (identity !== undefined && identity !== projection.barStartNs)
            throw new MarketDataChartProjectionError("Distinct Bar identities share renderer time");
        identityByTime.set(projection.time, projection.barStartNs);
    }
}

export function projectMarketDataBar(bar: MarketDataBar): MarketDataChartBarProjection {
    if (
        !/^(?:0|[1-9][0-9]*)$/.test(bar.bar_start_ns) ||
        !/^(?:0|[1-9][0-9]*)$/.test(bar.bar_end_ns)
    )
        throw new MarketDataChartProjectionError("Invalid nanosecond bounds");
    const start = BigInt(bar.bar_start_ns);
    const end = BigInt(bar.bar_end_ns);
    const time = Number(start / 1_000_000_000n);
    const endTime = Number(end / 1_000_000_000n);
    if (
        start >= end ||
        !Number.isSafeInteger(time) ||
        !Number.isSafeInteger(endTime) ||
        !Number.isFinite(new Date(time * 1000).getTime()) ||
        !Number.isFinite(new Date(endTime * 1000).getTime())
    )
        throw new MarketDataChartProjectionError("Unsafe timestamp or unordered bounds");
    const number = (value: string): number => {
        const result = Number(value);
        if (value.trim() === "" || !Number.isFinite(result))
            throw new MarketDataChartProjectionError("Empty or non-finite numeric value");
        return result;
    };
    return {
        time: time as UTCTimestamp,
        barStartNs: bar.bar_start_ns,
        barEndNs: bar.bar_end_ns,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        volume: bar.volume,
        closed: bar.closed,
        numeric: {
            open: number(bar.open),
            high: number(bar.high),
            low: number(bar.low),
            close: number(bar.close),
            volume: number(bar.volume)
        }
    };
}

export const toCandlestick = (
    bar: MarketDataChartBarProjection
): CandlestickData<UTCTimestamp> => ({
    time: bar.time,
    open: bar.numeric.open,
    high: bar.numeric.high,
    low: bar.numeric.low,
    close: bar.numeric.close
});
export const toCloseLine = (bar: MarketDataChartBarProjection): LineData<UTCTimestamp> => ({
    time: bar.time,
    value: bar.numeric.close
});
