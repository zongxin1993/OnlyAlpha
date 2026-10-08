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
    type MarketDataBars,
    type MarketDataSource
} from "../../api/marketData/model";
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
import {
    projectMarketDataBar,
    toCandlestick,
    type MarketDataChartBarProjection
} from "../../charts/lightweight/marketDataChartProjection";
const projectBars = (bars: MarketDataBars["bars"]) => bars.map(projectMarketDataBar);
const renderedBar = (bar: MarketDataChartBarProjection) => ({
    ...toCandlestick(bar),
    barStartNs: bar.barStartNs
});
const shiftBar = (bar: MarketDataChartBarProjection, seconds: number) => ({
    ...bar,
    time: (bar.time + seconds) as typeof bar.time,
    barStartNs: (BigInt(bar.barStartNs) + BigInt(seconds) * 1_000_000_000n).toString(),
    barEndNs: (BigInt(bar.barEndNs) + BigInt(seconds) * 1_000_000_000n).toString()
});
import { WorkspacePage } from "./WorkspacePage";
import type { MarketDataStreamEvent } from "../../api/marketData/stream";

const streams = vi.hoisted(() => ({
    callbacks: [] as ((event: MarketDataStreamEvent) => void)[],
    requests: [] as unknown[]
}));
vi.mock("../../api/marketData/stream", () => ({
    openMarketDataStream: (request: unknown, callback: (event: MarketDataStreamEvent) => void) => {
        streams.requests.push(request);
        streams.callbacks.push(callback);
        return () => undefined;
    }
}));

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
 * Only the rendering library is mocked. The shipping PriceChart executes, so
 * invented candle/overlay values cannot hide behind a component mock.
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
        removeSeries: vi.fn(),
        subscribeCrosshairMove: vi.fn<(handler: unknown) => void>(),
        unsubscribeCrosshairMove: vi.fn<(handler: unknown) => void>(),
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
        createChart: vi.fn<() => typeof created>(() => created),
        created
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
    // These existing manual-context regressions explicitly request their 1m fixture.
    await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "1");
}

async function selectBtcInstrument(user: ReturnType<typeof userEvent.setup>) {
    const search = screen.getByRole("searchbox", { name: "搜索标的" });
    await user.type(search, "BTC{Enter}");
    await user.click(await screen.findByRole("button", { name: /BTCUSDT\.TEST/ }));
}

beforeEach(() => {
    streams.callbacks.length = 0;
    streams.requests.length = 0;
    chartMocks.candles.setData.mockClear();
    chartMocks.candles.update.mockClear();
    chartMocks.overlays.setData.mockClear();
    chartMocks.timeScale.getVisibleLogicalRange.mockClear();
    chartMocks.timeScale.setVisibleLogicalRange.mockClear();
    chartMocks.timeScale.subscribeVisibleLogicalRangeChange.mockClear();
    chartMocks.timeScale.unsubscribeVisibleLogicalRangeChange.mockClear();
    chartMocks.range.value = { from: 30, to: 60 };
    chartMocks.visible.handler = null;
    chartMocks.created.removeSeries.mockClear();
    chartMocks.created.subscribeCrosshairMove.mockClear();
    chartMocks.created.unsubscribeCrosshairMove.mockClear();
});

afterEach(() => {
    vi.restoreAllMocks();
});

const binanceSource = (overrides: Partial<MarketDataSource> = {}) =>
    marketDataSource({
        type_id: "binance.spot.market_data",
        source_id: "server-reported-binance-live",
        environment: "GLOBAL",
        integration_revision_fingerprint: "b".repeat(64),
        ...overrides
    });
const binanceInstrument = () =>
    marketDataInstrument({ instrument_id: "BTCUSDT.BINANCE", venue: "BINANCE" });
const sourceSelection = (source: MarketDataSource) => ({
    integration_id: source.integration_id,
    integration_revision_fingerprint: source.integration_revision_fingerprint,
    type_id: source.type_id,
    source_id: source.source_id,
    environment: source.environment
});

it("defaults to the exact server Binance GLOBAL source and BTCUSDT with first history and stream at 15m", async () => {
    const source = binanceSource();
    const instrument = binanceInstrument();
    const reference = {
        integration_id: source.integration_id,
        integration_revision_fingerprint: source.integration_revision_fingerprint,
        expected_type_id: source.type_id
    };
    const listInstruments = vi.fn<MarketDataApiClient["listInstruments"]>(() =>
        Promise.resolve([instrument])
    );
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_reference, query) =>
        Promise.resolve(
            marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
        )
    );
    renderWorkspace(
        marketDataClient({
            listSources: () =>
                Promise.resolve([marketDataSource({ integration_id: "other-provider" }), source]),
            listInstruments,
            queryBars
        })
    );
    await waitFor(() => {
        expect(streams.requests).toHaveLength(1);
    });
    expect(listInstruments).toHaveBeenCalledWith(reference, "BTCUSDT", expect.any(AbortSignal));
    expect(queryBars).toHaveBeenCalledExactlyOnceWith(reference, {
        instrument_id: instrument.instrument_id,
        anchor_kind: "LATEST_CLOSED",
        target_bar_count: 1440,
        bar_semantic: marketDataBarSemantic(15)
    });
    expect(streams.requests[0]).toMatchObject({
        source_reference: reference,
        instrument_id: instrument.instrument_id,
        bar_semantic: marketDataBarSemantic(15)
    });
    expect(screen.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
    expect(renderedPrices()).toEqual([101, 102.5]);
    expect(chartMocks.overlays.setData).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "指标" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "因子" })).toBeDisabled();
});

it.each([
    ["empty", []],
    ["other provider", [marketDataSource()]],
    ["US", [binanceSource({ environment: "US" })]],
    ["testnet", [binanceSource({ environment: "SPOT_TESTNET" })]],
    ["TEST", [binanceSource({ environment: "TEST" })]],
    ["non-contract LIVE label", [binanceSource({ environment: "LIVE" })]]
] as const)(
    "defaults to an honest setup state without any default substitute: %s",
    async (_name, sources) => {
        const listInstruments = vi.fn<MarketDataApiClient["listInstruments"]>(() =>
            Promise.resolve([])
        );
        const queryBars = vi.fn<MarketDataApiClient["queryBars"]>();
        renderWorkspace(
            marketDataClient({
                listSources: () => Promise.resolve(sources),
                listInstruments,
                queryBars
            })
        );
        await waitFor(() => {
            expect(screen.getByTestId("market-data-status")).toHaveTextContent(
                "未配置可用的 Binance Spot 公共行情数据源（GLOBAL）"
            );
        });
        expect(screen.getByRole("combobox", { name: "数据源" })).toHaveValue("");
        expect(listInstruments).not.toHaveBeenCalled();
        expect(queryBars).not.toHaveBeenCalled();
        expect(streams.requests).toHaveLength(0);
        expect(renderedPrices()).toEqual([]);
        expect(screen.getByRole("button", { name: "管理数据源" })).toBeInTheDocument();
        expect(screen.queryByText(/synthetic/)).not.toBeInTheDocument();
    }
);

it("defaults to explicit source choice for multiple GLOBAL sources, then bootstraps only the manually chosen source", async () => {
    const sources = [
        binanceSource(),
        binanceSource({
            integration_id: "second-source",
            source_id: "second-market-source",
            integration_revision_fingerprint: "c".repeat(64)
        })
    ];
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((reference, query) => {
        const source = sources.find((item) => item.integration_id === reference.integration_id);
        if (source === undefined) throw new Error("Query must select a published fixture source");
        return Promise.resolve(
            marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
        );
    });
    const listInstruments = vi.fn<MarketDataApiClient["listInstruments"]>(() =>
        Promise.resolve([binanceInstrument()])
    );
    renderWorkspace(
        marketDataClient({
            listSources: () => Promise.resolve(sources),
            listInstruments,
            queryBars
        })
    );
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(
            "请选择 Binance Spot 公共行情数据源（GLOBAL）"
        );
    });
    expect(queryBars).not.toHaveBeenCalled();
    expect(listInstruments).not.toHaveBeenCalled();
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox", { name: "数据源" }), "second-source");
    await waitFor(() => {
        expect(queryBars).toHaveBeenCalledTimes(1);
    });
    expect(queryBars.mock.calls[0]?.[0]).toMatchObject({
        integration_id: "second-source",
        integration_revision_fingerprint: "c".repeat(64)
    });
    expect(queryBars.mock.calls[0]?.[1].bar_semantic).toEqual(marketDataBarSemantic(15));
});

it.each([
    ["missing", []],
    ["wrong venue", [marketDataInstrument()]],
    ["duplicate", [binanceInstrument(), binanceInstrument()]]
] as const)(
    "defaults fail closed before Bars when exact BTCUSDT is %s",
    async (_name, instruments) => {
        const queryBars = vi.fn<MarketDataApiClient["queryBars"]>();
        renderWorkspace(
            marketDataClient({
                listSources: () => Promise.resolve([binanceSource()]),
                listInstruments: () => Promise.resolve(instruments),
                queryBars
            })
        );
        await waitFor(() => {
            expect(screen.getByTestId("market-data-status")).toHaveTextContent(
                _name === "duplicate" ? "CONTRACT_ERROR" : "当前数据源未提供 BTCUSDT.BINANCE"
            );
        });
        expect(queryBars).not.toHaveBeenCalled();
        expect(streams.requests).toHaveLength(0);
        expect(renderedPrices()).toEqual([]);
    }
);

it("defaults show unavailable rather than missing configuration when source discovery fails", async () => {
    renderWorkspace(
        marketDataClient({
            listSources: () => Promise.reject(new MarketDataWebError("TRANSPORT_ERROR", "offline"))
        })
    );
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent("行情服务不可用");
    });
    expect(screen.getByTestId("market-data-status")).not.toHaveTextContent("未配置可用");
    expect(renderedPrices()).toEqual([]);
});

it("defaults reject duplicate source ownership rather than choosing by array order", async () => {
    const listInstruments = vi.fn<MarketDataApiClient["listInstruments"]>();
    renderWorkspace(
        marketDataClient({
            listSources: () =>
                Promise.resolve([
                    binanceSource(),
                    binanceSource({ integration_revision_fingerprint: "c".repeat(64) })
                ]),
            listInstruments
        })
    );
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent("CONTRACT_ERROR");
    });
    expect(listInstruments).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox", { name: "数据源" })).toHaveValue("");
});

it("defaults discard a delayed bootstrap response after an explicit source change", async () => {
    let release!: (instruments: ReturnType<typeof binanceInstrument>[]) => void;
    const listInstruments = vi.fn<MarketDataApiClient["listInstruments"]>(
        () =>
            new Promise((resolve) => {
                release = resolve;
            })
    );
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>();
    renderWorkspace(
        marketDataClient({
            listSources: () =>
                Promise.resolve([
                    binanceSource(),
                    marketDataSource({ integration_id: "other-source" })
                ]),
            listInstruments,
            queryBars
        })
    );
    await waitFor(() => {
        expect(listInstruments).toHaveBeenCalledTimes(1);
    });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox", { name: "数据源" }), "other-source");
    await act(async () => {
        release([binanceInstrument()]);
        await Promise.resolve();
    });
    expect(queryBars).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox", { name: "数据源" })).toHaveValue("other-source");
    expect(screen.getByTestId("market-data-observation")).toHaveAttribute(
        "data-observation-mode",
        "unavailable"
    );
});

it("defaults ignore aborted source discovery during StrictMode effect replay", async () => {
    const source = binanceSource();
    const listInstruments = vi.fn<MarketDataApiClient["listInstruments"]>(() =>
        Promise.resolve([binanceInstrument()])
    );
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_reference, query) =>
        Promise.resolve(
            marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
        )
    );
    const listSources = vi.fn<MarketDataApiClient["listSources"]>(() => Promise.resolve([source]));
    render(
        <StrictMode>
            <AppProviders
                client={researchClient()}
                integrationClient={configuredSources()}
                marketDataClient={marketDataClient({ listSources, listInstruments, queryBars })}
            >
                <WorkspacePage />
            </AppProviders>
        </StrictMode>
    );
    await waitFor(() => {
        expect(streams.requests).toHaveLength(1);
    });
    expect(queryBars).toHaveBeenCalledTimes(1);
    expect(listInstruments).toHaveBeenCalledTimes(1);
    expect(listSources.mock.calls[0]?.[0]?.aborted).toBe(true);
    expect(queryBars.mock.calls[0]?.[1].bar_semantic).toEqual(marketDataBarSemantic(15));
});

it.each(["timeframe", "instrument"] as const)(
    "invalidates Inspector proof on %s replacement before a held query or failure",
    async (variant) => {
        const source = binanceSource();
        const initial = binanceInstrument();
        const next = marketDataInstrument({
            instrument_id: "ETHUSDT.BINANCE",
            venue: "BINANCE",
            display_symbol: "ETHUSDT"
        });
        let reject!: (reason: Error) => void;
        const queryBars = vi
            .fn<MarketDataApiClient["queryBars"]>()
            .mockImplementationOnce((_reference, query) =>
                Promise.resolve(
                    marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
                )
            )
            .mockImplementationOnce(
                () =>
                    new Promise((_resolve, fail) => {
                        reject = fail;
                    })
            );
        renderWorkspace(
            marketDataClient({
                listSources: () => Promise.resolve([source]),
                listInstruments: () => Promise.resolve([initial, next]),
                queryBars
            })
        );
        await waitFor(() => {
            expect(screen.getByTestId("market-data-status")).toHaveAttribute(
                "data-status",
                "ready"
            );
        });
        const user = userEvent.setup();
        await user.click(
            within(screen.getByRole("toolbar", { name: "工作区面板" })).getByRole("button", {
                name: "检查器"
            })
        );
        const inspector = within(screen.getByRole("complementary", { name: "上下文面板" }));
        expect(inspector.getByText("COMPLETE")).toBeInTheDocument();
        expect(inspector.getByText("8".repeat(64))).toBeInTheDocument();
        if (variant === "timeframe")
            await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "5");
        else {
            await user.type(screen.getByRole("searchbox", { name: "搜索标的" }), "ETH");
            await user.keyboard("{Enter}");
            await user.click(screen.getByRole("button", { name: /ETHUSDT\.BINANCE/ }));
        }
        await waitFor(() => {
            expect(queryBars).toHaveBeenCalledTimes(2);
        });
        expect(inspector.queryByText("COMPLETE")).not.toBeInTheDocument();
        expect(inspector.queryByText("8".repeat(64))).not.toBeInTheDocument();
        expect(inspector.getByText("尚未查询")).toBeInTheDocument();
        expect(inspector.getByText("尚未验证")).toBeInTheDocument();
        await act(async () => {
            reject(new MarketDataWebError("TRANSPORT_ERROR", "offline"));
            await Promise.resolve();
        });
        await waitFor(() => {
            expect(screen.getByTestId("market-data-status")).toHaveAttribute(
                "data-status",
                "failed"
            );
        });
        expect(inspector.queryByText("COMPLETE")).not.toBeInTheDocument();
        expect(inspector.queryByText("8".repeat(64))).not.toBeInTheDocument();
    }
);

it("replaces only the active price series, preserving range, preview and left-edge guard", () => {
    const bars = projectBars(marketDataBars().bars);
    const last = bars.at(-1);
    if (last === undefined) throw new Error("fixture requires a last Bar");
    const preview = { ...shiftBar(last, 60), closed: false };
    const onNearLeftEdge = vi.fn();
    const semantic = marketDataBarSemantic(1);
    const chart = (chartType: "CANDLESTICK" | "LINE", liveBar = preview) => (
        <PriceChart
            barSemantic={semantic}
            bars={bars}
            liveBar={liveBar}
            contextKey="exact-a"
            chartType={chartType}
            onNearLeftEdge={onNearLeftEdge}
        />
    );
    const view = render(chart("CANDLESTICK"));
    const instances = chartMocks.createChart.mock.calls.length;
    chartMocks.visible.handler?.({ from: 30, to: 80 });
    chartMocks.range.value = { from: 12, to: 62 };
    const anchor = screen.getByTestId("price-chart").getAttribute("data-visible-anchor-time");
    view.rerender(chart("LINE"));
    expect(chartMocks.createChart).toHaveBeenCalledTimes(instances);
    expect(chartMocks.created.removeSeries).toHaveBeenLastCalledWith(chartMocks.candles);
    expect(chartMocks.overlays.setData).toHaveBeenLastCalledWith(
        [...bars, preview].map((bar) => ({ time: bar.time, value: bar.numeric.close }))
    );
    expect(chartMocks.range.value).toEqual({ from: 12, to: 62 });
    expect(onNearLeftEdge).not.toHaveBeenCalled();
    const updated = {
        ...preview,
        close: "109.000000000000000001",
        numeric: { ...preview.numeric, close: 109 }
    };
    view.rerender(chart("LINE", updated));
    expect(chartMocks.overlays.update).toHaveBeenLastCalledWith({ time: updated.time, value: 109 });
    view.rerender(chart("CANDLESTICK", updated));
    expect(chartMocks.created.removeSeries).toHaveBeenLastCalledWith(chartMocks.overlays);
    expect(chartMocks.candles.setData).toHaveBeenLastCalledWith(
        [...bars, updated].map(renderedBar)
    );
    expect(chartMocks.range.value).toEqual({ from: 12, to: 62 });
    expect(screen.getByTestId("price-chart")).toHaveAttribute(
        "data-visible-anchor-time",
        anchor ?? ""
    );
    expect(onNearLeftEdge).not.toHaveBeenCalled();
    expect(chartMocks.createChart).toHaveBeenCalledTimes(instances);
});

it("resolves crosshair time to current exact identity and unsubscribes on destruction", () => {
    const bars = projectBars(marketDataBars().bars);
    const first = bars[0];
    if (first === undefined) throw new Error("fixture requires a first Bar");
    const onSelection = vi.fn();
    const view = render(<PriceChart bars={bars} contextKey="exact-a" onSelection={onSelection} />);
    const handler = chartMocks.created.subscribeCrosshairMove.mock.calls[0]?.[0];
    expect(handler).toBeTypeOf("function");
    const move = handler as (event: {
        time?: number;
        point?: { x: number; y: number };
        seriesData: Map<unknown, unknown>;
    }) => void;
    move({
        time: first.time,
        point: { x: 20, y: 20 },
        seriesData: new Map([[chartMocks.candles, { close: 999 }]])
    });
    expect(onSelection).toHaveBeenLastCalledWith({
        contextKey: "exact-a",
        barStartNs: first.barStartNs
    });
    move({ seriesData: new Map() });
    expect(onSelection).toHaveBeenLastCalledWith(null);
    move({ time: -1, point: { x: 20, y: 20 }, seriesData: new Map() });
    expect(onSelection).toHaveBeenLastCalledWith(null);
    view.rerender(<PriceChart bars={bars} contextKey="exact-b" onSelection={onSelection} />);
    expect(onSelection).toHaveBeenLastCalledWith(null);
    move({ time: first.time, point: { x: 20, y: 20 }, seriesData: new Map() });
    expect(onSelection).toHaveBeenLastCalledWith({
        contextKey: "exact-b",
        barStartNs: first.barStartNs
    });
    view.unmount();
    expect(chartMocks.created.unsubscribeCrosshairMove).toHaveBeenCalledExactlyOnceWith(handler);
});

it("shows exact Workspace observations and changes only browser chart preference", async () => {
    const user = userEvent.setup();
    const first = projectBars(marketDataBars().bars)[0];
    if (first === undefined) throw new Error("fixture requires a first Bar");
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_reference, query) =>
        Promise.resolve(marketDataBarsForQuery(query))
    );
    const client = marketDataClient({
        queryBars,
        listInstruments: () => Promise.resolve([marketDataInstrument()])
    });
    const acquisition = vi.spyOn(client, "createAcquisition");
    renderWorkspace(client);
    expect(screen.getByTestId("market-data-observation")).toHaveAttribute(
        "data-observation-mode",
        "unavailable"
    );
    expect(screen.getByRole("combobox", { name: "图表类型" })).toHaveValue("CANDLESTICK");
    await selectSource(user);
    await selectBtcInstrument(user);
    await waitFor(() => {
        expect(screen.getByTestId("market-data-observation")).toHaveAttribute(
            "data-observation-mode",
            "latest-closed"
        );
    });
    expect(screen.getByTestId("market-data-observation")).toHaveTextContent("C 102.50");
    const requests = queryBars.mock.calls.length;
    await user.selectOptions(screen.getByRole("combobox", { name: "图表类型" }), "LINE");
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-chart-type", "LINE");
    expect(queryBars).toHaveBeenCalledTimes(requests);
    expect(acquisition).not.toHaveBeenCalled();
    const handler = chartMocks.created.subscribeCrosshairMove.mock.calls[0]?.[0] as (
        event: object
    ) => void;
    act(() => {
        handler({ time: first.time, point: { x: 10, y: 10 } });
    });
    expect(screen.getByTestId("market-data-observation")).toHaveAttribute(
        "data-observation-mode",
        "crosshair"
    );
    expect(screen.getByTestId("market-data-observation")).toHaveTextContent("C 101.00");
    act(() => {
        handler({});
    });
    expect(screen.getByTestId("market-data-observation")).toHaveAttribute(
        "data-observation-mode",
        "latest-closed"
    );
    act(() => {
        handler({ time: first.time, point: { x: 10, y: 10 } });
    });
    await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "5");
    await waitFor(() => {
        expect(screen.getByTestId("market-data-observation")).toHaveAttribute(
            "data-observation-mode",
            "latest-closed"
        );
    });
    expect(screen.getByRole("combobox", { name: "图表类型" })).toHaveValue("LINE");
});

it("derives selected preview updates from identity and falls back on mouse leave", async () => {
    const user = userEvent.setup();
    renderWorkspace(
        marketDataClient({
            listInstruments: () => Promise.resolve([marketDataInstrument()]),
            queryBars: (_reference, query) => Promise.resolve(marketDataBarsForQuery(query))
        })
    );
    await selectSource(user);
    await selectBtcInstrument(user);
    await waitFor(() => {
        expect(streams.callbacks).toHaveLength(1);
    });
    const original = marketDataBars().bars[0];
    if (original === undefined) throw new Error("fixture requires a Bar");
    const bar = {
        ...original,
        bar_start_ns: "1767225720000000000",
        bar_end_ns: "1767225780000000000",
        closed: false,
        close: "103.000000000000000001",
        volume: "7.000000000000000001"
    };
    const event = {
        schema_version: 2 as const,
        event: "BAR_PREVIEW" as const,
        source_id: marketDataSource().source_id,
        instrument_id: marketDataInstrument().instrument_id,
        bar_semantic: marketDataBarSemantic(1),
        bar
    };
    act(() => {
        streams.callbacks[0]?.(event);
    });
    const observation = screen.getByTestId("market-data-observation");
    expect(observation).toHaveAttribute("data-observation-mode", "preview");
    expect(observation).toHaveTextContent("实时预览");
    expect(observation).toHaveTextContent("103.000000000000000001");
    const move = chartMocks.created.subscribeCrosshairMove.mock.calls[0]?.[0] as (
        event: object
    ) => void;
    act(() => {
        move({ time: projectMarketDataBar(bar).time, point: { x: 10, y: 10 } });
    });
    expect(observation).toHaveAttribute("data-observation-mode", "crosshair");
    act(() => {
        streams.callbacks[0]?.({ ...event, bar: { ...bar, close: "104.000000000000000001" } });
    });
    expect(observation).toHaveTextContent("104.000000000000000001");
    await user.unhover(screen.getByTestId("price-chart"));
    act(() => {
        move({});
    });
    expect(observation).toHaveAttribute("data-observation-mode", "preview");
    act(() => {
        streams.callbacks[0]?.({
            ...event,
            event: "BAR_CLOSED",
            sequence: "29453762",
            bar: { ...bar, closed: true }
        });
    });
    expect(observation).toHaveAttribute("data-observation-mode", "latest-closed");
    expect(observation).toHaveTextContent("103.000000000000000001");
    act(() => {
        move({ time: projectMarketDataBar(bar).time, point: { x: 10, y: 10 } });
    });
    await user.selectOptions(screen.getByRole("combobox", { name: "数据源" }), "");
    expect(observation).toHaveAttribute("data-observation-mode", "unavailable");
    expect(observation).toHaveAttribute("data-bar-start-ns", "");
});

it("renders canonical Product bars without browser range planning", () => {
    expect(projectBars(marketDataBars().bars).map(toCandlestick)).toEqual([
        { time: 1_767_225_600, open: 100, high: 102, low: 99, close: 101 },
        { time: 1_767_225_660, open: 101, high: 103, low: 100, close: 102.5 }
    ]);
});

it("updates realtime candles without recreating the chart", () => {
    const historical = projectBars(marketDataBars().bars);
    const view = render(
        <PriceChart
            barSemantic={marketDataBarSemantic(7)}
            bars={historical}
            contextKey="revision-a"
        />
    );
    const created = chartMocks.createChart.mock.calls.length;
    const second = historical.at(1);
    if (second === undefined) throw new Error("fixture requires two bars");
    const preview = { ...second, close: "103", numeric: { ...second.numeric, close: 103 } };

    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(7)}
            bars={historical}
            contextKey="revision-a"
            liveBar={preview}
        />
    );

    expect(chartMocks.createChart).toHaveBeenCalledTimes(created);
    expect(chartMocks.candles.update).toHaveBeenLastCalledWith(renderedBar(preview));
    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(37)}
            bars={historical.slice(1)}
            contextKey="revision-b"
        />
    );
    expect(chartMocks.candles.setData).toHaveBeenLastCalledWith(
        historical.slice(1).map(renderedBar)
    );
    expect(chartMocks.createChart).toHaveBeenCalledTimes(created);
});

it("subscribes to the visible range and unsubscribes the same handler", () => {
    const view = render(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            bars={projectBars(marketDataBars().bars)}
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
            bars={projectBars(marketDataBars().bars)}
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
    const history = projectBars(marketDataBars().bars);
    const chart = (key: string, bars: typeof history) => (
        <PriceChart
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
    const history = projectBars(marketDataBars().bars);
    const chart = (callback: () => void) => (
        <StrictMode>
            <PriceChart
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
    const first = projectBars(marketDataBars().bars)[0];
    if (first === undefined) throw new Error("fixture requires a first Bar");
    const candle = (index: number) => shiftBar(first, index * 60);
    const prior = [candle(1), candle(2)];
    const view = render(
        <PriceChart barSemantic={marketDataBarSemantic(1)} bars={prior} contextKey="context-a" />
    );
    const created = chartMocks.createChart.mock.calls.length;
    chartMocks.range.value = { from: 5, to: 10 };
    chartMocks.timeScale.setVisibleLogicalRange.mockClear();
    view.rerender(
        <PriceChart
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
    const prior = projectBars(marketDataBars().bars);
    const first = prior[0];
    const last = prior[1];
    if (first === undefined || last === undefined) throw new Error("fixture requires two Bars");
    const view = render(
        <PriceChart barSemantic={marketDataBarSemantic(1)} bars={prior} contextKey="context-a" />
    );
    act(() => {
        chartMocks.range.value = { from: 0.2, to: 1.2 };
        chartMocks.visible.handler?.(chartMocks.range.value);
    });
    const chart = screen.getByTestId("price-chart");
    expect(chart).toHaveAttribute("data-visible-anchor-time", String(last.time));
    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            bars={[shiftBar(first, -60), ...prior, shiftBar(last, 60)]}
            contextKey="context-a"
        />
    );
    expect(chart).toHaveAttribute("data-visible-anchor-time", String(last.time));
    expect(chart).toHaveAttribute("data-visible-range-from", "1.2");
});

it("shifts the logical range by the strict prepend count", () => {
    const historical = projectBars(marketDataBars().bars);
    const first = historical[0];
    if (first === undefined) throw new Error("fixture requires a first Bar");
    const earlier = shiftBar(first, -60);
    const view = render(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            bars={historical}
            contextKey="context-a"
        />
    );
    chartMocks.timeScale.setVisibleLogicalRange.mockClear();
    chartMocks.range.value = { from: 5, to: 10 };

    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
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
    const historical = projectBars(marketDataBars().bars);
    const view = render(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
            bars={historical}
            contextKey="context-a"
        />
    );
    chartMocks.timeScale.setVisibleLogicalRange.mockClear();

    view.rerender(
        <PriceChart
            barSemantic={marketDataBarSemantic(1)}
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
    const historical = projectBars(marketDataBars().bars);
    const first = historical[0];
    const last = historical[1];
    if (first === undefined || last === undefined) throw new Error("fixture requires two bars");
    const specification = marketDataBarSemantic(1);
    const view = render(
        <PriceChart barSemantic={specification} bars={historical} contextKey="revision-a" />
    );

    view.rerender(
        <PriceChart
            barSemantic={specification}
            bars={historical}
            contextKey="revision-a"
            liveBar={{ ...first, close: "999", numeric: { ...first.numeric, close: 999 } }}
        />
    );
    expect(chartMocks.candles.update).not.toHaveBeenCalled();

    const next = { ...shiftBar(last, 60), close: "103", numeric: { ...last.numeric, close: 103 } };
    view.rerender(
        <PriceChart
            barSemantic={specification}
            bars={historical}
            contextKey="revision-a"
            liveBar={next}
        />
    );
    expect(chartMocks.candles.update).toHaveBeenCalledExactlyOnceWith(renderedBar(next));

    view.rerender(
        <PriceChart
            barSemantic={specification}
            bars={historical}
            contextKey="revision-a"
            liveBar={{ ...last, close: "999", numeric: { ...last.numeric, close: 999 } }}
        />
    );
    expect(chartMocks.candles.update).toHaveBeenCalledTimes(1);
});

it("renders no invented candles in an unconfigured workspace", async () => {
    renderWorkspace(marketDataClient({ listSources: () => Promise.resolve([]) }));

    await waitFor(() => {
        expect(renderedPrices()).toEqual([]);
    });
    expect(screen.getByTestId("market-data-status")).toHaveTextContent(
        "未配置可用的 Binance Spot 公共行情数据源（GLOBAL）"
    );
    expect(screen.getByTestId("real-overlay-note")).toHaveTextContent("尚未接入正式 Catalog");
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
        "指标/因子目录尚未接入正式 Catalog"
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
