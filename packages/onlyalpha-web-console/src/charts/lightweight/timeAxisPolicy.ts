import type { MarketDataBarSpecification } from "../../api/marketData/model";

export function deriveTimeAxisPolicy(spec: MarketDataBarSpecification, width: number) {
    return {
        timeVisible: spec.step < 1_440,
        secondsVisible: false,
        visibleBars: Math.max(30, Math.min(240, Math.floor(width / 8)))
    };
}
