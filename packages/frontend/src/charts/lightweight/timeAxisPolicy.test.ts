import { marketDataBarSemantic } from "../../api/marketData/model";
import { deriveTimeAxisPolicy } from "./timeAxisPolicy";

it.each([7, 37, 120])("derives intraday viewport from width for arbitrary %im bars", (step) => {
    const spec = marketDataBarSemantic(step);
    const narrow = deriveTimeAxisPolicy(spec, 400);
    const wide = deriveTimeAxisPolicy(spec, 1_200);
    expect(narrow.timeVisible).toBe(true);
    expect(narrow.secondsVisible).toBe(false);
    expect(wide.visibleBars).toBeGreaterThan(narrow.visibleBars);
});

it.each([0, -1, 1.5])("rejects an invalid real minute step %s", (step) => {
    expect(() => marketDataBarSemantic(step)).toThrow();
});

it("keeps a 720-minute Bar semantic valid", () => {
    expect(marketDataBarSemantic(720).formation).toMatchObject({
        window_minutes: 720,
        stride_minutes: 720
    });
});
