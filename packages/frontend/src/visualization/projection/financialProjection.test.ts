import { parseDecimalText } from "../../domain/research/decimal";
import type {
    ResearchMarketPoint,
    ResearchSignalPoint,
    ResearchVariablePoint
} from "../../domain/research/model";
import { parseUnixNanoseconds } from "../../domain/research/time";
import {
    projectFiniteDecimal,
    projectMarketEvidence,
    projectSignalEvidence,
    projectVariableEvidence
} from "./financialProjection";

const market = (timestamp: string): ResearchMarketPoint => ({
    kind: "MARKET",
    instrumentId: "510300",
    tsEventNs: parseUnixNanoseconds(timestamp),
    open: parseDecimalText("10.0"),
    high: parseDecimalText("12.0"),
    low: parseDecimalText("9.5"),
    close: parseDecimalText("11.0"),
    volume: parseDecimalText("1000")
});

it("projects exact OHLC only at the renderer boundary", () => {
    const result = projectMarketEvidence([market("1000000000"), market("2000000000")]);
    expect(result).toEqual({
        ok: true,
        value: {
            candles: [
                { time: 1, open: 10, high: 12, low: 9.5, close: 11 },
                { time: 2, open: 10, high: 12, low: 9.5, close: 11 }
            ],
            volume: [
                { time: 1, value: 1000, direction: "UP" },
                { time: 2, value: 1000, direction: "UP" }
            ]
        }
    });
    expect(projectFiniteDecimal("1e9999").ok).toBe(false);
    expect(projectMarketEvidence([market("1000000001"), market("1000000002")]).ok).toBe(false);
});

it("projects only authoritative true Signal evidence to markers and preserves null outside it", () => {
    const signal = (timestamp: string, value: boolean | null): ResearchSignalPoint => ({
        kind: "SIGNAL",
        instrumentId: "510300",
        tsEventNs: parseUnixNanoseconds(timestamp),
        value
    });
    const projected = projectSignalEvidence("ENTRY_SIGNAL", [
        signal("1000000000", null),
        signal("2000000000", false),
        signal("3000000000", true)
    ]);
    expect(projected.ok && projected.value).toEqual([
        {
            time: 3,
            role: "ENTRY_SIGNAL",
            position: "belowBar",
            shape: "arrowUp"
        }
    ]);
    const exit = projectSignalEvidence("EXIT_SIGNAL", [signal("4000000000", true)]);
    expect(exit.ok && exit.value[0]).toMatchObject({ position: "aboveBar", shape: "arrowDown" });
    const eligibility = projectSignalEvidence("ELIGIBILITY", [signal("5000000000", true)]);
    expect(eligibility.ok && eligibility.value).toEqual([]);
});

it("rejects non-numeric Variable evidence from numeric chart projection", () => {
    const point: ResearchVariablePoint = {
        kind: "VARIABLE",
        instrumentId: "510300",
        tsEventNs: parseUnixNanoseconds("1000000000"),
        valueKind: "BOOLEAN",
        decimalValue: null,
        integerValue: null,
        booleanValue: true,
        stringValue: null
    };
    expect(projectVariableEvidence([point])).toMatchObject({ ok: false });
});
