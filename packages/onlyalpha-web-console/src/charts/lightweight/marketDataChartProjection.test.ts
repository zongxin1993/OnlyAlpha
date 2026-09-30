import { marketDataBars } from "../../test/marketDataClient";
import {
    admitMarketDataChartBars,
    projectMarketDataBar,
    toCandlestick,
    toCloseLine
} from "./marketDataChartProjection";
function fixtureBar() {
    const bar = marketDataBars().bars[0];
    if (bar === undefined) throw new Error("fixture requires a Bar");
    return bar;
}

it("rejects different exact identities that collapse to one renderer time", () => {
    const first = fixtureBar();
    const second = { ...first, bar_start_ns: (BigInt(first.bar_start_ns) + 1n).toString() };
    expect(() => {
        admitMarketDataChartBars([first, second]);
    }).toThrow("MARKET_DATA_CHART_PROJECTION_INVALID");
    expect(() => {
        admitMarketDataChartBars([first, { ...first }]);
    }).not.toThrow();
});

it("retains exact Product identity and values outside numeric renderer projections", () => {
    const source = {
        ...fixtureBar(),
        bar_start_ns: "1767225600000000123",
        open: "100.000000000000000001",
        volume: "2.000000000000000001"
    };
    const bar = projectMarketDataBar(source);
    expect(bar).toMatchObject({
        barStartNs: source.bar_start_ns,
        barEndNs: source.bar_end_ns,
        open: source.open,
        high: source.high,
        low: source.low,
        close: source.close,
        volume: source.volume,
        closed: true
    });
    expect(toCandlestick(bar)).toEqual({
        time: 1767225600,
        open: 100,
        high: 102,
        low: 99,
        close: 101
    });
    expect(toCloseLine(bar)).toEqual({ time: 1767225600, value: 101 });
    expect(bar.numeric.volume).toBe(2);
    expect(projectMarketDataBar({ ...source, closed: false }).closed).toBe(false);
});

it.each(["", " ", "NaN", "Infinity", "-Infinity", "1e999"])(
    "rejects invalid renderer numbers: %s",
    (value) => {
        for (const field of ["open", "high", "low", "close", "volume"] as const) {
            expect(() => projectMarketDataBar({ ...fixtureBar(), [field]: value })).toThrow(
                "MARKET_DATA_CHART_PROJECTION_INVALID"
            );
        }
    }
);

it.each([
    { bar_start_ns: "9007199254740992000000000", bar_end_ns: "9007199254740993000000000" },
    { bar_start_ns: "8640000000001000000000", bar_end_ns: "8640000000002000000000" },
    { bar_start_ns: "2", bar_end_ns: "1" },
    { bar_start_ns: "1", bar_end_ns: "1" },
    { bar_start_ns: "bad", bar_end_ns: "2" }
])("rejects unsafe or invalid timestamp bounds: %j", (bounds) => {
    expect(() => projectMarketDataBar({ ...fixtureBar(), ...bounds })).toThrow(
        "MARKET_DATA_CHART_PROJECTION_INVALID"
    );
});
