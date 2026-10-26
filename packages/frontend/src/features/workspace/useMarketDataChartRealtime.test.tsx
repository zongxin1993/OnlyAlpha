import { requiredValue } from "../../test/requiredValue";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AppProviders } from "../../app/providers";
import { useMarketDataChart, STREAM_RECONNECT_DELAYS_MS } from "./useMarketDataChart";
import {
    marketDataClient,
    marketDataSource,
    marketDataInstrument,
    FIXTURE_SELECTION
} from "../../test/marketDataClient";
import { integrationClient } from "../../test/integrationClient";
import { marketDataSourceChoiceKey } from "../../api/marketData/model";
import { MarketDataWebError, type MarketDataBarsQuery } from "../../api/marketData/client";
import { readTemporaryMarketData } from "../../api/marketData/temporary";
import { openTemporaryMarketDataStream } from "../../api/marketData/temporaryStream";
import { temporaryMarketDataWindowSchema } from "../../api/marketData/temporary.generated";
vi.mock("../../api/marketData/temporary", () => ({ readTemporaryMarketData: vi.fn() }));
vi.mock("../../api/marketData/temporaryStream", () => ({
    openTemporaryMarketDataStream: vi.fn(() => vi.fn())
}));
function windowFor(query: MarketDataBarsQuery) {
    const stride =
        BigInt(
            query.bar_semantic.formation.kind === "FIXED_DURATION"
                ? query.bar_semantic.formation.window_minutes
                : 1
        ) * 60000000000n;
    const end = BigInt(query.before_ns ?? "1767225600000000000");
    const start = end - BigInt(query.target_bar_count) * stride;
    return temporaryMarketDataWindowSchema.parse({
        schema_version: 1,
        source_kind: "TEMPORARY_MARKET_DATA",
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        source_selection: FIXTURE_SELECTION,
        instrument_id: query.instrument_id,
        bar_semantic: query.bar_semantic,
        anchor_kind: query.anchor_kind,
        requested_before_ns: query.before_ns ?? null,
        requested_bar_count: query.target_bar_count,
        resolved_start_ns: start.toString(),
        resolved_end_ns: end.toString(),
        coverage: {
            status: "COMPLETE",
            expected_bar_count: query.target_bar_count,
            actual_bar_count: query.target_bar_count,
            gaps: []
        },
        bars: Array.from({ length: query.target_bar_count }, (_, index) => ({
            bar_start_ns: (start + BigInt(index) * stride).toString(),
            bar_end_ns: (start + BigInt(index + 1) * stride).toString(),
            open: "10.00",
            high: "12.00",
            low: "9.00",
            close: "11.00",
            volume: "1.00",
            closed: true
        })),
        window_fingerprint: "a".repeat(64),
        calendar_fingerprint: "b".repeat(64),
        resolution_plan_fingerprint: "c".repeat(64),
        resolution_mode: "PROVIDER_NATIVE"
    });
}
function Probe() {
    const state = useMarketDataChart();
    return (
        <>
            <button
                disabled={state.selectableSources.length === 0}
                onClick={() => {
                    state.selectSource(marketDataSourceChoiceKey(marketDataSource()));
                }}
            >
                source
            </button>
            <button onClick={() => void state.selectInstrument(marketDataInstrument())}>
                instrument
            </button>
            <button
                onClick={() =>
                    void state.selectInstrument(
                        marketDataInstrument({
                            instrument_id: "ETHUSDT.TEST",
                            display_symbol: "ETHUSDT"
                        })
                    )
                }
            >
                eth
            </button>
            <button onClick={() => void state.selectBarDuration(1)}>1m</button>
            <button onClick={() => void state.selectBarDuration(15)}>15m</button>
            <button onClick={() => void state.selectBarDuration(7)}>7m</button>
            <button onClick={() => void state.selectBarDuration(37)}>37m</button>
            <button onClick={() => void state.loadOlderHistory(true)}>older</button>
            <button onClick={() => void state.loadOlderHistory()}>auto-older</button>
            <button onClick={() => void state.searchInstruments("ETHUSDT")}>search</button>
            <button
                onClick={() => {
                    state.refreshSources();
                }}
            >
                refresh
            </button>
            <output data-testid="latest">{state.bars.at(-1)?.close ?? "none"}</output>
            <output data-testid="latest-end">{state.bars.at(-1)?.barEndNs ?? "none"}</output>
            <output data-testid="live">{state.liveBar?.close ?? "none"}</output>
            <output data-testid="context">{state.chartContextKey}</output>
            <output data-testid="timing">{JSON.stringify(state.timing)}</output>
            <output data-testid="realtime">{state.realtimeStatus}</output>
            <output data-testid="message">{state.message}</output>
            <output data-testid="older">{state.olderHistoryStatus}</output>
            <output data-testid="fingerprint">{state.windowFingerprint ?? "none"}</output>
            <output data-testid="status">{state.status}</output>
            <output data-testid="count">{state.loadedClosedBarCount}</output>
        </>
    );
}
afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllEnvs();
    vi.useRealTimers();
});
it("loads 2000 temporary closed bars and subscribes without any persistent history or acquisition call", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    vi.mocked(readTemporaryMarketData).mockImplementation((_credentials, _ref, query) =>
        Promise.resolve(windowFor(query))
    );
    const queryBars = vi.fn(() =>
        Promise.resolve().then(() => {
            throw new Error("persistent history is prohibited");
        })
    );
    const createAcquisition = vi.fn(() =>
        Promise.resolve().then(() => {
            throw new Error("implicit acquisition is prohibited");
        })
    );
    const queryLatestBar = vi.fn(() =>
        Promise.resolve().then(() => {
            throw new Error("retained-history fallback is prohibited");
        })
    );
    const api = marketDataClient({ queryBars, createAcquisition, queryLatestBar });
    render(
        <AppProviders integrationClient={integrationClient()} marketDataClient={api}>
            <Probe />
        </AppProviders>
    );
    const user = userEvent.setup();
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "source" })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "source" }));
    await user.click(screen.getByRole("button", { name: "instrument" }));
    await waitFor(() => {
        expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });
    expect(screen.getByTestId("count")).toHaveTextContent("2000");
    expect(queryBars).not.toHaveBeenCalled();
    expect(createAcquisition).not.toHaveBeenCalled();
    expect(queryLatestBar).not.toHaveBeenCalled();
    await waitFor(() => {
        expect(openTemporaryMarketDataStream).toHaveBeenCalled();
    });
    expect(requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[0]).toMatchObject({
        operation: "SUBSCRIBE_TEMPORARY_BARS",
        expected_window_fingerprint: "a".repeat(64),
        target_bar_count: 2000
    });
});
async function running(
    overrides: Parameters<typeof marketDataClient>[0] = {},
    reader: typeof readTemporaryMarketData = (_credentials, _ref, query) =>
        Promise.resolve(windowFor(query)),
    expected = "ready"
) {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    vi.mocked(readTemporaryMarketData).mockImplementation(reader);
    const closures: ReturnType<typeof vi.fn>[] = [];
    vi.mocked(openTemporaryMarketDataStream).mockImplementation(() => {
        const close = vi.fn();
        closures.push(close);
        return close;
    });
    const api = marketDataClient(overrides);
    const view = render(
        <AppProviders integrationClient={integrationClient()} marketDataClient={api}>
            <Probe />
        </AppProviders>
    );
    const user = userEvent.setup();
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "source" })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "source" }));
    await user.click(screen.getByRole("button", { name: "instrument" }));
    await waitFor(() => {
        expect(screen.getByTestId("status")).toHaveTextContent(expected);
    });
    if (expected === "ready")
        await waitFor(() => {
            expect(openTemporaryMarketDataStream).toHaveBeenCalled();
        });
    return { view, user, closures, api };
}
function lastQuery() {
    return requiredValue(vi.mocked(readTemporaryMarketData).mock.calls.at(-1))[2];
}
it.each([1, 7])(
    "keeps the current %im calculation prefix through older paging without a new close",
    async (minutes) => {
        const t = await running();
        await t.user.click(screen.getByRole("button", { name: `${String(minutes)}m` }));
        await waitFor(() => {
            expect(screen.getByTestId("context")).toHaveTextContent(
                `"window_minutes":${String(minutes)}`
            );
            expect(screen.getByTestId("status")).toHaveTextContent("ready");
        });
        expect(screen.getByTestId("latest-end")).toHaveTextContent("1767225600000000000");
        emitBar("BAR_PREVIEW");
        for (let page = 0; page < 9; page++) {
            await t.user.click(screen.getByRole("button", { name: /^older$/ }));
            await waitFor(() => {
                expect(screen.getByTestId("older")).toHaveTextContent("idle");
            });
        }
        expect(screen.getByTestId("count")).toHaveTextContent(/^4000$/);
        expect(screen.getByTestId("latest-end")).toHaveTextContent("1767225600000000000");
    }
);
function emitBar(kind: "BAR_CLOSED" | "BAR_PREVIEW", change: Record<string, unknown> = {}) {
    const query = lastQuery(),
        base = windowFor(query),
        last = requiredValue(base.bars.at(-1));
    const width = BigInt(last.bar_end_ns) - BigInt(last.bar_start_ns);
    const value = {
        ...last,
        bar_start_ns: last.bar_end_ns,
        bar_end_ns: (BigInt(last.bar_end_ns) + width).toString(),
        closed: kind === "BAR_CLOSED",
        close: "11.50",
        ...change
    };
    const callback = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[1];
    act(() => {
        callback({
            schema_version: 2,
            event: kind,
            source_id: FIXTURE_SELECTION.source_id,
            instrument_id: query.instrument_id,
            bar_semantic: query.bar_semantic,
            bar: value,
            timing: null,
            ...(kind === "BAR_CLOSED" ? { sequence: "123" } : {})
        } as Parameters<typeof callback>[0]);
    });
}
it("keeps preview separate and closes it only after the corresponding closed bar", async () => {
    await running();
    emitBar("BAR_PREVIEW");
    expect(screen.getByTestId("live")).toHaveTextContent("11.5");
    expect(screen.getByTestId("count")).toHaveTextContent("2000");
    emitBar("BAR_CLOSED");
    expect(screen.getByTestId("count")).toHaveTextContent("2001");
    expect(screen.getByTestId("live")).toHaveTextContent("none");
    emitBar("BAR_PREVIEW");
    expect(screen.getByTestId("live")).toHaveTextContent("none");
});
it.each(["BAR_CLOSED", "BAR_PREVIEW"] as const)(
    "rejects a different instrument in %s",
    async (kind) => {
        await running();
        const query = lastQuery(),
            callback = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[1];
        const bar = requiredValue(windowFor(query).bars.at(-1));
        act(() => {
            callback({
                schema_version: 2,
                event: kind,
                source_id: FIXTURE_SELECTION.source_id,
                instrument_id: "OTHER.TEST",
                bar_semantic: query.bar_semantic,
                bar: { ...bar, closed: kind === "BAR_CLOSED" },
                timing: null,
                ...(kind === "BAR_CLOSED" ? { sequence: "123" } : {})
            } as Parameters<typeof callback>[0]);
        });
        expect(screen.getByTestId("status")).toHaveTextContent("failed");
        expect(screen.getByTestId("count")).toHaveTextContent("0");
    }
);
it.each(["BAR_CLOSED", "BAR_PREVIEW"] as const)(
    "rejects unsafe renderer values from %s before mutation",
    async (kind) => {
        await running();
        emitBar(kind, { close: "9".repeat(400) });
        expect(screen.getByTestId("status")).toHaveTextContent("failed");
        expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
    }
);
it("fails the context on a conflicting closed fact and stops its old subscription", async () => {
    const t = await running();
    const query = lastQuery(),
        callback = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[1];
    act(() => {
        callback({
            schema_version: 2,
            event: "BAR_CLOSED",
            source_id: FIXTURE_SELECTION.source_id,
            instrument_id: query.instrument_id,
            bar_semantic: query.bar_semantic,
            bar: { ...requiredValue(windowFor(query).bars.at(-1)), close: "10.50" },
            sequence: "123",
            timing: null
        });
    });
    expect(screen.getByTestId("status")).toHaveTextContent("failed");
    expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
    expect(t.closures[0]).toHaveBeenCalled();
});
it("closes old subscriptions across 1m, 7m and 37m without deriving input cursors in the browser", async () => {
    const t = await running();
    for (const period of ["1m", "7m", "37m"]) {
        await t.user.click(screen.getByRole("button", { name: period }));
        await waitFor(() => {
            expect(screen.getByTestId("status")).toHaveTextContent("ready");
        });
    }
    expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(4);
    expect(t.closures.slice(0, 3).every((close) => close.mock.calls.length === 1)).toBe(true);
    expect(
        requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[0]
    ).not.toHaveProperty("resume_after_sequence");
});
it("drops queued events from the original instrument subscription", async () => {
    const t = await running();
    const old = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[1],
        query = lastQuery();
    await t.user.click(screen.getByRole("button", { name: "eth" }));
    await waitFor(() => {
        expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(2);
    });
    const before = screen.getByTestId("latest").textContent;
    act(() => {
        old({
            schema_version: 2,
            event: "BAR_CLOSED",
            source_id: FIXTURE_SELECTION.source_id,
            instrument_id: query.instrument_id,
            bar_semantic: query.bar_semantic,
            bar: { ...requiredValue(windowFor(query).bars.at(-1)), close: "10.50" },
            sequence: "123",
            timing: null
        });
    });
    expect(screen.getByTestId("latest").textContent).toBe(before);
    expect(screen.getByTestId("context")).toHaveTextContent("ETHUSDT.TEST");
});
it("keeps the active context when reselecting the same source, instrument or duration", async () => {
    const t = await running();
    const reads = vi.mocked(readTemporaryMarketData).mock.calls.length;
    for (const name of ["source", "instrument"]) {
        await t.user.click(screen.getByRole("button", { name }));
    }
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(reads);
    expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(1);
    expect(t.closures[0]).not.toHaveBeenCalled();
});
it("keeps price data and subscription when search fails", async () => {
    const t = await running({
        listInstruments: vi.fn(() =>
            Promise.resolve().then(() => {
                throw new Error("search unavailable");
            })
        )
    });
    await t.user.click(screen.getByRole("button", { name: "search" }));
    expect(screen.getByTestId("count")).toHaveTextContent("2000");
    expect(t.closures[0]).not.toHaveBeenCalled();
});
it("retains trusted current data when an older temporary page fails", async () => {
    const t = await running();
    vi.mocked(readTemporaryMarketData).mockRejectedValueOnce(
        new MarketDataWebError("TRANSPORT_ERROR", "offline")
    );
    await t.user.click(screen.getByRole("button", { name: "older" }));
    await waitFor(() => {
        expect(screen.getByTestId("older")).toHaveTextContent("failed");
    });
    expect(screen.getByTestId("count")).toHaveTextContent("2000");
});
it.each([
    ["LOCAL_READ_UNAUTHORIZED", 401],
    ["MARKET_DATA_ACCESS_DENIED", 403],
    ["MARKET_DATA_PROVENANCE_CONFLICT", 409],
    ["MARKET_DATA_TEMPORARY_RESPONSE_MISMATCH", 503],
    ["MARKET_DATA_SOURCE_CATALOG_CORRUPT", 503],
    ["CONTRACT_ERROR", 403]
] as const)("withdraws shared chart proof after older paging refuses %s", async (code, status) => {
    const t = await running();
    const callback = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[1];
    act(() => {
        callback({ schema_version: 2, event: "STATE", state: "READY" });
    });
    expect(screen.getByTestId("fingerprint")).not.toHaveTextContent("none");
    vi.mocked(readTemporaryMarketData).mockRejectedValueOnce(
        new MarketDataWebError(code, "denied", status)
    );
    await t.user.click(screen.getByRole("button", { name: "older" }));
    await waitFor(() => {
        expect(screen.getByTestId("status")).toHaveTextContent("failed");
    });
    expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
    expect(screen.getByTestId("count")).toHaveTextContent(/^0$/);
    expect(screen.getByTestId("realtime")).toHaveTextContent("failed");
    expect(t.closures[0]).toHaveBeenCalled();
    act(() => {
        callback({ schema_version: 2, event: "STATE", state: "READY" });
    });
    emitBar("BAR_PREVIEW");
    emitBar("BAR_CLOSED");
    expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
    expect(screen.getByTestId("count")).toHaveTextContent(/^0$/);
    expect(screen.getByTestId("live")).toHaveTextContent("none");
    expect(screen.getByTestId("realtime")).toHaveTextContent("failed");
});

it("retains stale data on disconnect and re-pins the last closed target before reconnecting", async () => {
    const t = await running();
    emitBar("BAR_CLOSED");
    const closedEnd = requiredValue(windowFor(lastQuery()).bars.at(-1)).bar_end_ns;
    const width =
        BigInt(closedEnd) - BigInt(requiredValue(windowFor(lastQuery()).bars.at(-1)).bar_start_ns);
    vi.useFakeTimers();
    const disconnected = requiredValue(
        vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1)
    )[2];
    act(() => {
        disconnected();
    });
    expect(screen.getByTestId("realtime")).toHaveTextContent("degraded");
    expect(screen.getByTestId("count")).toHaveTextContent("2001");
    await act(async () => {
        await vi.advanceTimersByTimeAsync(250);
    });
    expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(2);
    expect(lastQuery().anchor_kind).toBe("BEFORE_TIME");
    expect(lastQuery().before_ns).toBe((BigInt(closedEnd) + width).toString());
    t.view.unmount();
    expect(vi.getTimerCount()).toBe(0);
});
it("clears data on authentication refusal instead of reconnecting", async () => {
    await running();
    act(() => {
        requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[2](
            "AUTHENTICATION_ERROR"
        );
    });
    expect(screen.getByTestId("count")).toHaveTextContent("0");
    expect(screen.getByTestId("status")).toHaveTextContent("failed");
    expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(1);
});
it.each(["initial", "reload", "older"] as const)(
    "rejects non-finite price values on %s before publishing data",
    async (path) => {
        const invalid = (query: MarketDataBarsQuery) => {
            const value = windowFor(query);
            requiredValue(value.bars[0]).close = "9".repeat(400);
            return value;
        };
        if (path === "initial") {
            await running({}, (_c, _r, q) => Promise.resolve(invalid(q)), "failed");
            expect(screen.getByTestId("count")).toHaveTextContent(/^0$/);
            return;
        }
        const t = await running();
        vi.mocked(readTemporaryMarketData).mockImplementation((_c, _r, q) =>
            Promise.resolve(invalid(q))
        );
        await t.user.click(screen.getByRole("button", { name: path === "older" ? "older" : "1m" }));
        if (path === "older") {
            await waitFor(() => {
                expect(screen.getByTestId("older")).toHaveTextContent("failed");
            });
            expect(screen.getByTestId("count")).toHaveTextContent(/^2000$/);
        } else {
            await waitFor(() => {
                expect(screen.getByTestId("status")).toHaveTextContent("failed");
            });
            expect(screen.getByTestId("count")).toHaveTextContent(/^0$/);
        }
    }
);
it.each(["BAR_CLOSED", "BAR_PREVIEW"] as const)(
    "rejects unsafe timestamps from %s",
    async (kind) => {
        await running();
        emitBar(kind, {
            bar_start_ns: "999999999999999999999999999999999999",
            bar_end_ns: "9999999999999999999999999999999999999"
        });
        expect(screen.getByTestId("status")).toHaveTextContent("failed");
        expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
    }
);
it("drops held out-of-order queries across a rapid duration change", async () => {
    const t = await running();
    let resolve!: (value: ReturnType<typeof windowFor>) => void;
    const held = new Promise<ReturnType<typeof windowFor>>((done) => {
        resolve = done;
    });
    vi.mocked(readTemporaryMarketData)
        .mockImplementationOnce(() => held)
        .mockImplementation((_c, _r, q) => Promise.resolve(windowFor(q)));
    await t.user.click(screen.getByRole("button", { name: "1m" }));
    const oldQuery = lastQuery();
    await t.user.click(screen.getByRole("button", { name: "7m" }));
    await waitFor(() => {
        expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });
    const context = screen.getByTestId("context").textContent;
    await act(async () => {
        resolve(windowFor(oldQuery));
        await held;
    });
    expect(screen.getByTestId("context").textContent).toBe(context);
    expect(lastQuery().bar_semantic.formation).toMatchObject({ window_minutes: 7 });
    expect(requiredValue(vi.mocked(readTemporaryMarketData).mock.calls.at(-2))[4]?.aborted).toBe(
        true
    );
});
it("shows honest partial data, stops at no progress, and permits explicit re-entry", async () => {
    let partial = true;
    const t = await running(
        {},
        (_c, _r, q) =>
            Promise.resolve().then(() => {
                const value = windowFor(q);
                if (!partial) return value;
                const missing = value.bars.slice(0, 1000);
                value.bars = value.bars.slice(-1000);
                value.coverage = {
                    status: "PARTIAL",
                    expected_bar_count: 2000,
                    actual_bar_count: 1000,
                    gaps: missing.map((bar) => ({
                        start_ns: bar.bar_start_ns,
                        end_ns: bar.bar_end_ns
                    }))
                };
                return value;
            }),
        "incomplete"
    );
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("count")).toHaveTextContent(/^1000$/);
    partial = false;
    await t.user.click(screen.getByRole("button", { name: "instrument" }));
    await waitFor(() => {
        expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });
    expect(screen.getByTestId("count")).toHaveTextContent(/^2000$/);
});
it("does not auto-select a new latest Revision when the exact source disappears", async () => {
    let missing = false;
    const next = marketDataSource({
        integration_revision_fingerprint: "b".repeat(64),
        type_id: "binance.spot.market_data"
    });
    const t = await running({
        listSources: () => Promise.resolve(missing ? [next] : [marketDataSource()])
    });
    const reads = vi.mocked(readTemporaryMarketData).mock.calls.length;
    missing = true;
    await t.user.click(screen.getByRole("button", { name: "refresh" }));
    await waitFor(() => {
        expect(screen.getByTestId("status")).toHaveTextContent("failed");
    });
    await t.user.click(screen.getByRole("button", { name: "refresh" }));
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(reads);
    expect(screen.getByTestId("count")).toHaveTextContent(/^0$/);
});

it("fails a mismatched plan without reconnecting or changing Source", async () => {
    const t = await running();
    const q = lastQuery(),
        callback = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[1];
    act(() => {
        callback({
            schema_version: 2,
            event: "SUBSCRIBED",
            source_kind: "TEMPORARY_MARKET_DATA",
            authority: "DISPLAY_ONLY",
            publication_status: "NOT_A_RESEARCH_RESULT",
            stream_id: "stream",
            source_id: FIXTURE_SELECTION.source_id,
            instrument_id: q.instrument_id,
            resolution_mode: "PROVIDER_NATIVE",
            resolution_plan_fingerprint: "f".repeat(64),
            cursor_bar_stride_minutes: 15
        });
    });
    expect(screen.getByTestId("realtime")).toHaveTextContent("failed");
    expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
    expect(t.closures[0]).toHaveBeenCalled();
    expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(1);
});
it.each(["merge", "stale", "mismatch"] as const)(
    "holds an older temporary page across a realtime close: %s",
    async (mode) => {
        const t = await running();
        const original = lastQuery();
        let resolve!: (value: ReturnType<typeof windowFor>) => void;
        const held = new Promise<ReturnType<typeof windowFor>>((done) => {
            resolve = done;
        });
        vi.mocked(readTemporaryMarketData)
            .mockImplementationOnce(() => held)
            .mockImplementation((_c, _r, q) => Promise.resolve(windowFor(q)));
        await t.user.click(screen.getByRole("button", { name: "older" }));
        const older = lastQuery();
        const callback = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[1],
            last = requiredValue(windowFor(original).bars.at(-1));
        const width = BigInt(last.bar_end_ns) - BigInt(last.bar_start_ns);
        act(() => {
            callback({
                schema_version: 2,
                event: "BAR_CLOSED",
                source_id: FIXTURE_SELECTION.source_id,
                instrument_id: original.instrument_id,
                bar_semantic: original.bar_semantic,
                bar: {
                    ...last,
                    bar_start_ns: last.bar_end_ns,
                    bar_end_ns: (BigInt(last.bar_end_ns) + width).toString()
                },
                sequence: "123",
                timing: null
            });
        });
        if (mode === "stale") {
            await t.user.click(screen.getByRole("button", { name: "eth" }));
            await waitFor(() => {
                expect(screen.getByTestId("context")).toHaveTextContent("ETHUSDT.TEST");
            });
        }
        const value = windowFor(older);
        if (mode === "mismatch") value.source_selection.environment = "OTHER";
        await act(async () => {
            resolve(value);
            await held;
        });
        if (mode === "merge") expect(screen.getByTestId("count")).toHaveTextContent(/^2241$/);
        else if (mode === "mismatch") {
            expect(screen.getByTestId("older")).toHaveTextContent("failed");
            expect(screen.getByTestId("count")).toHaveTextContent(/^0$/);
            expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
            expect(screen.getByTestId("realtime")).toHaveTextContent("failed");
        } else expect(screen.getByTestId("count")).toHaveTextContent(/^2000$/);
    }
);
it.each(["instrument", "1m"])(
    "permits explicit %s recovery after terminal stream failure",
    async (name) => {
        const t = await running();
        act(() => {
            requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[1]({
                schema_version: 2,
                event: "ERROR",
                code: "SOURCE_UNAVAILABLE",
                detail: "offline"
            });
        });
        expect(screen.getByTestId("realtime")).toHaveTextContent("failed");
        await t.user.click(screen.getByRole("button", { name }));
        await waitFor(() => {
            expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(2);
        });
        expect(screen.getByTestId("count")).toHaveTextContent(/^2000$/);
    }
);
it("preserves signed native timing and rejects timing from another subscription occurrence", async () => {
    await running();
    const req = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[0],
        callback = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[1];
    const subscribed = {
        schema_version: 2 as const,
        event: "SUBSCRIBED" as const,
        source_kind: "TEMPORARY_MARKET_DATA" as const,
        authority: "DISPLAY_ONLY" as const,
        publication_status: "NOT_A_RESEARCH_RESULT" as const,
        stream_id: "current",
        source_id: FIXTURE_SELECTION.source_id,
        instrument_id: req.instrument_id,
        resolution_mode: "PROVIDER_NATIVE" as const,
        resolution_plan_fingerprint: "c".repeat(64),
        cursor_bar_stride_minutes: 15
    };
    act(() => {
        callback(subscribed);
        callback({ schema_version: 2, event: "STATE", state: "READY" });
    });
    const last = requiredValue(windowFor(lastQuery()).bars.at(-1));
    const event = {
        schema_version: 2 as const,
        event: "BAR_PREVIEW" as const,
        source_id: FIXTURE_SELECTION.source_id,
        instrument_id: req.instrument_id,
        bar_semantic: req.bar_semantic,
        bar: {
            ...last,
            bar_start_ns: last.bar_end_ns,
            bar_end_ns: (BigInt(last.bar_end_ns) + 900000000000n).toString(),
            closed: false
        },
        timing: { stream_id: "current", provider_event_ns: "1002", ingress_received_ns: "1000" }
    };
    act(() => {
        callback(event);
    });
    expect(screen.getByTestId("timing")).toHaveTextContent('"receiveDelayNs":"-2"');
    act(() => {
        callback({
            ...event,
            bar: { ...event.bar, close: "11.50" },
            timing: { ...event.timing, stream_id: "other", ingress_received_ns: "9999" }
        });
    });
    expect(screen.getByTestId("timing")).toHaveTextContent('"receiveDelayNs":"-2"');
});
it.each(["HISTORY_REFRESH_REQUIRED", "MARKET_DATA_CONTINUITY_UNPROVEN"])(
    "fully refreshes the temporary window after %s without durable acquisition",
    async (code) => {
        const acquisition = vi.fn(() =>
            Promise.resolve().then(() => {
                throw new Error("durable acquisition forbidden");
            })
        );
        const t = await running({ createAcquisition: acquisition });
        const reads = vi.mocked(readTemporaryMarketData).mock.calls.length;
        act(() => {
            requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[1]({
                schema_version: 2,
                event: "ERROR",
                code,
                detail: code
            });
        });
        await waitFor(() => {
            expect(readTemporaryMarketData).toHaveBeenCalledTimes(reads + 1);
        });
        await waitFor(() => {
            expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(2);
        });
        expect(t.closures[0]).toHaveBeenCalled();
        expect(acquisition).not.toHaveBeenCalled();
    }
);
it.each(["initial", "reload", "older"] as const)(
    "rejects unsafe time projection on %s without mutating a retained chart",
    async (path) => {
        const invalid = (q: MarketDataBarsQuery) => {
            const value = windowFor(q);
            requiredValue(value.bars[0]).bar_start_ns = "999999999999999999999999999999999999";
            return value;
        };
        if (path === "initial") {
            await running({}, (_c, _r, q) => Promise.resolve(invalid(q)), "failed");
            expect(screen.getByTestId("count")).toHaveTextContent(/^0$/);
            return;
        }
        const t = await running();
        vi.mocked(readTemporaryMarketData).mockImplementation((_c, _r, q) =>
            Promise.resolve(invalid(q))
        );
        await t.user.click(screen.getByRole("button", { name: path === "older" ? "older" : "1m" }));
        if (path === "older") {
            await waitFor(() => {
                expect(screen.getByTestId("older")).toHaveTextContent("failed");
            });
            expect(screen.getByTestId("count")).toHaveTextContent(/^2000$/);
        } else {
            await waitFor(() => {
                expect(screen.getByTestId("status")).toHaveTextContent("failed");
            });
            expect(screen.getByTestId("count")).toHaveTextContent(/^0$/);
        }
    }
);
it.each(["transport", "unauthorized", "mismatch"])(
    "retains only trusted partial rows after %s failure while completing a cold window",
    async (kind) => {
        let reads = 0;
        await running(
            {},
            (_c, _r, q) =>
                Promise.resolve().then(() => {
                    if (reads++ > 0)
                        throw new MarketDataWebError(
                            kind === "transport"
                                ? "CHART_STUDY_QUERY_UNAVAILABLE"
                                : kind === "unauthorized"
                                  ? "MARKET_DATA_ACCESS_DENIED"
                                  : "MARKET_DATA_TEMPORARY_RESPONSE_MISMATCH",
                            "failed",
                            kind === "unauthorized" ? 403 : 503
                        );
                    const value = windowFor(q),
                        missing = value.bars.slice(0, 1000);
                    value.bars = value.bars.slice(-1000);
                    value.coverage = {
                        status: "PARTIAL",
                        expected_bar_count: 2000,
                        actual_bar_count: 1000,
                        gaps: missing.map((bar) => ({
                            start_ns: bar.bar_start_ns,
                            end_ns: bar.bar_end_ns
                        }))
                    };
                    return value;
                }),
            "failed"
        );
        expect(screen.getByTestId("count")).toHaveTextContent(
            kind === "transport" ? /^1000$/ : /^0$/
        );
        expect(openTemporaryMarketDataStream).not.toHaveBeenCalled();
        if (kind === "transport")
            expect(screen.getByTestId("fingerprint")).toHaveTextContent("a".repeat(64));
    }
);
it.each([
    "MARKET_DATA_IDENTITY_CONFLICT",
    "MARKET_DATA_PROVENANCE_CONFLICT",
    "MARKET_DATA_SOURCE_CATALOG_CORRUPT"
])(
    "withdraws old calculation input on %s rather than retaining a displayable numeric proof",
    async (code) => {
        const t = await running();
        act(() => {
            requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[1]({
                schema_version: 2,
                event: "ERROR",
                code,
                detail: code
            });
        });
        expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
        expect(screen.getByTestId("status")).toHaveTextContent("failed");
        expect(t.closures[0]).toHaveBeenCalled();
        expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(1);
    }
);
it.each(["MALFORMED_JSON", "CONTRACT_ERROR"] as const)(
    "withdraws old numeric input after a terminal %s",
    async (failure) => {
        const t = await running();
        act(() => {
            requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls[0])[2](failure);
        });
        expect(screen.getByTestId("fingerprint")).toHaveTextContent("none");
        expect(screen.getByTestId("status")).toHaveTextContent("failed");
        expect(t.closures[0]).toHaveBeenCalled();
    }
);
it("deduplicates pending older reads and stops automatic no-progress paging while retaining an explicit retry", async () => {
    const t = await running();
    let finish!: (window: ReturnType<typeof windowFor>) => void;
    vi.mocked(readTemporaryMarketData).mockImplementationOnce(
        () =>
            new Promise((resolve) => {
                finish = resolve;
            })
    );
    const before = vi.mocked(readTemporaryMarketData).mock.calls.length;
    await t.user.click(screen.getByRole("button", { name: "auto-older" }));
    await t.user.click(screen.getByRole("button", { name: "auto-older" }));
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(before + 1);
    const noProgress = windowFor(lastQuery());
    noProgress.bars = [];
    noProgress.coverage = {
        ...noProgress.coverage,
        status: "PARTIAL",
        actual_bar_count: 0,
        gaps: [{ start_ns: noProgress.resolved_start_ns, end_ns: noProgress.resolved_end_ns }]
    };
    await act(() =>
        Promise.resolve().then(() => {
            finish(noProgress);
        })
    );
    await t.user.click(screen.getByRole("button", { name: "auto-older" }));
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(before + 1);
    await t.user.click(screen.getByRole("button", { name: "older" }));
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(before + 2);
});
it("stops after the bounded reconnect delays and permits an explicit same-context recovery", async () => {
    const t = await running();
    vi.useFakeTimers();
    act(() => {
        requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[2]();
    });
    for (const [index, delay] of STREAM_RECONNECT_DELAYS_MS.entries()) {
        await act(async () => vi.advanceTimersByTimeAsync(delay));
        expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(index + 2);
        act(() => {
            requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[2]();
        });
    }
    expect(screen.getByTestId("realtime")).toHaveTextContent("failed");
    expect(screen.getByTestId("count")).toHaveTextContent(/^2000$/);
    expect(vi.getTimerCount()).toBe(0);
    vi.useRealTimers();
    await t.user.click(screen.getByRole("button", { name: "1m" }));
    await waitFor(() => {
        expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(
            STREAM_RECONNECT_DELAYS_MS.length + 2
        );
    });
});

it("retries unavailable Provider recovery within the frozen burst and ignores its late disconnect", async () => {
    const t = await running();
    vi.useFakeTimers();
    act(() => {
        requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[1]({
            schema_version: 2,
            event: "STATE",
            state: "READY"
        });
    });
    const unavailable = () => {
        const call = requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1));
        act(() => {
            call[1]({ schema_version: 2, event: "STATE", state: "RECOVERING" });
            call[1]({
                schema_version: 2,
                event: "ERROR",
                code: "MARKET_DATA_SOURCE_UNAVAILABLE",
                detail: "Provider recovery unavailable"
            });
            call[2]();
        });
    };
    unavailable();
    expect(screen.getByTestId("realtime")).toHaveTextContent("degraded");
    for (const [index, delay] of [250, 500, 1000, 2000, 4000].entries()) {
        await act(async () => vi.advanceTimersByTimeAsync(delay));
        expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(index + 2);
        expect(lastQuery().anchor_kind).toBe("BEFORE_TIME");
        expect(lastQuery().before_ns).toBe("1767225600000000000");
        unavailable();
    }
    expect(screen.getByTestId("realtime")).toHaveTextContent("failed");
    expect(screen.getByTestId("count")).toHaveTextContent(/^2000$/);
    expect(vi.getTimerCount()).toBe(0);
    t.view.unmount();
});

it.each(["HISTORY_REFRESH_REQUIRED", "MARKET_DATA_CONTINUITY_UNPROVEN"])(
    "stops repeated full refresh after %s until an explicit reread",
    async (code) => {
        const t = await running();
        const reads = vi.mocked(readTemporaryMarketData).mock.calls.length;
        const fault = () => {
            act(() => {
                requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[1]({
                    schema_version: 2,
                    event: "ERROR",
                    code,
                    detail: code
                });
            });
        };
        fault();
        await waitFor(() => {
            expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(2);
        });
        expect(screen.getByTestId("fingerprint")).not.toHaveTextContent("none");
        fault();
        await waitFor(() => {
            expect(screen.getByTestId("realtime")).toHaveTextContent("failed");
        });
        expect(screen.getByTestId("fingerprint")).toHaveTextContent(/^none$/);
        expect(readTemporaryMarketData).toHaveBeenCalledTimes(reads + 1);
        expect(screen.getByTestId("latest")).toHaveTextContent("11.00");
        await t.user.click(screen.getByRole("button", { name: "15m" }));
        await waitFor(() => {
            expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(3);
        });
        expect(readTemporaryMarketData).toHaveBeenCalledTimes(reads + 2);
        fault();
        await waitFor(() => {
            expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(4);
        });
    }
);
