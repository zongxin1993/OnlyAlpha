import type { MarketDataBar } from "../../api/marketData/model";
import { MarketDataBarLedgerConflictError, OnlyMarketDataBarLedger } from "./marketDataBarLedger";

function bar(start: string, overrides: Partial<MarketDataBar> = {}): MarketDataBar {
    return {
        bar_start_ns: start,
        bar_end_ns: (BigInt(start) + 60n).toString(),
        open: "100",
        high: "102",
        low: "99",
        close: "101",
        volume: "2",
        closed: true,
        ...overrides
    };
}

describe("MarketDataBarLedger", () => {
    it("retains one immutable closed snapshot across preview-only updates", () => {
        const ledger = new OnlyMarketDataBarLedger("context");
        ledger.mergeHistory([bar("100")]);
        const closed = ledger.snapshot().closedBars;
        for (let close = 100; close < 110; close++) {
            ledger.applyPreview(bar("160", { closed: false, close: String(close) }));
            expect(ledger.snapshot().closedBars).toBe(closed);
        }
        expect(Object.isFrozen(closed)).toBe(true);
        expect(Object.isFrozen(closed[0])).toBe(true);
        ledger.mergeHistory([bar("100")]);
        expect(ledger.snapshot().closedBars).toBe(closed);
        ledger.applyClosed(bar("160"));
        expect(ledger.snapshot().closedBars).not.toBe(closed);
        expect(closed).toEqual([bar("100")]);
        expect(ledger.snapshot().closedBars).toEqual([bar("100"), bar("160")]);
    });
    it("replays an identical preview without changing its version or value", () => {
        const ledger = new OnlyMarketDataBarLedger("context");
        const preview = bar("100", { closed: false });
        ledger.applyPreview(preview);
        const before = ledger.snapshot();
        expect(ledger.applyPreview({ ...preview }).changed).toBe(false);
        expect(ledger.snapshot()).toEqual(before);
    });
    it("orders unsorted closed history by exact nanoseconds", () => {
        const ledger = new OnlyMarketDataBarLedger("context");

        ledger.mergeHistory([
            bar("9007199254740993"),
            bar("9007199254740991"),
            bar("9007199254740992")
        ]);

        expect(ledger.snapshot().closedBars.map((item) => item.bar_start_ns)).toEqual([
            "9007199254740991",
            "9007199254740992",
            "9007199254740993"
        ]);
    });

    it("treats an exact duplicate as idempotent", () => {
        const ledger = new OnlyMarketDataBarLedger("context");
        const exact = bar("100");

        expect(ledger.mergeHistory([exact]).changed).toBe(true);
        expect(ledger.mergeHistory([{ ...exact }])).toMatchObject({
            changed: false,
            appendedCount: 0,
            prependedCount: 0
        });
        expect(ledger.snapshot().closedBars).toEqual([exact]);
    });

    it.each(["bar_end_ns", "open", "high", "low", "close", "volume", "closed"] as const)(
        "fails atomically when a duplicate start has conflicting %s",
        (field) => {
            const ledger = new OnlyMarketDataBarLedger("context");
            ledger.mergeHistory([bar("100")]);
            const conflicting = bar("100", {
                [field]: field === "closed" ? false : field === "bar_end_ns" ? "999" : "changed"
            });

            expect(() => ledger.mergeHistory([bar("40"), conflicting])).toThrow(
                MarketDataBarLedgerConflictError
            );
            expect(ledger.snapshot().closedBars).toEqual([bar("100")]);
        }
    );

    it("replaces preview at the same or newer start and ignores an older preview", () => {
        const ledger = new OnlyMarketDataBarLedger("context");
        const first = bar("100", { closed: false, close: "101" });
        const replacement = bar("100", { closed: false, close: "102" });
        const newer = bar("160", { closed: false, close: "103" });

        expect(ledger.applyPreview(first).changed).toBe(true);
        expect(ledger.applyPreview(replacement).changed).toBe(true);
        expect(ledger.applyPreview(bar("40", { closed: false })).changed).toBe(false);
        expect(ledger.applyPreview(newer).changed).toBe(true);
        expect(ledger.snapshot().preview).toEqual(newer);
    });

    it("ignores previews at or before the latest closed bar", () => {
        const ledger = new OnlyMarketDataBarLedger("context");
        ledger.mergeHistory([bar("100")]);

        expect(ledger.applyPreview(bar("100", { closed: false })).changed).toBe(false);
        expect(ledger.applyPreview(bar("40", { closed: false })).changed).toBe(false);
        expect(ledger.snapshot().preview).toBeNull();
    });

    it("lets a closed bar supersede preview at or before its start", () => {
        const ledger = new OnlyMarketDataBarLedger("context");
        ledger.applyPreview(bar("100", { closed: false }));

        ledger.applyClosed(bar("100"));

        expect(ledger.snapshot()).toMatchObject({ closedBars: [bar("100")], preview: null });
    });

    it("accepts a reconnect replay of the exact closed bar without mutation", () => {
        const exact = bar("100");
        const ledger = new OnlyMarketDataBarLedger("context");
        ledger.mergeHistory([exact]);
        const before = ledger.snapshot();

        expect(ledger.applyClosed({ ...exact }).changed).toBe(false);
        expect(ledger.snapshot()).toEqual(before);
    });
});

it("retains at most 4000 closed bars around the requested window and still rejects conflicts atomically", () => {
    const bar = (index: number) => ({
        bar_start_ns: (BigInt(index) * 60_000_000_000n).toString(),
        bar_end_ns: (BigInt(index + 1) * 60_000_000_000n).toString(),
        open: "10.00",
        high: "12.00",
        low: "9.00",
        close: "11.00",
        volume: "1.00",
        closed: true
    });
    const ledger = new OnlyMarketDataBarLedger("bounded");
    ledger.mergeHistory(Array.from({ length: 4100 }, (_, index) => bar(index)));
    expect(ledger.snapshot().closedBars).toHaveLength(4000);
    expect(ledger.snapshot().earliestStartNs).toBe(bar(100).bar_start_ns);
    ledger.mergeHistory([bar(0)]);
    expect(ledger.snapshot().closedBars).toHaveLength(4000);
    expect(ledger.snapshot().earliestStartNs).toBe("0");
    const previous = ledger.snapshot();
    expect(() => ledger.mergeHistory([bar(1), { ...bar(100), close: "10.50" }])).toThrow(
        MarketDataBarLedgerConflictError
    );
    expect(ledger.snapshot()).toEqual(previous);
    ledger.applyClosed(bar(4100));
    expect(ledger.snapshot().closedBars).toHaveLength(4000);
    expect(ledger.snapshot().latestClosedStartNs).toBe(bar(4100).bar_start_ns);
});

it.each([1, 7])(
    "preserves the latest 2000 closed %im bars while browsing beyond the retention limit",
    (minutes) => {
        const stride = BigInt(minutes) * 60_000_000_000n;
        const row = (index: number) =>
            bar((BigInt(index) * stride).toString(), {
                bar_end_ns: (BigInt(index + 1) * stride).toString()
            });
        for (const olderStart of [0, 7600]) {
            const ledger = new OnlyMarketDataBarLedger("current-and-history");
            const current = Array.from({ length: 2000 }, (_, index) => row(10000 + index));
            ledger.mergeHistory(current);
            ledger.mergeHistory(
                Array.from({ length: 2400 }, (_, index) => row(olderStart + index)),
                (BigInt(olderStart + 2400) * stride).toString()
            );
            const snapshot = ledger.snapshot();
            expect(snapshot.closedBars).toHaveLength(4000);
            expect(snapshot.closedBars.slice(-2000)).toEqual(current);
            expect(snapshot.earliestStartNs).toBe((BigInt(olderStart + 400) * stride).toString());
        }
    }
);
