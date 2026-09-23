import type { CandlestickData, UTCTimestamp } from "lightweight-charts";

export const TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1H": 3_600,
    "1D": 86_400,
    "1W": 604_800
} as const;

export type Timeframe = keyof typeof TIMEFRAME_SECONDS;

/**
 * Deterministic placeholder bars for the W0 shell. Every call with the same timeframe returns the
 * same series, so renders, screenshots and tests agree. W1 replaces this with formal historical
 * bars read through the Product API; until then the chart claims no market truth.
 */
export function buildPlaceholderBars(
    timeframe: Timeframe,
    count = 180
): CandlestickData<UTCTimestamp>[] {
    let seed = 20_260_923;
    function nextUnit(): number {
        seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648;
        return seed / 2_147_483_648;
    }
    const step = TIMEFRAME_SECONDS[timeframe];
    const start = Date.UTC(2026, 0, 5) / 1000;
    const bars: CandlestickData<UTCTimestamp>[] = [];
    let close = 1_472;
    for (let index = 0; index < count; index += 1) {
        const open = close;
        const moved = Math.max(1, open + (nextUnit() - 0.5) * 22);
        const high = Math.max(open, moved) + nextUnit() * 7;
        const low = Math.min(open, moved) - nextUnit() * 7;
        bars.push({
            time: (start + index * step) as UTCTimestamp,
            open,
            high,
            low,
            close: moved
        });
        close = moved;
    }
    return bars;
}
