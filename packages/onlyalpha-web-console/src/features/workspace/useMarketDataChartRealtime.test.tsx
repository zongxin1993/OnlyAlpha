import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProviders } from "../../app/providers";
import type { MarketDataStreamEvent } from "../../api/marketData/stream";
import {
    fixedDurationMinutes,
    marketDataBarSemantic,
    type MarketDataBars,
    type MarketDataSourceReference
} from "../../api/marketData/model";
import type { MarketDataBarsQuery } from "../../api/marketData/client";
import {
    dataSourceSummary,
    dataSourceType,
    integrationClient,
    operationalStatus
} from "../../test/integrationClient";
import {
    FIXTURE_SELECTION,
    incompleteBars,
    marketDataBars,
    marketDataBarsForQuery,
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

function resetStream() {
    stream.callbacks.length = 0;
    stream.disconnects.length = 0;
    stream.requests.length = 0;
    stream.closed.count = 0;
}

async function selectFixtureSource(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "source" }));
    await user.click(screen.getByRole("button", { name: "1m" }));
}

it.each(["merge", "stale", "mismatch"] as const)(
    "holds an older page across realtime BAR_CLOSED: %s",
    async (variant) => {
        resetStream();
        const firstBar = marketDataBars().bars[0];
        const lastBar = marketDataBars().bars[1];
        if (firstBar === undefined || lastBar === undefined)
            throw new Error("fixture requires two Bars");
        let release!: (page: MarketDataBars) => void;
        let frozen!: MarketDataBarsQuery;
        const queryBars = vi.fn((_reference, query: MarketDataBarsQuery) => {
            if (query.target_bar_count === 240) {
                frozen = query;
                return new Promise<MarketDataBars>((resolve) => {
                    release = resolve;
                });
            }
            return Promise.resolve(marketDataBarsForQuery(query));
        });
        const user = userEvent.setup();
        render(
            <AppProviders
                client={researchClient()}
                integrationClient={integrationClient()}
                marketDataClient={marketDataClient({ queryBars })}
            >
                <Harness />
            </AppProviders>
        );
        await selectFixtureSource(user);
        await user.click(screen.getByRole("button", { name: "btc" }));
        await waitFor(() => {
            expect(stream.requests).toHaveLength(1);
        });
        act(() => {
            stream.callbacks[0]?.({ schema_version: 2, event: "STATE", state: "READY" });
        });
        await user.click(screen.getByRole("button", { name: "older" }));
        await user.click(screen.getByRole("button", { name: "older" }));
        expect(queryBars).toHaveBeenCalledTimes(2);
        expect(screen.getByTestId("older-status")).toHaveTextContent("loading");
        act(() =>
            stream.callbacks[0]?.({
                schema_version: 2,
                event: "BAR_CLOSED",
                source_id: FIXTURE_SELECTION.source_id,
                instrument_id: "BTCUSDT.TEST",
                bar_semantic: marketDataBarSemantic(1),
                sequence: "29453762",
                bar: {
                    ...lastBar,
                    bar_start_ns: "1767225720000000000",
                    bar_end_ns: "1767225780000000000",
                    close: "103"
                }
            })
        );
        expect(screen.getByTestId("cursor")).toHaveTextContent("29453762");
        const earlier = {
            ...firstBar,
            bar_start_ns: "1767225540000000000",
            bar_end_ns: "1767225600000000000",
            close: "99"
        };
        if (variant === "stale") {
            await user.click(screen.getByRole("button", { name: "eth" }));
            await waitFor(() => {
                expect(stream.requests).toHaveLength(2);
            });
        }
        await act(async () => {
            release(
                marketDataBarsForQuery(frozen, {
                    resolved_start_ns: earlier.bar_start_ns,
                    resolved_end_ns: earlier.bar_end_ns,
                    bars: [earlier, { ...earlier }],
                    ...(variant === "mismatch"
                        ? { source_selection: { ...FIXTURE_SELECTION, source_id: "wrong" } }
                        : {})
                })
            );
            await Promise.resolve();
        });
        if (variant === "stale") {
            expect(screen.getByTestId("closed-bars").textContent).toBe("101.00,102.50");
            expect(screen.getByTestId("context-key")).toHaveTextContent("ETHUSDT.TEST");
            expect(screen.getByTestId("older-status")).toHaveTextContent("idle");
        } else {
            expect(screen.getByTestId("closed-bars").textContent).toBe(
                variant === "merge" ? "99,101.00,102.50,103" : "101.00,102.50,103"
            );
            expect(screen.getByTestId("closed-count").textContent).toBe(
                variant === "merge" ? "4" : "3"
            );
            expect(screen.getByTestId("older-status")).toHaveTextContent(
                variant === "merge" ? "idle" : "failed"
            );
            expect(screen.getByTestId("chart-status")).toHaveTextContent("ready");
            expect(screen.getByTestId("cursor")).toHaveTextContent("29453762");
            expect(stream.requests).toHaveLength(1);
            expect(stream.closed.count).toBe(0);
            expect(screen.getByTestId("realtime-status")).toHaveTextContent("ready");
            if (variant === "merge") {
                const timer = vi.spyOn(window, "setTimeout");
                act(() => {
                    stream.disconnects[0]?.();
                });
                const reconnect = timer.mock.calls.at(-1)?.[0] as (() => void) | undefined;
                if (typeof reconnect !== "function") throw new Error("missing reconnect callback");
                act(() => {
                    reconnect();
                });
                expect(stream.requests[1]).toMatchObject({
                    resume_after_sequence: "29453762",
                    resume_plan_fingerprint: "f".repeat(64)
                });
                timer.mockRestore();
            }
        }
    }
);

it.each(["initial", "reload"] as const)(
    "fails a mismatched %s response before publishing or opening a stream",
    async (path) => {
        resetStream();
        const queryBars = vi.fn((_reference, query: MarketDataBarsQuery) =>
            Promise.resolve(
                path === "reload" && query.anchor_kind === "LATEST_CLOSED"
                    ? marketDataBarsForQuery(query, incompleteBars())
                    : marketDataBarsForQuery(query, {
                          ...(path === "initial" ? incompleteBars() : {}),
                          instrument_id: "ETHUSDT.TEST"
                      })
            )
        );
        const user = userEvent.setup();
        const client = marketDataClient({ queryBars });
        const acquire = vi.spyOn(client, "createAcquisition");
        render(
            <AppProviders
                client={researchClient()}
                integrationClient={integrationClient()}
                marketDataClient={client}
            >
                <Harness />
            </AppProviders>
        );
        await selectFixtureSource(user);
        await user.click(screen.getByRole("button", { name: "btc" }));
        await waitFor(() => {
            expect(screen.getByTestId("chart-status")).toHaveTextContent("failed");
        });
        expect(screen.getByTestId("chart-message")).toHaveTextContent(
            "MARKET_DATA_HISTORY_RESPONSE_MISMATCH"
        );
        expect(screen.getByTestId("closed-count").textContent).toBe("0");
        expect(stream.requests).toHaveLength(0);
        expect(queryBars).toHaveBeenCalledTimes(path === "initial" ? 1 : 2);
        expect(acquire).toHaveBeenCalledTimes(path === "initial" ? 0 : 1);
    }
);

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
                onClick={() => {
                    state.selectSource("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
                }}
            >
                second source
            </button>
            <button
                type="button"
                onClick={() => void state.selectInstrument(marketDataInstrument())}
            >
                btc
            </button>
            <button type="button" onClick={() => void state.selectBarDuration(1)}>
                1m
            </button>
            <button type="button" onClick={() => void state.selectInstrument(eth)}>
                eth
            </button>
            <button type="button" onClick={() => void state.selectBarDuration(7)}>
                7m
            </button>
            <button type="button" onClick={() => void state.selectBarDuration(37)}>
                37m
            </button>
            <button type="button" onClick={() => void state.loadOlderHistory()}>
                older
            </button>
            <button type="button" onClick={() => void state.searchInstruments("ETHUSDT")}>
                search
            </button>
            <output>{state.liveBar?.close ?? "none"}</output>
            <output data-testid="closed-bars">
                {state.bars.map((bar) => bar.close).join(",")}
            </output>
            <output data-testid="closed-count">{state.loadedClosedBarCount}</output>
            <output data-testid="chart-status">{state.status}</output>
            <output data-testid="chart-message">{state.message ?? "none"}</output>
            <output data-testid="context-key">{state.chartContextKey ?? "none"}</output>
            <output data-testid="older-status">{state.olderHistoryStatus}</output>
            <output data-testid="cursor">{state.lastClosedCursor ?? "none"}</output>
            <output data-testid="realtime-status">{state.realtimeStatus}</output>
            <output data-testid="stream-error">{state.streamError ?? "none"}</output>
            <output data-testid="exact-bars">{JSON.stringify(state.bars)}</output>
            <output data-testid="exact-preview">{JSON.stringify(state.liveBar)}</output>
            <output data-testid="coverage">{state.coverage?.status ?? "none"}</output>
            <output data-testid="history-proof">
                {state.historyProjectionFingerprint ?? "none"}
            </output>
            <output data-testid="resolved-source">{state.resolvedSourceId ?? "none"}</output>
        </>
    );
}

it.each(["initial", "reload", "older", "BAR_PREVIEW", "BAR_CLOSED"] as const)(
    "rejects invalid projection before Ledger or cursor mutation: %s",
    async (path) => {
        resetStream();
        const original = marketDataBars().bars[0];
        if (original === undefined) throw new Error("fixture requires a Bar");
        const badBar = { ...original, close: "Infinity" };
        const queryBars = vi.fn((_reference, query: MarketDataBarsQuery) =>
            Promise.resolve(
                marketDataBarsForQuery(
                    query,
                    path === "reload" && query.anchor_kind === "LATEST_CLOSED"
                        ? incompleteBars()
                        : path === "initial" ||
                            path === "reload" ||
                            (path === "older" && query.target_bar_count === 240)
                          ? path === "older"
                              ? {
                                    bars: [
                                        {
                                            ...badBar,
                                            bar_start_ns: "1767225540000000000",
                                            bar_end_ns: "1767225600000000000"
                                        }
                                    ],
                                    resolved_start_ns: "1767225540000000000",
                                    resolved_end_ns: "1767225600000000000"
                                }
                              : { bars: [badBar] }
                          : {}
                )
            )
        );
        const user = userEvent.setup();
        render(
            <AppProviders
                client={researchClient()}
                integrationClient={integrationClient()}
                marketDataClient={marketDataClient({ queryBars })}
            >
                <Harness />
            </AppProviders>
        );
        await selectFixtureSource(user);
        await user.click(screen.getByRole("button", { name: "btc" }));
        if (path === "initial" || path === "reload") {
            await waitFor(() => {
                expect(screen.getByTestId("chart-status")).toHaveTextContent("failed");
            });
            expect(screen.getByTestId("chart-message")).toHaveTextContent(
                "MARKET_DATA_CHART_PROJECTION_INVALID"
            );
            expect(stream.requests).toHaveLength(0);
            expect(screen.getByTestId("exact-bars")).toHaveTextContent("[]");
            return;
        }
        await waitFor(() => {
            expect(stream.requests).toHaveLength(1);
        });
        act(() => stream.callbacks[0]?.({ schema_version: 2, event: "STATE", state: "READY" }));
        const before = screen.getByTestId("exact-bars").textContent;
        if (path === "older") {
            await user.click(screen.getByRole("button", { name: "older" }));
            await waitFor(() => {
                expect(screen.getByTestId("older-status")).toHaveTextContent("failed");
            });
            expect(screen.getByTestId("realtime-status")).toHaveTextContent("ready");
            expect(stream.closed.count).toBe(0);
        } else {
            act(() =>
                stream.callbacks[0]?.({
                    schema_version: 2,
                    event: path,
                    source_id: FIXTURE_SELECTION.source_id,
                    instrument_id: "BTCUSDT.TEST",
                    bar_semantic: marketDataBarSemantic(1),
                    sequence: "29453762",
                    bar: {
                        ...badBar,
                        bar_start_ns: "1767225720000000000",
                        bar_end_ns: "1767225780000000000",
                        closed: path === "BAR_CLOSED"
                    }
                })
            );
            expect(screen.getByTestId("realtime-status")).toHaveTextContent("failed");
            expect(screen.getByTestId("stream-error")).toHaveTextContent(
                "MARKET_DATA_CHART_PROJECTION_INVALID"
            );
            expect(screen.getByTestId("cursor")).toHaveTextContent("none");
            expect(screen.getByTestId("exact-preview")).toHaveTextContent("null");
            expect(stream.closed.count).toBe(1);
            act(() => stream.disconnects[0]?.());
        }
        expect(screen.getByTestId("exact-bars").textContent).toBe(before);
        expect(stream.requests).toHaveLength(1);
        expect(screen.getByTestId("chart-status")).toHaveTextContent("ready");
    }
);

it("retains exact history and idempotently projects preview updates and close", async () => {
    resetStream();
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
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.requests).toHaveLength(1);
    });
    const projected = JSON.parse(screen.getByTestId("exact-bars").textContent) as {
        barStartNs: string;
        open: string;
        volume: string;
    }[];
    const first = projected[0];
    const original = marketDataBars().bars[0];
    if (original === undefined) throw new Error("fixture requires a Bar");
    expect(first).toMatchObject({
        barStartNs: original.bar_start_ns,
        open: original.open,
        volume: original.volume
    });
    const bar = {
        ...original,
        bar_start_ns: "1767225720000000000",
        bar_end_ns: "1767225780000000000",
        closed: false,
        close: "103.000000000000000001"
    };
    const preview = {
        schema_version: 2 as const,
        event: "BAR_PREVIEW" as const,
        source_id: FIXTURE_SELECTION.source_id,
        instrument_id: "BTCUSDT.TEST",
        bar_semantic: marketDataBarSemantic(1),
        bar
    };
    act(() => stream.callbacks[0]?.(preview));
    const exact = screen.getByTestId("exact-preview").textContent;
    act(() => stream.callbacks[0]?.(preview));
    expect(screen.getByTestId("exact-preview").textContent).toBe(exact);
    act(() =>
        stream.callbacks[0]?.({ ...preview, bar: { ...bar, close: "104.000000000000000001" } })
    );
    expect(screen.getByTestId("exact-preview")).toHaveTextContent("104.000000000000000001");
    act(() =>
        stream.callbacks[0]?.({
            ...preview,
            event: "BAR_CLOSED",
            sequence: "29453762",
            bar: { ...bar, closed: true }
        })
    );
    expect(screen.getByTestId("exact-preview")).toHaveTextContent("null");
    expect(screen.getByTestId("exact-bars")).toHaveTextContent("103.000000000000000001");
});

it("keeps initial history, realtime closed Bars, and preview in one ledger projection", async () => {
    stream.callbacks.length = 0;
    stream.disconnects.length = 0;
    stream.requests.length = 0;
    stream.closed.count = 0;
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
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(screen.getByTestId("closed-count")).toHaveTextContent("2");
    });
    const callback = stream.callbacks[0];
    if (callback === undefined) throw new Error("stream missing");

    act(() => {
        callback({
            schema_version: 2,
            event: "BAR_PREVIEW",
            source_id: "test.market_data.live",
            instrument_id: "BTCUSDT.TEST",
            bar_semantic: marketDataBarSemantic(1),
            bar: {
                bar_start_ns: "1767225720000000000",
                bar_end_ns: "1767225780000000000",
                open: "102.5",
                high: "104",
                low: "102",
                close: "103",
                volume: "1",
                closed: false
            }
        });
    });
    expect(screen.getByTestId("closed-count")).toHaveTextContent("2");
    expect(screen.getByText("103")).toBeInTheDocument();

    act(() => {
        callback({
            schema_version: 2,
            event: "BAR_CLOSED",
            source_id: "test.market_data.live",
            instrument_id: "BTCUSDT.TEST",
            bar_semantic: marketDataBarSemantic(1),
            sequence: "29453762",
            bar: {
                bar_start_ns: "1767225720000000000",
                bar_end_ns: "1767225780000000000",
                open: "102.5",
                high: "104",
                low: "102",
                close: "103",
                volume: "1",
                closed: true
            }
        });
    });
    expect(screen.getByTestId("closed-count")).toHaveTextContent("3");
    expect(screen.getByTestId("closed-bars")).toHaveTextContent("101.00,102.50,103");
});

it("preserves current Bars when an older page fails", async () => {
    stream.callbacks.length = 0;
    const queryBars = vi
        .fn()
        .mockResolvedValueOnce(
            marketDataBars({
                anchor_kind: "LATEST_CLOSED",
                requested_before_ns: null,
                requested_bar_count: 1440
            })
        )
        .mockRejectedValueOnce(new Error("older unavailable"));
    const user = userEvent.setup();
    render(
        <AppProviders
            client={researchClient()}
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient({ queryBars })}
        >
            <Harness />
        </AppProviders>
    );
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(screen.getByTestId("closed-count")).toHaveTextContent("2");
    });

    await user.click(screen.getByRole("button", { name: "older" }));

    await waitFor(() => {
        expect(screen.getByTestId("older-status")).toHaveTextContent("failed");
    });
    expect(screen.getByTestId("closed-count")).toHaveTextContent("2");
});

it("fails the exact chart context on a conflicting realtime closed Bar", async () => {
    stream.callbacks.length = 0;
    stream.closed.count = 0;
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
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(1);
    });
    const conflicting = marketDataBars().bars[0];
    if (conflicting === undefined) throw new Error("Market Data fixture requires a first Bar");

    act(() => {
        stream.callbacks[0]?.({
            schema_version: 2,
            event: "BAR_CLOSED",
            source_id: "test.market_data.live",
            instrument_id: "BTCUSDT.TEST",
            bar_semantic: marketDataBarSemantic(1),
            sequence: "29453762",
            bar: { ...conflicting, close: "999" }
        });
    });

    expect(screen.getByTestId("chart-status")).toHaveTextContent("failed");
    expect(screen.getByTestId("chart-message")).toHaveTextContent(
        "MARKET_DATA_BAR_LEDGER_CONFLICT"
    );
    expect(stream.closed.count).toBeGreaterThan(0);
});

it("replaces the ledger when the exact Integration Revision changes", async () => {
    stream.callbacks.length = 0;
    stream.requests.length = 0;
    const user = userEvent.setup();
    const view = (revision: string) => (
        <AppProviders
            key={revision}
            client={researchClient()}
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient({
                listSources: () =>
                    Promise.resolve([
                        marketDataSource({ integration_revision_fingerprint: revision })
                    ]),
                queryBars: (_reference, query) =>
                    Promise.resolve(
                        marketDataBarsForQuery(query, {
                            source_selection: {
                                ...FIXTURE_SELECTION,
                                integration_revision_fingerprint: revision
                            }
                        })
                    )
            })}
        >
            <Harness />
        </AppProviders>
    );
    const rendered = render(view("a".repeat(64)));
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(1);
    });
    act(() => {
        stream.callbacks[0]?.({
            schema_version: 2,
            event: "BAR_CLOSED",
            source_id: "test.market_data.live",
            instrument_id: "BTCUSDT.TEST",
            bar_semantic: marketDataBarSemantic(1),
            sequence: "29453762",
            bar: {
                bar_start_ns: "1767225720000000000",
                bar_end_ns: "1767225780000000000",
                open: "102.5",
                high: "104",
                low: "102",
                close: "103",
                volume: "1",
                closed: true
            }
        });
    });
    expect(screen.getByTestId("closed-count")).toHaveTextContent("3");

    rendered.rerender(view("b".repeat(64)));
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));

    await waitFor(() => {
        expect(screen.getByTestId("context-key")).toHaveTextContent("b".repeat(64));
        expect(screen.getByTestId("closed-count")).toHaveTextContent("2");
    });
});

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
                queryBars: (_reference, query) => Promise.resolve(marketDataBarsForQuery(query))
            })}
        >
            <Harness />
        </AppProviders>
    );
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(1);
    });
    const btcContext = screen.getByTestId("context-key").textContent;
    const first = stream.callbacks[0];
    if (first === undefined) throw new Error("first stream missing");
    first({
        schema_version: 2,
        event: "BAR_PREVIEW",
        source_id: "test.market_data.live",
        instrument_id: "BTCUSDT.TEST",
        bar_semantic: marketDataBarSemantic(1),
        bar: {
            bar_start_ns: "1767225720000000000",
            bar_end_ns: "1767225780000000000",
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
        bar_semantic: marketDataBarSemantic(1),
        bar: {
            bar_start_ns: "1767225780000000000",
            bar_end_ns: "1767225840000000000",
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
        bar_semantic: marketDataBarSemantic(1),
        bar: {
            bar_start_ns: "1767225720000000000",
            bar_end_ns: "1767225780000000000",
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
    expect(screen.getByTestId("context-key").textContent).not.toBe(btcContext);
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
        bar_semantic: marketDataBarSemantic(1),
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
                    steps.push(fixedDurationMinutes(query.bar_semantic));
                    return Promise.resolve(marketDataBarsForQuery(query));
                }
            })}
        >
            <Harness />
        </AppProviders>
    );
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(1);
    });
    const oneMinuteContext = screen.getByTestId("context-key").textContent;
    const first = stream.callbacks[0];
    await user.click(screen.getByRole("button", { name: "7m" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(2);
    });
    const sevenMinuteContext = screen.getByTestId("context-key").textContent;
    await user.click(screen.getByRole("button", { name: "37m" }));
    await waitFor(() => {
        expect(stream.callbacks).toHaveLength(3);
    });
    expect(steps).toEqual([1, 7, 37]);
    expect(sevenMinuteContext).not.toBe(oneMinuteContext);
    expect(screen.getByTestId("context-key").textContent).not.toBe(sevenMinuteContext);
    expect(stream.closed.count).toBeGreaterThanOrEqual(2);
    expect(
        stream.requests.map((request) =>
            fixedDurationMinutes(
                (request as { bar_semantic: ReturnType<typeof marketDataBarSemantic> }).bar_semantic
            )
        )
    ).toEqual([1, 7, 37]);
    first?.({
        schema_version: 2,
        event: "BAR_PREVIEW",
        source_id: "test.market_data.live",
        instrument_id: "BTCUSDT.TEST",
        bar_semantic: marketDataBarSemantic(1),
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
        bar_semantic: marketDataBarSemantic(7),
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
    await selectFixtureSource(user);
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
            resolution_mode: "PROVIDER_NATIVE",
            resolution_plan_fingerprint: "a".repeat(64),
            cursor_bar_stride_minutes: 1
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
    await selectFixtureSource(user);
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

it("keeps the active ledger, cursor and stream when reselecting the current context", async () => {
    resetStream();
    const queryBars = vi.fn((_reference, query: MarketDataBarsQuery) =>
        Promise.resolve(marketDataBarsForQuery(query))
    );
    const user = userEvent.setup();
    render(
        <AppProviders
            client={researchClient()}
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient({ queryBars })}
        >
            <Harness />
        </AppProviders>
    );
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.requests).toHaveLength(1);
    });
    act(() => {
        stream.callbacks[0]?.({ schema_version: 2, event: "STATE", state: "READY" });
        stream.callbacks[0]?.({ schema_version: 2, event: "BASE_CURSOR", sequence: "29453762" });
    });
    const context = screen.getByTestId("context-key").textContent;
    const bars = screen.getByTestId("exact-bars").textContent;
    for (const name of ["source", "btc", "1m"]) {
        await user.click(screen.getByRole("button", { name }));
        expect(screen.getByTestId("context-key").textContent).toBe(context);
        expect(screen.getByTestId("exact-bars").textContent).toBe(bars);
        expect(screen.getByTestId("cursor")).toHaveTextContent("29453762");
        expect(screen.getByTestId("realtime-status")).toHaveTextContent("ready");
        expect(queryBars).toHaveBeenCalledTimes(1);
        expect(stream.requests).toHaveLength(1);
        expect(stream.closed.count).toBe(0);
    }
});

it("keeps admitted history and its live consumer when an instrument search fails", async () => {
    resetStream();
    const user = userEvent.setup();
    render(
        <AppProviders
            client={researchClient()}
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient({
                listInstruments: () => Promise.reject(new Error("search unavailable"))
            })}
        >
            <Harness />
        </AppProviders>
    );
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.requests).toHaveLength(1);
    });
    const bars = screen.getByTestId("exact-bars").textContent;
    const context = screen.getByTestId("context-key").textContent;
    const proof = screen.getByTestId("history-proof").textContent;
    await user.click(screen.getByRole("button", { name: "search" }));
    expect(screen.getByTestId("chart-status")).toHaveTextContent("ready");
    expect(screen.getByTestId("exact-bars").textContent).toBe(bars);
    expect(screen.getByTestId("context-key").textContent).toBe(context);
    expect(screen.getByTestId("history-proof").textContent).toBe(proof);
    expect(stream.requests).toHaveLength(1);
    expect(stream.closed.count).toBe(0);
});

it.each(["btc", "1m"])(
    "allows explicit %s recovery after terminal stream failure",
    async (action) => {
        resetStream();
        const queryBars = vi.fn((_reference, query: MarketDataBarsQuery) =>
            Promise.resolve(marketDataBarsForQuery(query))
        );
        const user = userEvent.setup();
        render(
            <AppProviders
                client={researchClient()}
                integrationClient={integrationClient()}
                marketDataClient={marketDataClient({ queryBars })}
            >
                <Harness />
            </AppProviders>
        );
        await selectFixtureSource(user);
        await user.click(screen.getByRole("button", { name: "btc" }));
        await waitFor(() => {
            expect(stream.requests).toHaveLength(1);
        });
        act(() => {
            stream.callbacks[0]?.({
                schema_version: 2,
                event: "ERROR",
                code: "PROVIDER_UNAVAILABLE"
            });
        });
        expect(screen.getByTestId("realtime-status")).toHaveTextContent("failed");
        await user.click(screen.getByRole("button", { name: action }));
        await waitFor(() => {
            expect(stream.requests).toHaveLength(2);
        });
        expect(queryBars).toHaveBeenCalledTimes(2);
        expect(stream.closed.count).toBe(1);
        expect(screen.getByTestId("realtime-status")).toHaveTextContent("connecting");
    }
);

it.each(["btc", "1m"])("allows explicit %s re-entry after incomplete history", async (action) => {
    resetStream();
    const queryBars = vi.fn((_reference, query: MarketDataBarsQuery) =>
        Promise.resolve(
            marketDataBarsForQuery(
                query,
                queryBars.mock.calls.length <= 2
                    ? {
                          ...incompleteBars(),
                          anchor_kind: query.anchor_kind,
                          requested_before_ns: query.before_ns ?? null,
                          instrument_id: query.instrument_id,
                          bar_semantic: query.bar_semantic,
                          coverage: { ...incompleteBars().coverage, planned_acquisition_ranges: [] }
                      }
                    : {}
            )
        )
    );
    const user = userEvent.setup();
    render(
        <AppProviders
            client={researchClient()}
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient({ queryBars })}
        >
            <Harness />
        </AppProviders>
    );
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(screen.getByTestId("chart-status")).toHaveTextContent("incomplete");
    });
    expect(stream.requests).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: action }));
    await waitFor(() => {
        expect(stream.requests).toHaveLength(1);
    });
    expect(queryBars).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("chart-status")).toHaveTextContent("ready");
});

it("fences held out-of-order history across rapid source, instrument and period changes", async () => {
    resetStream();
    const secondSource = marketDataSource({
        integration_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        integration_revision_fingerprint: "b".repeat(64),
        source_id: "second.server.source"
    });
    const held: { release: (bars: MarketDataBars) => void; bars: MarketDataBars }[] = [];
    const queryBars = vi.fn((_reference: MarketDataSourceReference, query: MarketDataBarsQuery) => {
        const bars = marketDataBarsForQuery(query, {
            source_selection:
                _reference.integration_id === secondSource.integration_id
                    ? {
                          ...FIXTURE_SELECTION,
                          integration_id: secondSource.integration_id,
                          integration_revision_fingerprint:
                              secondSource.integration_revision_fingerprint,
                          source_id: secondSource.source_id
                      }
                    : FIXTURE_SELECTION
        });
        if (queryBars.mock.calls.length === 1) return Promise.resolve(bars);
        return new Promise<MarketDataBars>((release) => {
            held.push({ release, bars });
        });
    });
    const user = userEvent.setup();
    render(
        <AppProviders
            client={researchClient()}
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient({
                listSources: () => Promise.resolve([marketDataSource(), secondSource]),
                queryBars
            })}
        >
            <Harness />
        </AppProviders>
    );
    await selectFixtureSource(user);
    await user.click(screen.getByRole("button", { name: "btc" }));
    await waitFor(() => {
        expect(stream.requests).toHaveLength(1);
    });
    for (const name of ["eth", "7m", "second source", "btc", "37m"]) {
        await user.click(screen.getByRole("button", { name }));
        expect(screen.getByTestId("coverage")).toHaveTextContent("none");
        expect(screen.getByTestId("history-proof")).toHaveTextContent("none");
        expect(screen.getByTestId("resolved-source")).toHaveTextContent("none");
        expect(screen.getByTestId("exact-bars")).toHaveTextContent("[]");
    }
    expect(held).toHaveLength(4);
    const final = held[3];
    if (final === undefined) throw new Error("Final history request not held");
    await act(async () => {
        final.release(final.bars);
        await Promise.resolve();
    });
    await waitFor(() => {
        expect(stream.requests).toHaveLength(2);
    });
    const current = screen.getByTestId("context-key").textContent;
    expect(current).toContain(secondSource.integration_revision_fingerprint);
    expect(current).toContain("BTCUSDT.TEST");
    expect(current).toContain('"window_minutes":37');
    expect(stream.closed.count).toBe(1);
    for (const index of [1, 0, 2]) {
        const stale = held[index];
        if (stale === undefined) throw new Error("Stale history request not held");
        await act(async () => {
            stale.release(stale.bars);
            stream.callbacks[0]?.({ schema_version: 2, event: "STATE", state: "READY" });
            await Promise.resolve();
        });
        expect(screen.getByTestId("context-key").textContent).toBe(current);
        expect(screen.getByTestId("resolved-source")).toHaveTextContent(secondSource.source_id);
        expect(screen.getByTestId("realtime-status")).toHaveTextContent("connecting");
        expect(stream.requests).toHaveLength(2);
        expect(stream.closed.count).toBe(1);
    }
});
