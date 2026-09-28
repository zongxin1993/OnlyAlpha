import { act, render, screen, waitFor } from "@testing-library/react";
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
    callbacks: [] as ((event: MarketDataStreamEvent) => void)[],
    disconnects: [] as ((failure?: "MALFORMED_JSON" | "CONTRACT_ERROR") => void)[],
    requests: [] as unknown[],
    closed: { count: 0 }
}));

vi.mock("../../api/marketData/stream", async (original) => ({
    ...(await original()),
    openMarketDataStream: vi.fn(
        (
            request: unknown,
            onEvent: (event: MarketDataStreamEvent) => void,
            onDisconnect: (failure?: "MALFORMED_JSON" | "CONTRACT_ERROR") => void
        ) => {
            stream.callbacks.push(onEvent);
            stream.disconnects.push(onDisconnect);
            stream.requests.push(request);
            return () => {
                stream.closed.count += 1;
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
            <button type="button" onClick={() => void state.selectBarStep(7)}>
                7m
            </button>
            <button type="button" onClick={() => void state.selectBarStep(37)}>
                37m
            </button>
            <output>{state.liveBar?.close ?? "none"}</output>
            <output data-testid="cursor">{state.lastClosedCursor ?? "none"}</output>
            <output data-testid="realtime-status">{state.realtimeStatus}</output>
            <output data-testid="stream-error">{state.streamError ?? "none"}</output>
        </>
    );
}

it("ignores queued events from a stale source or instrument stream", async () => {
    stream.callbacks.length = 0;
    stream.disconnects.length = 0;
    stream.requests.length = 0;
    stream.closed.count = 0;
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
        schema_version: 2,
        event: "BAR_PREVIEW",
        source_id: "test.market_data.live",
        instrument_id: "BTCUSDT.TEST",
        bar_specification: { aggregation: "TIME", step: 1, price_type: "LAST" },
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
    const historicalCursor = (stream.requests[0] as { resume_after_sequence: string })
        .resume_after_sequence;
    expect(historicalCursor).toBe("29453761");
    expect(
        (stream.requests[0] as { resume_plan_fingerprint: string }).resume_plan_fingerprint
    ).toBe("f".repeat(64));
    const nextCursor = (BigInt(historicalCursor) + 1n).toString();
    act(() => {
        first({ schema_version: 2, event: "BASE_CURSOR", sequence: historicalCursor });
        first({ schema_version: 2, event: "BASE_CURSOR", sequence: nextCursor });
        first({ schema_version: 2, event: "BASE_CURSOR", sequence: historicalCursor });
    });
    expect(screen.getByTestId("cursor")).toHaveTextContent(nextCursor);
    first({
        schema_version: 2,
        event: "BAR_PREVIEW",
        source_id: "test.market_data.live",
        instrument_id: "BTCUSDT.TEST",
        bar_specification: { aggregation: "TIME", step: 1, price_type: "LAST" },
        bar: {
            bar_start_ns: "120000000000",
            bar_end_ns: "180000000000",
            open: "3",
            high: "3",
            low: "3",
            close: "3",
            volume: "1",
            closed: false
        }
    });
    await waitFor(() => {
        expect(screen.getByText("3")).toBeInTheDocument();
    });
    first({
        schema_version: 2,
        event: "BAR_PREVIEW",
        source_id: "test.market_data.live",
        instrument_id: "BTCUSDT.TEST",
        bar_specification: { aggregation: "TIME", step: 1, price_type: "LAST" },
        bar: {
            bar_start_ns: "60000000000",
            bar_end_ns: "120000000000",
            open: "9",
            high: "9",
            low: "9",
            close: "9",
            volume: "1",
            closed: false
        }
    });
    expect(screen.getByText("3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "eth" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(2);
    });
    expect((stream.requests[1] as { resume_after_sequence: string }).resume_after_sequence).toBe(
        "29453761"
    );
    expect(
        (stream.requests[1] as { resume_plan_fingerprint: string }).resume_plan_fingerprint
    ).toBe("f".repeat(64));
    first({
        schema_version: 2,
        event: "BAR_PREVIEW",
        source_id: "test.market_data.live",
        instrument_id: "BTCUSDT.TEST",
        bar_specification: { aggregation: "TIME", step: 1, price_type: "LAST" },
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

it("switches 1m to 7m to 37m by closing each old stream and loading typed history", async () => {
    stream.callbacks.length = 0;
    stream.disconnects.length = 0;
    stream.requests.length = 0;
    stream.closed.count = 0;
    const steps: number[] = [];
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
                queryBars: (_reference, query) => {
                    steps.push(query.bar_specification.step);
                    return Promise.resolve(
                        marketDataBars({ bar_specification: query.bar_specification })
                    );
                }
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
    await user.click(screen.getByRole("button", { name: "7m" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(2);
    });
    await user.click(screen.getByRole("button", { name: "37m" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(3);
    });
    expect(steps).toEqual([1, 7, 37]);
    expect(stream.closed.count).toBeGreaterThanOrEqual(2);
    expect(
        stream.requests.map(
            (request) => (request as { bar_specification: { step: number } }).bar_specification.step
        )
    ).toEqual([1, 7, 37]);
    first?.({
        schema_version: 2,
        event: "BAR_PREVIEW",
        source_id: "test.market_data.live",
        instrument_id: "BTCUSDT.TEST",
        bar_specification: { aggregation: "TIME", step: 1, price_type: "LAST" },
        bar: {
            bar_start_ns: "60000000000",
            bar_end_ns: "120000000000",
            open: "999",
            high: "999",
            low: "999",
            close: "999",
            volume: "1",
            closed: false
        }
    });
    expect(screen.queryByText("999")).not.toBeInTheDocument();
    stream.callbacks[2]?.({
        schema_version: 2,
        event: "BAR_PREVIEW",
        source_id: "test.market_data.live",
        instrument_id: "BTCUSDT.TEST",
        bar_specification: { aggregation: "TIME", step: 7, price_type: "LAST" },
        bar: {
            bar_start_ns: "60000000000",
            bar_end_ns: "480000000000",
            open: "999",
            high: "999",
            low: "999",
            close: "999",
            volume: "1",
            closed: false
        }
    });
    expect(screen.queryByText("999")).not.toBeInTheDocument();
    expect(stream.closed.count).toBeGreaterThanOrEqual(3);
});

it("fails a mismatched plan without reconnecting", async () => {
    stream.callbacks.length = 0;
    stream.disconnects.length = 0;
    stream.requests.length = 0;
    const user = userEvent.setup();
    render(
        <AppProviders
            client={researchClient()}
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient()}
        >
            <Harness />
        </AppProviders>
    );
    await user.click(screen.getByRole("button", { name: "source" }));
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(1);
    });
    act(() => {
        stream.callbacks[0]?.({
            schema_version: 2,
            event: "SUBSCRIBED",
            stream_id: "wrong",
            source_id: "test.market_data.live",
            instrument_id: "BTCUSDT.TEST",
            resolution_mode: "EXTERNAL_NATIVE",
            resolution_plan_fingerprint: "a".repeat(64),
            cursor_bar_step_minutes: 1
        });
        stream.disconnects[0]?.();
    });
    expect(screen.getByTestId("realtime-status")).toHaveTextContent("failed");
    expect(screen.getByTestId("stream-error")).toHaveTextContent(
        "MARKET_DATA_RESUME_PLAN_MISMATCH"
    );
    expect(stream.requests).toHaveLength(1);
});

it("reconnects transient closes with bounded exponential delays and the same resume pair", async () => {
    stream.callbacks.length = 0;
    stream.disconnects.length = 0;
    stream.requests.length = 0;
    const user = userEvent.setup();
    render(
        <AppProviders
            client={researchClient()}
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient()}
        >
            <Harness />
        </AppProviders>
    );
    await user.click(screen.getByRole("button", { name: "source" }));
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(1);
    });
    const timer = vi.spyOn(window, "setTimeout");
    act(() => stream.disconnects[0]?.());
    expect(timer.mock.calls.at(-1)?.[1]).toBe(250);
    const reconnect = timer.mock.calls.at(-1)?.[0] as (() => void) | undefined;
    if (typeof reconnect !== "function") throw new Error("missing reconnect callback");
    act(() => {
        reconnect();
    });
    expect(stream.requests).toHaveLength(2);
    expect(stream.requests[1]).toEqual(stream.requests[0]);
    act(() => stream.disconnects[1]?.());
    expect(timer.mock.calls.at(-1)?.[1]).toBe(500);
    timer.mockRestore();
});
