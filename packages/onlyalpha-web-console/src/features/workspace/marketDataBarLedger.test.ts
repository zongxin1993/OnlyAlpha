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
