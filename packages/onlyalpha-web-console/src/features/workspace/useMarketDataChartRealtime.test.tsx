import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProviders } from "../../app/providers";
import type { MarketDataStreamEvent } from "../../api/marketData/stream";
import {
    dataSourceSummary,
    dataSourceType,
    integrationClient,
    operationalStatus
} from "../../test/integrationClient";
import {
    marketDataBars,
    marketDataClient,
    marketDataInstrument,
    marketDataSource
} from "../../test/marketDataClient";
import { researchClient } from "../../test/researchClient";
import { useMarketDataChart } from "./useMarketDataChart";

const stream = vi.hoisted(() => ({
    callbacks: [] as ((event: MarketDataStreamEvent) => void)[]
}));

vi.mock("../../api/marketData/stream", async (original) => ({
    ...(await original()),
    openMarketDataStream: vi.fn(
        (_request: unknown, onEvent: (event: MarketDataStreamEvent) => void) => {
            stream.callbacks.push(onEvent);
            return () => {
                return undefined;
            };
        }
    )
}));

const eth = { ...marketDataInstrument(), instrument_id: "ETHUSDT.TEST", display_symbol: "ETHUSDT" };

function Harness() {
    const state = useMarketDataChart();
    return (
        <>
            <button
                type="button"
                onClick={() => {
                    state.selectSource(marketDataSource().integration_id);
                }}
            >
                source
            </button>
            <button
                type="button"
                onClick={() => void state.selectInstrument(marketDataInstrument())}
            >
                btc
            </button>
            <button type="button" onClick={() => void state.selectInstrument(eth)}>
                eth
            </button>
            <output>{state.liveBar?.close ?? "none"}</output>
        </>
    );
}

it("ignores queued events from a stale source or instrument stream", async () => {
    stream.callbacks.length = 0;
    const user = userEvent.setup();
    render(
        <AppProviders
            client={researchClient()}
            integrationClient={integrationClient({
                listTypes: () => Promise.resolve([dataSourceType()]),
                listDataSources: () => Promise.resolve([dataSourceSummary()]),
                getOperationalStatus: () => Promise.resolve(operationalStatus({ status: "READY" }))
            })}
            marketDataClient={marketDataClient({
                listInstruments: () => Promise.resolve([marketDataInstrument(), eth]),
                queryBars: () => Promise.resolve(marketDataBars())
            })}
        >
            <Harness />
        </AppProviders>
    );
    await user.click(screen.getByRole("button", { name: "source" }));
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(1);
    });
    const first = stream.callbacks[0];
    if (first === undefined) throw new Error("first stream missing");
    first({
        schema_version: 1,
        event: "BAR_PREVIEW",
        source_id: "source",
        instrument_id: "BTCUSDT.TEST",
        bar_specification: "1m",
        bar: {
            bar_start_ns: "60000000000",
            bar_end_ns: "120000000000",
            open: "1",
            high: "2",
            low: "0.5",
            close: "2",
            volume: "1",
            closed: false
        }
    });
    await waitFor(() => {
        expect(screen.getByText("2")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "eth" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(2);
    });
    first({
        schema_version: 1,
        event: "BAR_PREVIEW",
        source_id: "source",
        instrument_id: "BTCUSDT.TEST",
        bar_specification: "1m",
        bar: {
            bar_start_ns: "120000000000",
            bar_end_ns: "180000000000",
            open: "999",
            high: "999",
            low: "999",
            close: "999",
            volume: "1",
            closed: false
        }
    });
    expect(screen.queryByText("999")).not.toBeInTheDocument();
});
