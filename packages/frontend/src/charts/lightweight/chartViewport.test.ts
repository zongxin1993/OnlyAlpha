import type { LogicalRange } from "lightweight-charts";
import { rebaseChartRange } from "./chartViewport";

it("advances at the live edge only for a new timestamp; preview prices and Study changes do not scroll", () => {
    const before = [10, 20, 30];
    const range = { from: 0, to: 5 } as LogicalRange;
    expect(rebaseChartRange(range, before, [10, 20, 30, 40], true)).toEqual({ from: 1, to: 6 });
    expect(rebaseChartRange(range, before, before, true)).toEqual(range);
    expect(rebaseChartRange(range, before, [10, 20, 30, 40])).toEqual(range);
});
it("keeps a historical viewport and rebases prepended history without pulling it to the live edge", () => {
    expect(
        rebaseChartRange({ from: 0, to: 1 } as LogicalRange, [10, 20, 30], [10, 20, 30, 40], true)
    ).toEqual({ from: 0, to: 1 });
    expect(
        rebaseChartRange(
            { from: 0.25, to: 4.5 } as LogicalRange,
            [10, 20, 30],
            [0, 10, 20, 30],
            true
        )
    ).toEqual({ from: 1.25, to: 5.5 });
});
