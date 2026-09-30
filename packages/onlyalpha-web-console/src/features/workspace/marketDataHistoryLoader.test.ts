import type { MarketDataBar, MarketDataBarSemantic } from "../../api/marketData/model";
import type { MarketDataApiClient } from "../../api/marketData/client";
import { marketDataBarSemantic } from "../../api/marketData/model";
import {
    FIXTURE_REFERENCE,
    marketDataAcquisition,
    marketDataBars,
    marketDataClient
} from "../../test/marketDataClient";
import { OnlyMarketDataBarLedger } from "./marketDataBarLedger";
import {
    OLDER_HISTORY_TARGET_BAR_COUNT,
    OnlyMarketDataHistoryLoader,
    onlyMarketDataChartContextKey
} from "./marketDataHistoryLoader";

const currentBars = marketDataBars().bars;
const firstCurrentBar: MarketDataBar =
    currentBars[0] ??
    (() => {
        throw new Error("Market Data fixture requires a first Bar");
    })();
const earlierBar: MarketDataBar = {
    ...firstCurrentBar,
    bar_start_ns: "1767225540000000000",
    bar_end_ns: "1767225600000000000"
};

function completePage(bars: readonly MarketDataBar[] = [earlierBar]) {
    return marketDataBars({
        requested_before_ns: firstCurrentBar.bar_start_ns,
        requested_bar_count: OLDER_HISTORY_TARGET_BAR_COUNT,
        resolved_start_ns: earlierBar.bar_start_ns,
        resolved_end_ns: firstCurrentBar.bar_start_ns,
        bars: [...bars],
        coverage: {
            ...marketDataBars().coverage,
            expected_bar_count: bars.length,
            actual_bar_count: bars.length
        }
    });
}

function loaderHarness(overrides: {
    readonly queryBars?: MarketDataApiClient["queryBars"];
    readonly current?: () => boolean;
}) {
    const ledger = new OnlyMarketDataBarLedger("context");
    ledger.mergeHistory(currentBars);
    const queryBars = overrides.queryBars ?? vi.fn(() => Promise.resolve(completePage()));
    const client = marketDataClient({ queryBars });
    const loader = new OnlyMarketDataHistoryLoader({
        client,
        reference: FIXTURE_REFERENCE,
        expectedSourceId: "test.market_data.live",
        contextKey: "context",
        isCurrent: overrides.current ?? (() => true),
        merge: (bars) => ledger.mergeHistory(bars)
    });
    return { client, ledger, loader, queryBars };
}

const load = (loader: OnlyMarketDataHistoryLoader, semantic = marketDataBarSemantic(1)) =>
    loader.loadOlder({
        instrumentId: "BTCUSDT.TEST",
        barSemantic: semantic,
        beforeNs: firstCurrentBar.bar_start_ns
    });

describe("older Market Data history", () => {
    it.each(["first query", "frozen re-query"])(
        "rejects a mismatched %s without merging or registering the page",
        async (path) => {
            const wrong = { ...completePage(), instrument_id: "ETHUSDT.TEST" };
            const incomplete = {
                ...completePage([]),
                history_projection_fingerprint: null,
                resume_after_sequence: null,
                resume_plan_fingerprint: null,
                coverage: { ...completePage().coverage, status: "INCOMPLETE" as const }
            };
            const queryBars = vi.fn();
            if (path === "frozen re-query") queryBars.mockResolvedValueOnce(incomplete);
            queryBars.mockResolvedValueOnce(wrong).mockResolvedValueOnce(completePage());
            const { ledger, loader } = loaderHarness({ queryBars });
            const before = ledger.snapshot();
            await expect(load(loader)).rejects.toMatchObject({
                code: "MARKET_DATA_HISTORY_RESPONSE_MISMATCH"
            });
            expect(ledger.snapshot()).toEqual(before);
            expect(await load(loader)).toMatchObject({ status: "loaded", prependedCount: 1 });
            expect(queryBars).toHaveBeenCalledTimes(path === "first query" ? 2 : 3);
        }
    );
    it("changes the presentation context key for every exact identity field", () => {
        const semantic = marketDataBarSemantic(1);
        const base = onlyMarketDataChartContextKey(FIXTURE_REFERENCE, "BTCUSDT.TEST", semantic);
        const variants: readonly [typeof FIXTURE_REFERENCE, string, MarketDataBarSemantic][] = [
            [{ ...FIXTURE_REFERENCE, integration_id: "other" }, "BTCUSDT.TEST", semantic],
            [
                { ...FIXTURE_REFERENCE, integration_revision_fingerprint: "b".repeat(64) },
                "BTCUSDT.TEST",
                semantic
            ],
            [FIXTURE_REFERENCE, "ETHUSDT.TEST", semantic],
            [FIXTURE_REFERENCE, "BTCUSDT.TEST", marketDataBarSemantic(7)]
        ];

        for (const [reference, instrumentId, barSemantic] of variants) {
            expect(onlyMarketDataChartContextKey(reference, instrumentId, barSemantic)).not.toBe(
                base
            );
        }
    });

    it("queries BEFORE_TIME at the ledger's earliest exact nanoseconds and merges a COMPLETE page", async () => {
        const { ledger, loader, queryBars } = loaderHarness({});

        await load(loader);

        expect(queryBars).toHaveBeenCalledWith(
            FIXTURE_REFERENCE,
            expect.objectContaining({
                anchor_kind: "BEFORE_TIME",
                before_ns: firstCurrentBar.bar_start_ns,
                target_bar_count: OLDER_HISTORY_TARGET_BAR_COUNT
            })
        );
        expect(ledger.snapshot().earliestStartNs).toBe(earlierBar.bar_start_ns);
    });

    it("uses only server-planned ranges then repeats the frozen page query", async () => {
        const frozenIncomplete = {
            ...completePage([]),
            history_projection_fingerprint: null,
            resume_after_sequence: null,
            resume_plan_fingerprint: null,
            coverage: {
                ...marketDataBars().coverage,
                status: "INCOMPLETE",
                planned_acquisition_ranges: [{ start_ns: "10", end_ns: "20" }]
            }
        };
        const queryBars = vi
            .fn()
            .mockResolvedValueOnce(frozenIncomplete)
            .mockResolvedValueOnce(completePage());
        const { client, loader } = loaderHarness({ queryBars });
        const create = vi
            .spyOn(client, "createAcquisition")
            .mockResolvedValue(marketDataAcquisition({ status: "COMPLETE" }));

        await load(loader);

        expect(create).toHaveBeenCalledWith(FIXTURE_REFERENCE, {
            instrument_id: "BTCUSDT.TEST",
            start_ns: "10",
            end_ns: "20",
            bar_semantic: marketDataBarSemantic(1)
        });
        expect(queryBars).toHaveBeenCalledTimes(2);
        expect(queryBars.mock.calls[1]).toEqual(queryBars.mock.calls[0]);
    });

    it("deduplicates concurrent and completed requests for the same frozen page", async () => {
        let resolve!: (page: ReturnType<typeof completePage>) => void;
        const queryBars = vi.fn(
            () =>
                new Promise<ReturnType<typeof completePage>>((done) => {
                    resolve = done;
                })
        );
        const { loader } = loaderHarness({ queryBars });

        const first = load(loader);
        const repeated = load(loader);
        resolve(completePage());
        await Promise.all([first, repeated]);
        await load(loader);

        expect(queryBars).toHaveBeenCalledTimes(1);
    });

    it("marks history exhausted and blocks further pages when COMPLETE adds no earlier bar", async () => {
        const queryBars = vi.fn(() => Promise.resolve(completePage()));
        const { ledger, loader } = loaderHarness({ queryBars });
        ledger.mergeHistory([earlierBar]);

        expect(await load(loader)).toMatchObject({ status: "exhausted" });
        await loader.loadOlder({
            instrumentId: "BTCUSDT.TEST",
            barSemantic: marketDataBarSemantic(1),
            beforeNs: "1"
        });

        expect(queryBars).toHaveBeenCalledTimes(1);
    });

    it("drops a completed page when its context generation became stale", async () => {
        let resolve!: (page: ReturnType<typeof completePage>) => void;
        let current = true;
        const queryBars = vi.fn(
            () =>
                new Promise<ReturnType<typeof completePage>>((done) => {
                    resolve = done;
                })
        );
        const { ledger, loader } = loaderHarness({ queryBars, current: () => current });

        const pending = load(loader);
        current = false;
        resolve(completePage());

        expect(await pending).toMatchObject({ status: "stale" });
        expect(ledger.snapshot().earliestStartNs).toBe(firstCurrentBar.bar_start_ns);
    });
});
