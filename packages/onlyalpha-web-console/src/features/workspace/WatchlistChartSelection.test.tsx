import { readTemporaryMarketData } from "../../api/marketData/temporary";
import { temporaryWindowForQuery } from "../../test/temporaryMarketDataClient";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { MarketDataApiClient } from "../../api/marketData/client";
import { AppProviders } from "../../app/providers";
import { marketDataBarSemantic, marketDataSourceChoiceKey } from "../../api/marketData/model";
import {
    marketDataBarsForQuery,
    marketDataClient,
    marketDataInstrument,
    marketDataSource
} from "../../test/marketDataClient";
import { onlyMarketDataSourceReference, useMarketDataChart } from "./useMarketDataChart";
vi.mock("../../api/marketData/temporaryStream", () => ({
    openTemporaryMarketDataStream: () => () => undefined
}));
vi.mock("../../api/marketData/temporary", () => ({ readTemporaryMarketData: vi.fn() }));
beforeEach(() => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    vi.mocked(readTemporaryMarketData).mockImplementation((_c, reference, query) =>
        Promise.resolve(temporaryWindowForQuery(reference, query))
    );
});
afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllEnvs();
});
it("keeps the last A selection when a pending B lookup completes after an A no-op", async () => {
    let finishB: ((items: ReturnType<typeof marketDataInstrument>[]) => void) | undefined;
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_reference, query) =>
        Promise.resolve(marketDataBarsForQuery(query))
    );
    const createAcquisition = vi.fn<MarketDataApiClient["createAcquisition"]>();
    const client = marketDataClient({
        listInstruments: (_reference, _query, _signal, ids) =>
            ids?.[0] === "ETHUSDT.TEST"
                ? new Promise((resolve) => {
                      finishB = resolve;
                  })
                : Promise.resolve([marketDataInstrument()]),
        queryBars,
        createAcquisition
    });
    const wrapper = ({ children }: { readonly children: ReactNode }) => (
        <AppProviders marketDataClient={client}>{children}</AppProviders>
    );
    const { result } = renderHook(() => useMarketDataChart(), { wrapper });
    await waitFor(() => {
        expect(result.current.selectableSources).toHaveLength(1);
    });
    const source = onlyMarketDataSourceReference(marketDataSource());
    await act(() => result.current.selectWatchlistInstrument(source, "BTCUSDT.TEST"));
    const context = result.current.chartContextKey;
    let pending: Promise<void> | undefined;
    act(() => {
        pending = result.current.selectWatchlistInstrument(source, "ETHUSDT.TEST");
    });
    await act(() => result.current.selectWatchlistInstrument(source, "BTCUSDT.TEST"));
    await act(async () => {
        finishB?.([marketDataInstrument({ instrument_id: "ETHUSDT.TEST" })]);
        await pending;
    });
    expect(result.current.instrument?.instrument_id).toBe("BTCUSDT.TEST");
    expect(result.current.chartContextKey).toBe(context);
    expect(queryBars).not.toHaveBeenCalled();
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(1);
    expect(createAcquisition).not.toHaveBeenCalled();
});
it("switches exact Watchlist sources while retaining the period and fills temporary inputs without acquisition", async () => {
    const first = marketDataSource();
    const second = marketDataSource({
        integration_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        integration_revision_fingerprint: "b".repeat(64)
    });
    let secondReads = 0;
    vi.mocked(readTemporaryMarketData).mockImplementation((_c, reference, query) =>
        Promise.resolve().then(() => {
            const value = temporaryWindowForQuery(reference, query);
            if (reference.integration_id === second.integration_id && secondReads++ === 0) {
                const missing = value.bars.slice(0, 1000);
                value.bars = value.bars.slice(1000);
                value.coverage = {
                    status: "PARTIAL",
                    expected_bar_count: 2000,
                    actual_bar_count: 1000,
                    gaps: missing.map((bar) => ({
                        start_ns: bar.bar_start_ns,
                        end_ns: bar.bar_end_ns
                    }))
                };
            }
            return value;
        })
    );
    const createAcquisition = vi.fn<MarketDataApiClient["createAcquisition"]>();
    const client = marketDataClient({
        listSources: () => Promise.resolve([first, second]),
        listInstruments: (_reference, _query, _signal, ids) =>
            Promise.resolve([marketDataInstrument({ instrument_id: ids?.[0] ?? "BTCUSDT.TEST" })]),
        queryBars: vi.fn(() =>
            Promise.resolve().then(() => {
                throw new Error("persistent history is prohibited");
            })
        ),
        createAcquisition
    });
    const wrapper = ({ children }: { readonly children: ReactNode }) => (
        <AppProviders marketDataClient={client}>{children}</AppProviders>
    );
    const { result } = renderHook(() => useMarketDataChart(), { wrapper });
    await waitFor(() => {
        expect(result.current.selectableSources).toHaveLength(2);
    });
    await act(() =>
        result.current.selectWatchlistInstrument(
            onlyMarketDataSourceReference(first),
            "BTCUSDT.TEST"
        )
    );
    await act(() => result.current.selectBarDuration(7));
    await act(() =>
        result.current.selectWatchlistInstrument(
            onlyMarketDataSourceReference(second),
            "ETHUSDT.TEST"
        )
    );
    expect(result.current.sourceId).toBe(marketDataSourceChoiceKey(second));
    expect(result.current.instrument?.instrument_id).toBe("ETHUSDT.TEST");
    expect(result.current.barSemantic).toEqual(marketDataBarSemantic(7));
    expect(result.current.status).toBe("ready");
    expect(createAcquisition).not.toHaveBeenCalled();
    await act(() =>
        result.current.selectWatchlistInstrument(
            {
                ...onlyMarketDataSourceReference(second),
                integration_revision_fingerprint: "c".repeat(64)
            },
            "BTCUSDT.TEST"
        )
    );
    expect(result.current.instrument?.instrument_id).toBe("ETHUSDT.TEST");
    expect(result.current.message).toContain("不会自动换源");
});
it.each(["changed", "removed"])(
    "does not replace a Watchlist Source when its catalog entry is %s",
    async (change) => {
        const first = marketDataSource();
        let catalog = [first];
        const listSources = vi.fn(() => Promise.resolve(catalog));
        const createAcquisition = vi.fn();
        const client = marketDataClient({
            listSources,
            createAcquisition,
            listInstruments: () => Promise.resolve([marketDataInstrument()])
        });
        const wrapper = ({ children }: { readonly children: ReactNode }) => (
            <AppProviders marketDataClient={client}>{children}</AppProviders>
        );
        const { result } = renderHook(() => useMarketDataChart(), { wrapper });
        await waitFor(() => {
            expect(result.current.selectableSources).toHaveLength(1);
        });
        await act(() =>
            result.current.selectWatchlistInstrument(
                onlyMarketDataSourceReference(first),
                "BTCUSDT.TEST"
            )
        );
        expect(result.current.reference).toEqual(onlyMarketDataSourceReference(first));
        catalog =
            change === "changed"
                ? [{ ...first, integration_revision_fingerprint: "c".repeat(64) }]
                : [];
        act(() => {
            result.current.refreshSources();
        });
        await waitFor(() => {
            expect(listSources).toHaveBeenCalledTimes(2);
        });
        await waitFor(() => {
            expect(result.current.reference).toBeNull();
        });
        expect(result.current.sourceId).toBe("");
        expect(result.current.bars).toHaveLength(0);
        expect(result.current.message).toContain("重新绑定");
        expect(createAcquisition).not.toHaveBeenCalled();
    }
);
// One Integration may retain several immutable published Source Revisions.
// Choosing an exact Watchlist reference must not collapse that lineage.
it("keeps two original revisions of one Integration separately selectable", async () => {
    const original = marketDataSource({ is_current_revision: false });
    const published = marketDataSource({ integration_revision_fingerprint: "b".repeat(64) });
    const client = marketDataClient({
        listSources: () => Promise.resolve([original, published]),
        listInstruments: () => Promise.resolve([marketDataInstrument()])
    });
    const wrapper = ({ children }: { readonly children: ReactNode }) => (
        <AppProviders marketDataClient={client}>{children}</AppProviders>
    );
    const { result } = renderHook(() => useMarketDataChart(), { wrapper });
    await waitFor(() => {
        expect(result.current.selectableSources).toHaveLength(2);
    });
    const exact = onlyMarketDataSourceReference(original);
    await act(async () => {
        await result.current.selectWatchlistInstrument(exact, "BTCUSDT.TEST");
    });
    expect(result.current.reference).toEqual(exact);
    act(() => {
        result.current.refreshSources();
    });
    await waitFor(() => {
        expect(result.current.selectableSources).toHaveLength(2);
    });
    expect(result.current.reference).toEqual(exact);
});
