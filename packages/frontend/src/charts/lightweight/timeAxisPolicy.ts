import { fixedDurationMinutes, type MarketDataBarSemantic } from "../../api/marketData/model";

export function deriveTimeAxisPolicy(spec: MarketDataBarSemantic, width: number) {
    return {
        timeVisible: fixedDurationMinutes(spec) < 1_440,
        secondsVisible: false,
        visibleBars: Math.max(30, Math.min(240, Math.floor(width / 8)))
    };
}
