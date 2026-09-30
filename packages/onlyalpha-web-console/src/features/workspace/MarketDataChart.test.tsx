import { act, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { AppProviders } from "../../app/providers";
import { MarketDataWebError } from "../../api/marketData/client";
import type { MarketDataApiClient } from "../../api/marketData/client";
import {
    fixedDurationMinutes,
    marketDataBarSemantic,
    type MarketDataAcquisition,
    type MarketDataBars
} from "../../api/marketData/model";
import { buildPlaceholderBars } from "../../charts/lightweight/placeholderBars";
import { PriceChart } from "../../charts/lightweight/PriceChart";
import {
    dataSourceSummary,
    dataSourceType,
    integrationClient,
    operationalStatus
} from "../../test/integrationClient";
import {
    incompleteBars,
    marketDataAcquisition,
    marketDataBars,
    marketDataBarsForQuery,
    marketDataClient,
    marketDataSource,
    marketDataInstrument
} from "../../test/marketDataClient";
import { researchClient } from "../../test/researchClient";
import { onlyBarsToCandles } from "./useMarketDataChart";
import { WorkspacePage } from "./WorkspacePage";

class NoopResizeObserver {
    observe(): void {
        return undefined;
    }
    unobserve(): void {
        return undefined;
    }
    disconnect(): void {
        return undefined;
    }
}

/**
 * Only the rendering library is mocked. The real `PriceChart`, the real chart-mode
 * decision and the real placeholder fallback all execute, so a synthetic price cannot
 * hide behind the mock.
 */
const chartMocks = vi.hoisted(() => {
    const range = { value: { from: 30, to: 60 } as { from: number; to: number } | null };
    const visible = {
        handler: null as ((range: { from: number; to: number } | null) => void) | null
    };
    const candles = {
        setData: vi.fn<(bars: readonly unknown[]) => void>(),
        update: vi.fn<(bar: unknown) => void>()
    };
    const overlays = {
        setData: vi.fn<(points: readonly unknown[]) => void>(),
        update: vi.fn<(bar: unknown) => void>()
    };
    const addSeries = vi.fn<(definition: string) => typeof candles>((definition) =>
        definition === "Candlestick" ? candles : overlays
    );
    const timeScale = {
        applyOptions: vi.fn(),
        getVisibleLogicalRange: vi.fn(() => range.value),
        setVisibleLogicalRange: vi.fn((next: { from: number; to: number }) => {
            range.value = next;
            visible.handler?.(next);
        }),
        subscribeVisibleLogicalRangeChange: vi.fn(
            (handler: (next: { from: number; to: number } | null) => void) => {
                visible.handler = handler;
            }
        ),
        unsubscribeVisibleLogicalRangeChange: vi.fn(
            (handler: (next: { from: number; to: number } | null) => void) => {
                if (visible.handler === handler) visible.handler = null;
            }
        )
    };
    const created = {
        addSeries,
        timeScale: () => timeScale,
        remove: vi.fn()
    };
    return {
        candles,
        overlays,
        addSeries,
        range,
        visible,
        timeScale,
        createChart: vi.fn<() => typeof created>(() => created)
    };
});

vi.mock("lightweight-charts", () => ({
    CandlestickSeries: "Candlestick",
    LineSeries: "Line",
    ColorType: { Solid: "solid" },
    TickMarkType: { Time: 3, TimeWithSeconds: 4 },
    createChart: chartMocks.createChart
}));

vi.stubGlobal("ResizeObserver", NoopResizeObserver);

function renderedPrices(): readonly number[] | null {
    const bars = chartMocks.candles.setData.mock.calls.at(-1)?.[0];
    if (bars === undefined) return null;
    return (bars as readonly { readonly close: number }[]).map((bar) => bar.close);
}

function configuredSources() {
    return integrationClient({
        listTypes: () => Promise.resolve([dataSourceType()]),
        listDataSources: () => Promise.resolve([dataSourceSummary()]),
        getOperationalStatus: () => Promise.resolve(operationalStatus({ status: "READY" }))
    });
}

function renderWorkspace(client: MarketDataApiClient) {
    return render(
        <AppProviders
            client={researchClient()}
            integrationClient={configuredSources()}
            marketDataClient={client}
        >
            <WorkspacePage />
        </AppProviders>
    );
}

async function selectSource(user: ReturnType<typeof userEvent.setup>) {
    await screen.findByRole("option", { name: /Fixture Source/ });
    await user.selectOptions(
        screen.getByRole("combobox", { name: "数据源" }),
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    );
}

async function selectBtcInstrument(user: ReturnType<typeof userEvent.setup>) {
    const search = screen.getByRole("searchbox", { name: "搜索标的" });
    await user.type(search, "BTC{Enter}");
    await user.click(await screen.findByRole("button", { name: /BTCUSDT\.TEST/ }));
}

beforeEach(() => {
    chartMocks.candles.setData.mockClear();
    chartMocks.candles.update.mockClear();
    chartMocks.overlays.setData.mockClear();
    chartMocks.timeScale.getVisibleLogicalRange.mockClear();
    chartMocks.timeScale.setVisibleLogicalRange.mockClear();
    chartMocks.timeScale.subscribeVisibleLogicalRangeChange.mockClear();
    chartMocks.timeScale.unsubscribeVisibleLogicalRangeChange.mockClear();
    chartMocks.range.value = { from: 30, to: 60 };
    chartMocks.visible.handler = null;
});

afterEach(() => {
    vi.restoreAllMocks();
});

it("renders canonical Product bars without browser range planning", () => {
    expect(onlyBarsToCandles(marketDataBars().bars)).toEqual([
        { time: 1_767_225_600, open: 100, high: 102, low: 99, close: 101 },
        { time: 1_767_225_660, open: 101, high: 103, low: 100, close: 102.5 }
    ]);
});

it("updates realtime candles without recreating the chart", () => {
    const historical = onlyBarsToCandles(marketDataBars().bars);
    const view = render(
        <PriceChart
            barSemantic={marketDataBarSemantic(7)}
            mode="real"
            bars={historical}
            contextKey="revision-a"
        />
    );
    const created = chartMocks.createChart.mock.calls.length;
    const second = historical.at(1);
    if (second === undefined) throw new Error("fixture requires two bars");
    const preview = { ...second, close: 103 };

    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(7)}
            mode="real"
            bars={historical}
            contextKey="revision-a"
            liveBar={preview}
        />
    );

    expect(chartMocks.createChart).toHaveBeenCalledTimes(created);
    expect(chartMocks.candles.update).toHaveBeenLastCalledWith(preview);
    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(37)}
            mode="real"
            bars={historical.slice(1)}
            contextKey="revision-b"
        />
    );
    expect(chartMocks.candles.setData).toHaveBeenLastCalledWith(historical.slice(1));
    expect(chartMocks.createChart).toHaveBeenCalledTimes(created);
});

it("subscribes to the visible range and unsubscribes the same handler", () => {
    const view = render(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            mode="real"
            bars={onlyBarsToCandles(marketDataBars().bars)}
            contextKey="context-a"
        />
    );
    const handler = chartMocks.visible.handler;

    expect(chartMocks.timeScale.subscribeVisibleLogicalRangeChange).toHaveBeenCalledOnce();
    expect(handler).not.toBeNull();
    view.unmount();
    expect(chartMocks.timeScale.unsubscribeVisibleLogicalRangeChange).toHaveBeenCalledWith(handler);
});

it("requests older history once per left-edge threshold crossing without recreating the chart", () => {
    const onNearLeftEdge = vi.fn();
    render(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            mode="real"
            bars={onlyBarsToCandles(marketDataBars().bars)}
            contextKey="context-a"
            onNearLeftEdge={onNearLeftEdge}
        />
    );
    const created = chartMocks.createChart.mock.calls.length;
    const handler = chartMocks.visible.handler;
    if (handler === null) throw new Error("visible-range handler missing");

    handler({ from: 24, to: 80 });
    expect(onNearLeftEdge).not.toHaveBeenCalled();
    handler({ from: 25, to: 81 });
    handler({ from: 24, to: 80 });
    handler({ from: 12, to: 68 });
    expect(onNearLeftEdge).toHaveBeenCalledOnce();
    handler({ from: 25, to: 81 });
    handler({ from: 24, to: 80 });

    expect(onNearLeftEdge).toHaveBeenCalledTimes(2);
    expect(chartMocks.createChart).toHaveBeenCalledTimes(created);
});

it("initializes the first non-empty history once even after an empty context publication", () => {
    const callback = vi.fn();
    const history = onlyBarsToCandles(marketDataBars().bars);
    const chart = (key: string, bars: typeof history) => (
        <PriceChart
            mode="real"
            barSemantic={marketDataBarSemantic(1)}
            bars={bars}
            contextKey={key}
            onNearLeftEdge={callback}
        />
    );
    const view = render(chart("context-a", []));
    expect(chartMocks.timeScale.setVisibleLogicalRange).not.toHaveBeenCalled();
    view.rerender(chart("context-a", history));
    expect(chartMocks.timeScale.setVisibleLogicalRange).toHaveBeenCalledExactlyOnceWith({
        from: 0,
        to: 6
    });
    expect(callback).not.toHaveBeenCalled();
    view.rerender(chart("context-a", [...history]));
    expect(chartMocks.timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);
    chartMocks.visible.handler?.({ from: 25, to: 30 });
    view.rerender(chart("context-b", []));
    chartMocks.visible.handler?.({ from: 0, to: 5 });
    view.rerender(chart("context-b", history));
    expect(chartMocks.timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(2);
    expect(callback).not.toHaveBeenCalled();
});

it("replays effects with one current range handler and no mount history request", () => {
    const oldCallback = vi.fn();
    const currentCallback = vi.fn();
    const history = onlyBarsToCandles(marketDataBars().bars);
    const chart = (callback: () => void) => (
        <StrictMode>
            <PriceChart
                mode="real"
                barSemantic={marketDataBarSemantic(1)}
                bars={history}
                contextKey="context-a"
                onNearLeftEdge={callback}
            />
        </StrictMode>
    );
    const view = render(chart(oldCallback));
    expect(oldCallback).not.toHaveBeenCalled();
    expect(
        chartMocks.timeScale.subscribeVisibleLogicalRangeChange.mock.calls.length -
            chartMocks.timeScale.unsubscribeVisibleLogicalRangeChange.mock.calls.length
    ).toBe(1);
    view.rerender(chart(currentCallback));
    chartMocks.visible.handler?.({ from: 25, to: 30 });
    chartMocks.visible.handler?.({ from: 24, to: 30 });
    expect(currentCallback).toHaveBeenCalledOnce();
    expect(oldCallback).not.toHaveBeenCalled();
    view.unmount();
    expect(chartMocks.visible.handler).toBeNull();
});

it.each([
    ["mixed prepend and append", [0, 1, 2, 3], 1],
    ["two prepends", [-1, 0, 1, 2], 2],
    ["right append only", [1, 2, 3], 0],
    ["missing prior identity", [0, 2, 3], 0],
    ["reordered prior sequence", [0, 2, 1, 3], 0]
] as const)("preserves the viewport using only proven left offset: %s", (_name, times, offset) => {
    const first = onlyBarsToCandles(marketDataBars().bars)[0];
    if (first === undefined) throw new Error("fixture requires a first Bar");
    const candle = (index: number) => ({
        ...first,
        time: (first.time + index * 60) as typeof first.time
    });
    const prior = [candle(1), candle(2)];
    const view = render(
        <PriceChart
            mode="real"
            barSemantic={marketDataBarSemantic(1)}
            bars={prior}
            contextKey="context-a"
        />
    );
    const created = chartMocks.createChart.mock.calls.length;
    chartMocks.range.value = { from: 5, to: 10 };
    chartMocks.timeScale.setVisibleLogicalRange.mockClear();
    view.rerender(
        <PriceChart
            mode="real"
            barSemantic={marketDataBarSemantic(1)}
            bars={times.map(candle)}
            contextKey="context-a"
        />
    );
    if (offset > 0)
        expect(chartMocks.timeScale.setVisibleLogicalRange).toHaveBeenCalledExactlyOnceWith({
            from: 5 + offset,
            to: 10 + offset
        });
    else expect(chartMocks.timeScale.setVisibleLogicalRange).not.toHaveBeenCalled();
    expect(chartMocks.createChart).toHaveBeenCalledTimes(created);
});

it("derives the visible anchor from renderer Bars and preserves it after a mixed prepend", () => {
    const prior = onlyBarsToCandles(marketDataBars().bars);
    const first = prior[0];
    const last = prior[1];
    if (first === undefined || last === undefined) throw new Error("fixture requires two Bars");
    const view = render(
        <PriceChart
            mode="real"
            barSemantic={marketDataBarSemantic(1)}
            bars={prior}
            contextKey="context-a"
        />
    );
    act(() => {
        chartMocks.range.value = { from: 0.2, to: 1.2 };
        chartMocks.visible.handler?.(chartMocks.range.value);
    });
    const chart = screen.getByTestId("price-chart");
    expect(chart).toHaveAttribute("data-visible-anchor-time", String(last.time));
    view.rerender(
        <PriceChart
            mode="real"
            barSemantic={marketDataBarSemantic(1)}
            bars={[
                { ...first, time: (first.time - 60) as typeof first.time },
                ...prior,
                { ...last, time: (last.time + 60) as typeof last.time }
            ]}
            contextKey="context-a"
        />
    );
    expect(chart).toHaveAttribute("data-visible-anchor-time", String(last.time));
    expect(chart).toHaveAttribute("data-visible-range-from", "1.2");
});

it("shifts the logical range by the strict prepend count", () => {
    const historical = onlyBarsToCandles(marketDataBars().bars);
    const first = historical[0];
    if (first === undefined) throw new Error("fixture requires a first Bar");
    const earlier = { ...first, time: (first.time - 60) as typeof first.time };
    const view = render(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            mode="real"
            bars={historical}
            contextKey="context-a"
        />
    );
    chartMocks.timeScale.setVisibleLogicalRange.mockClear();
    chartMocks.range.value = { from: 5, to: 10 };

    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            mode="real"
            bars={[earlier, ...historical]}
            contextKey="context-a"
        />
    );

    expect(chartMocks.timeScale.setVisibleLogicalRange).toHaveBeenLastCalledWith({
        from: 6,
        to: 11
    });
});

it("resets a changed context to the recent range", () => {
    const historical = onlyBarsToCandles(marketDataBars().bars);
    const view = render(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            mode="real"
            bars={historical}
            contextKey="context-a"
        />
    );
    chartMocks.timeScale.setVisibleLogicalRange.mockClear();

    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            mode="real"
            bars={historical}
            contextKey="context-b"
        />
    );

    expect(chartMocks.timeScale.setVisibleLogicalRange).toHaveBeenLastCalledWith({
        from: 0,
        to: historical.length + 4
    });
});

it("ignores realtime bars older than the history or latest realtime candle", () => {
    const historical = onlyBarsToCandles(marketDataBars().bars);
    const first = historical[0];
    const last = historical[1];
    if (first === undefined || last === undefined) throw new Error("fixture requires two bars");
    const specification = marketDataBarSemantic(1);
    const view = render(
        <PriceChart
            mode="real"
            barSemantic={specification}
            bars={historical}
            contextKey="revision-a"
        />
    );

    view.rerender(
        <PriceChart
            mode="real"
            barSemantic={specification}
            bars={historical}
            contextKey="revision-a"
            liveBar={{ ...first, close: 999 }}
        />
    );
    expect(chartMocks.candles.update).not.toHaveBeenCalled();

    const next = { ...last, time: (last.time + 60) as typeof last.time, close: 103 };
    view.rerender(
        <PriceChart
            mode="real"
            barSemantic={specification}
            bars={historical}
            contextKey="revision-a"
            liveBar={next}
        />
    );
    expect(chartMocks.candles.update).toHaveBeenCalledExactlyOnceWith(next);

    view.rerender(
        <PriceChart
            mode="real"
            barSemantic={specification}
            bars={historical}
            contextKey="revision-a"
            liveBar={{ ...last, close: 999 }}
        />
    );
    expect(chartMocks.candles.update).toHaveBeenCalledTimes(1);
});

it("keeps the deterministic placeholder series only in the synthetic W0 context", async () => {
    renderWorkspace(marketDataClient({ listSources: () => Promise.resolve([]) }));

    await waitFor(() => {
        expect(renderedPrices()).toEqual(buildPlaceholderBars("1D").map((bar) => bar.close));
    });
    expect(screen.getByTestId("market-data-status")).toHaveTextContent(/synthetic 占位/);
    expect(screen.queryByTestId("real-overlay-note")).not.toBeInTheDocument();
});

it("never renders a synthetic price once a real market data source is selected", async () => {
    const user = userEvent.setup();
    const barQueries: ((bars: MarketDataBars) => void)[] = [];
    const acquisitions: ((value: MarketDataAcquisition) => void)[] = [];
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: () =>
            new Promise<MarketDataBars>((resolve) => {
                barQueries.push(resolve);
            }),
        createAcquisition: () =>
            new Promise<MarketDataAcquisition>((resolve) => {
                acquisitions.push(resolve);
            })
    });
    renderWorkspace(client);

    await selectSource(user);
    await selectBtcInstrument(user);

    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveAttribute("data-status", "loading");
    });
    expect(renderedPrices()).toEqual([]);

    barQueries[0]?.(incompleteBars());
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveAttribute(
            "data-status",
            "acquiring"
        );
    });
    expect(renderedPrices()).toEqual([]);

    acquisitions[0]?.(
        marketDataAcquisition({
            status: "FAILED",
            coverage: incompleteBars().coverage,
            revision_id: null,
            revision_fingerprint: null,
            seal_id: null,
            failure_detail: "OnlyBinanceError:BINANCE_HTTP_ERROR"
        })
    );
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(/历史行情同步失败/);
    });
    expect(chartMocks.candles.setData.mock.calls.at(-1)?.[0]).toEqual([]);
});

it("renders only canonical Product bars in real READY and disables synthetic overlays", async () => {
    const user = userEvent.setup();
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: (_reference, query) => Promise.resolve(marketDataBarsForQuery(query))
    });
    renderWorkspace(client);

    await selectSource(user);
    await selectBtcInstrument(user);

    await waitFor(() => {
        expect(screen.getByTestId("market-data-source-tag")).toHaveTextContent("real · DB");
    });
    expect(renderedPrices()).toEqual([101, 102.5]);
    expect(chartMocks.overlays.setData).not.toHaveBeenCalled();
    expect(screen.getByTestId("real-overlay-note")).toHaveTextContent(
        "真实指标/因子将在 W3 接入 Product API"
    );
    expect(screen.getByRole("button", { name: /指标/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /因子/ })).toBeDisabled();
    expect(screen.getByTestId("market-data-status")).toHaveTextContent(
        /test\.market_data\.live · 历史投影 888888888888 · ● 连接中/
    );
    expect(screen.getByTestId("market-data-status")).toHaveAttribute("data-loaded-bar-count", "2");
    expect(screen.getByTestId("market-data-status")).toHaveAttribute(
        "data-older-history-status",
        "idle"
    );
});

it("accepts a custom seven-minute specification through the real Product query", async () => {
    const user = userEvent.setup();
    const steps: number[] = [];
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: (_reference, query) => {
            steps.push(fixedDurationMinutes(query.bar_semantic));
            return Promise.resolve(
                marketDataBarsForQuery(query, {
                    bar_semantic: query.bar_semantic
                })
            );
        }
    });
    renderWorkspace(client);
    await selectSource(user);
    await selectBtcInstrument(user);
    await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "custom");
    await user.clear(screen.getByRole("spinbutton", { name: "自定义周期分钟数" }));
    await user.type(screen.getByRole("spinbutton", { name: "自定义周期分钟数" }), "7");
    await user.click(screen.getByRole("button", { name: "应用" }));
    await waitFor(() => {
        expect(steps).toContain(7);
    });
    expect(screen.getByRole("combobox", { name: "时间周期" })).toHaveValue("custom");
});

it("requests an explicit acquisition for incomplete coverage and then renders database bars", async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: (_reference, query) => {
            calls.push("bars");
            return Promise.resolve(
                marketDataBarsForQuery(query, calls.length === 1 ? incompleteBars() : {})
            );
        },
        createAcquisition: () => {
            calls.push("acquisition");
            return Promise.resolve(marketDataAcquisition());
        }
    });
    renderWorkspace(client);

    await selectSource(user);
    await selectBtcInstrument(user);

    await waitFor(() => {
        expect(calls).toEqual(["bars", "acquisition", "bars"]);
    });
    await waitFor(() => {
        expect(screen.getByTestId("market-data-source-tag")).toHaveTextContent("real · DB");
    });
    expect(renderedPrices()).toEqual([101, 102.5]);
});

it("submits multiple server-planned acquisition ranges in order", async () => {
    const user = userEvent.setup();
    const ranges = [
        { start_ns: "1767225600000000000", end_ns: "1767225660000000000" },
        { start_ns: "1767225660000000000", end_ns: "1767225720000000000" }
    ];
    const submitted: string[] = [];
    let queries = 0;
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: (_reference, query) => {
            queries += 1;
            return Promise.resolve(
                queries === 1
                    ? incompleteBars({
                          coverage: {
                              ...incompleteBars().coverage,
                              gaps: ranges,
                              planned_acquisition_ranges: ranges
                          }
                      })
                    : marketDataBarsForQuery(query)
            );
        },
        createAcquisition: (_reference, query) => {
            submitted.push(`${query.start_ns}-${query.end_ns}`);
            return Promise.resolve(marketDataAcquisition());
        }
    });
    renderWorkspace(client);

    await selectSource(user);
    await selectBtcInstrument(user);

    await waitFor(() => {
        expect(submitted).toEqual(ranges.map((range) => `${range.start_ns}-${range.end_ns}`));
    });
    expect(queries).toBe(2);
});

it("re-enters the command after owner loss and re-queries the frozen window", async () => {
    const setTimeout = window.setTimeout.bind(window);
    vi.spyOn(window, "setTimeout").mockImplementation((handler: TimerHandler, timeout?: number) => {
        if (timeout === 250 && typeof handler === "function") {
            queueMicrotask(handler as () => void);
            return 1;
        }
        return setTimeout(handler, timeout);
    });
    const user = userEvent.setup();
    const calls: string[] = [];
    const queries: Parameters<MarketDataApiClient["queryBars"]>[1][] = [];
    let creates = 0;
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: (_reference, query) => {
            queries.push(query);
            calls.push("bars");
            return Promise.resolve(
                calls.filter((item) => item === "bars").length === 1
                    ? incompleteBars()
                    : marketDataBarsForQuery(query)
            );
        },
        createAcquisition: () => {
            creates += 1;
            calls.push(creates === 1 ? "create:RUNNING" : "create:COMPLETE");
            return Promise.resolve(
                marketDataAcquisition({ status: creates === 1 ? "RUNNING" : "COMPLETE" })
            );
        },
        getAcquisition: () => {
            calls.push("status:PENDING");
            return Promise.resolve(marketDataAcquisition({ status: "PENDING" }));
        }
    });
    renderWorkspace(client);

    await selectSource(user);
    await selectBtcInstrument(user);

    await waitFor(() => {
        expect(calls).toEqual([
            "bars",
            "create:RUNNING",
            "status:PENDING",
            "create:COMPLETE",
            "bars"
        ]);
    });
    expect(queries).toHaveLength(2);
    const initial = queries[0];
    if (initial === undefined) throw new Error("initial Market Data query was not recorded");
    expect(queries[1]).toMatchObject({
        anchor_kind: "BEFORE_TIME",
        before_ns: incompleteBars().resolved_end_ns,
        target_bar_count: initial.target_bar_count,
        bar_semantic: initial.bar_semantic
    });
    expect(renderedPrices()).toEqual([101, 102.5]);
});

it("surfaces an unavailable market data backend without fake bars", async () => {
    const user = userEvent.setup();
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: () =>
            Promise.reject(
                new MarketDataWebError("TRANSPORT_ERROR", "Market Data API is unavailable")
            )
    });
    renderWorkspace(client);

    await selectSource(user);
    await selectBtcInstrument(user);

    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(/TRANSPORT_ERROR/);
    });
    expect(renderedPrices()).toEqual([]);
});

it("offers only the sources the Market Data Product reports as eligible", async () => {
    renderWorkspace(
        marketDataClient({
            listSources: () =>
                Promise.resolve([
                    marketDataSource(),
                    marketDataSource({
                        integration_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                        display_name: "Testnet Source",
                        source_id: "test.market_data.spot_testnet",
                        environment: "SPOT_TESTNET"
                    })
                ])
        })
    );

    await screen.findByRole("option", { name: /Fixture Source/ });
    const selector = screen.getByRole("combobox", { name: "数据源" });
    expect(
        within(selector)
            .getAllByRole("option")
            .map((item) => item.textContent)
    ).toEqual([
        "未选择数据源",
        "Fixture Source · test.market_data",
        "Testnet Source · test.market_data"
    ]);
});
