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

export type OverlayKind = "indicator" | "factor";

export interface OverlaySpec {
    readonly id: string;
    readonly label: string;
    readonly kind: OverlayKind;
}

export const OVERLAY_COLORS = ["#1f5f8b", "#7a5c12", "#24683f", "#2f79a8"] as const;

function seededSeries(bars: readonly CandlestickData<UTCTimestamp>[], seed: number) {
    let state = seed;
    const smooth: number[] = [];
    let level = 50;
    for (const bar of bars) {
        state = (state * 1_103_515_245 + 12_345) % 2_147_483_648;
        const drift = (state / 2_147_483_648 - 0.5) * 6;
        const stretch = (bar.close - bar.open) * 0.4;
        level = Math.max(0, Math.min(100, level + drift + stretch));
        smooth.push(level);
    }
    const window = 5;
    return bars.map((bar, index) => {
        const from = Math.max(0, index - window + 1);
        const slice = smooth.slice(from, index + 1);
        return {
            time: bar.time,
            value: slice.reduce((total, item) => total + item, 0) / slice.length
        };
    });
}

/**
 * Placeholder overlay values for the W0/W1 shell. Real indicator and factor values belong to
 * `onlyalpha.calculations` and arrive through the Product API; nothing here is canonical.
 */
export function buildPlaceholderOverlay(
    bars: readonly CandlestickData<UTCTimestamp>[],
    overlay: OverlaySpec
) {
    if (overlay.kind === "factor") {
        let seed = 7;
        for (const character of overlay.id)
            seed = (seed * 31 + character.charCodeAt(0)) % 2_147_483_647;
        return seededSeries(bars, seed);
    }
    const window = Number.parseInt(overlay.id.replace(/\D/g, ""), 10) || 20;
    return bars
        .map((bar, index) => {
            if (index + 1 < window) return null;
            const slice = bars.slice(index + 1 - window, index + 1);
            return {
                time: bar.time,
                value: slice.reduce((total, item) => total + item.close, 0) / window
            };
        })
        .filter((point) => point !== null);
}

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
