import { fixedDurationMinutes, type MarketDataBarSemantic } from "../../api/marketData/model";

export function deriveTimeAxisPolicy(spec: MarketDataBarSemantic, width: number) {
    return {
        timeVisible: spec.formation.kind === "FIXED_DURATION" && fixedDurationMinutes(spec) < 1_440,
        secondsVisible: false,
        visibleBars: Math.max(30, Math.min(240, Math.floor(width / 8)))
    };
}
