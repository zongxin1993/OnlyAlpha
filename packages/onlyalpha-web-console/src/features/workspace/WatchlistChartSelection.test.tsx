import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { AppProviders } from "../../app/providers";
import { marketDataBarSemantic } from "../../api/marketData/model";
import {
    marketDataBarsForQuery,
    marketDataClient,
    marketDataInstrument,
    marketDataSource,
    FIXTURE_SELECTION
} from "../../test/marketDataClient";
import { onlyMarketDataSourceReference, useMarketDataChart } from "./useMarketDataChart";

vi.mock("../../api/marketData/stream", () => ({ openMarketDataStream: () => () => undefined }));

it("switches exact Watchlist sources while retaining the period and requires explicit preparation for gaps", async () => {
    const first = marketDataSource();
    const second = marketDataSource({
        integration_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        integration_revision_fingerprint: "b".repeat(64)
    });
    const createAcquisition = vi.fn();
    const client = marketDataClient({
        listSources: () => Promise.resolve([first, second]),
        listInstruments: (_reference, _query, _signal, ids) =>
            Promise.resolve([marketDataInstrument({ instrument_id: ids?.[0] ?? "BTCUSDT.TEST" })]),
        queryBars: (reference, query) => {
            const result = marketDataBarsForQuery(query, {
                source_selection: {
                    ...FIXTURE_SELECTION,
                    integration_id: reference.integration_id,
                    integration_revision_fingerprint: reference.integration_revision_fingerprint
                }
            });
            return Promise.resolve(
                reference.integration_id === second.integration_id
                    ? {
                          ...result,
                          bars: [],
                          history_projection_fingerprint: null,
                          resume_after_sequence: null,
                          resume_plan_fingerprint: null,
                          revision_evidence: [],
                          coverage: {
                              ...result.coverage,
                              status: "INCOMPLETE",
                              planned_acquisition_ranges: [
                                  {
                                      start_ns: result.resolved_start_ns,
                                      end_ns: result.resolved_end_ns
                                  }
                              ]
                          }
                      }
                    : result
            );
        },
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
    expect(result.current.sourceId).toBe(second.integration_id);
    expect(result.current.instrument?.instrument_id).toBe("ETHUSDT.TEST");
    expect(result.current.barSemantic).toEqual(marketDataBarSemantic(7));
    expect(result.current.message).toContain("不会自动采集");
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
