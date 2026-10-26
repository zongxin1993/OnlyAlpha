import { requiredValue } from "../../test/requiredValue";
import { readTemporaryMarketData } from "../../api/marketData/temporary";
import { temporaryWindowForQuery } from "../../test/temporaryMarketDataClient";
import { TEMPORARY_VECTOR_FINGERPRINT } from "../../test/temporaryChartVectors";
import { marketDataSourceChoiceKey } from "../../api/marketData/model";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { AppProviders } from "../../app/providers";
import { MarketDataWebError } from "../../api/marketData/client";
import type { MarketDataApiClient } from "../../api/marketData/client";
import {
    fixedDurationMinutes,
    marketDataBarSemantic,
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
    marketDataBars,
    marketDataBarsForQuery,
    marketDataClient,
    marketDataSource,
    marketDataInstrument
} from "../../test/marketDataClient";
import { chartCatalogFixture } from "../../test/chartCatalog";
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
import type { TemporaryMarketDataStreamEvent as MarketDataStreamEvent } from "../../api/marketData/stream.generated";

const streams = vi.hoisted(() => ({
    callbacks: [] as ((event: MarketDataStreamEvent) => void)[],
    requests: [] as unknown[]
}));
vi.mock("../../api/marketData/temporary", () => ({ readTemporaryMarketData: vi.fn() }));
let temporaryProducer: MarketDataApiClient;
vi.mock("../../api/marketData/temporaryStream", () => ({
    openTemporaryMarketDataStream: (
        request: unknown,
        callback: (event: MarketDataStreamEvent) => void
    ) => {
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
    const pricePane = {
        paneIndex: () => 0,
        setPreserveEmptyPane: vi.fn(),
        setStretchFactor: vi.fn()
    };
    const volumePane = { paneIndex: () => 1, setStretchFactor: vi.fn() };
    const range = { value: { from: 30, to: 60 } as { from: number; to: number } | null };
    const visible = {
        handler: null as ((range: { from: number; to: number } | null) => void) | null
    };
    const candles = {
        getPane: () => pricePane,
        setData: vi.fn<(bars: readonly unknown[]) => void>(),
        update: vi.fn<(bar: unknown) => void>()
    };
    const overlays = {
        getPane: () => pricePane,
        setData: vi.fn<(points: readonly unknown[]) => void>(),
        update: vi.fn<(bar: unknown) => void>()
    };
    const volume = {
        getPane: () => volumePane,
        setData: vi.fn<(bars: readonly unknown[]) => void>(),
        update: vi.fn<(bar: unknown) => void>()
    };
    const addSeries = vi.fn<
        (definition: string) => {
            setData: typeof candles.setData;
            update: typeof candles.update;
            getPane: () => typeof volumePane;
        }
    >((definition) =>
        definition === "Candlestick" ? candles : definition === "Histogram" ? volume : overlays
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
        applyOptions: vi.fn(),
        removePane: vi.fn(),
        addPane: () => volumePane,
        panes: () => [pricePane, volumePane],
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
        volume,
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
    HistogramSeries: "Histogram",
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
    temporaryProducer = client;
    return render(
        <AppProviders integrationClient={configuredSources()} marketDataClient={client}>
            <WorkspacePage />
        </AppProviders>
    );
}

async function sourceControl(user: ReturnType<typeof userEvent.setup>) {
    const summary = screen.getByText("行情设置", { exact: true });
    if (!(summary.parentElement as HTMLDetailsElement).open) await user.click(summary);
    return screen.getByRole("combobox", { name: "数据源" });
}

async function searchInput(user: ReturnType<typeof userEvent.setup>) {
    if (screen.queryByRole("dialog", { name: "商品搜索" }) === null)
        await user.click(screen.getByRole("button", { name: "搜索商品" }));
    return screen.getByRole("searchbox", { name: "商品代码或名称" });
}

async function selectSource(user: ReturnType<typeof userEvent.setup>) {
    await screen.findByRole("option", { name: /Fixture Source/ });
    await user.selectOptions(
        await sourceControl(user),
        marketDataSourceChoiceKey(marketDataSource())
    );
    // These existing manual-context regressions explicitly request their 1m fixture.
    await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "1");
}

async function selectBtcInstrument(user: ReturnType<typeof userEvent.setup>) {
    const search = await searchInput(user);
    await user.type(search, "BTC{Enter}");
    await user.click(await screen.findByRole("button", { name: /查看 BTCUSDT/ }));
}

const dialogDescriptors = {
    showModal: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal"),
    close: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close")
};

beforeEach(() => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string) =>
            Promise.resolve(
                new Response(
                    JSON.stringify(
                        url === "/api/v2/workspace"
                            ? { schema_version: 2, version: 0, configuration: null }
                            : url === "/api/v2/watchlists"
                              ? { schema_version: 2, version: 0, lists: [] }
                              : { error: { code: "UNAVAILABLE" } }
                    ),
                    {
                        status: ["/api/v2/workspace", "/api/v2/watchlists"].includes(url)
                            ? 200
                            : 503
                    }
                )
            )
        )
    );
    // Controlled data producer only: extend the older two-row vectors to the real
    // 2000-row temporary window. No production retained-history API is invoked.
    vi.mocked(readTemporaryMarketData).mockImplementation(async (credentials, reference, query) => {
        if (!credentials.localSession || credentials.capture().bearer !== null)
            throw new MarketDataWebError(
                "MARKET_DATA_ACCESS_DENIED",
                "临时行情需要本地 Owner 会话",
                403
            );
        const sample = await temporaryProducer.queryBars(reference, query);
        const value = temporaryWindowForQuery(reference, {
            ...query,
            before_ns: query.before_ns ?? sample.resolved_end_ns
        });
        value.anchor_kind = query.anchor_kind;
        value.requested_before_ns = query.before_ns ?? null;
        value.source_selection = sample.source_selection;
        value.window_fingerprint = TEMPORARY_VECTOR_FINGERPRINT;
        value.resolution_plan_fingerprint = requiredValue(sample.resolution_plan_fingerprint);
        const first = sample.bars[0];
        if (first !== undefined) {
            value.bars = value.bars.map((bar, index) => {
                const prices =
                    sample.bars[index - (value.bars.length - sample.bars.length)] ?? first;
                return {
                    ...bar,
                    open: prices.open,
                    high: prices.high,
                    low: prices.low,
                    close: prices.close,
                    volume: prices.volume
                };
            });
        }
        if (sample.coverage.status !== "COMPLETE") {
            value.coverage = {
                ...value.coverage,
                status: "PARTIAL",
                actual_bar_count: 0,
                gaps: value.bars.map((bar) => ({
                    start_ns: bar.bar_start_ns,
                    end_ns: bar.bar_end_ns
                }))
            };
            value.bars = [];
        }
        return value;
    });
    // jsdom has no modal API; native focus/modal behavior is Browser-owned.
    Object.defineProperties(HTMLDialogElement.prototype, {
        showModal: {
            configurable: true,
            value: function (this: HTMLDialogElement) {
                this.setAttribute("open", "");
            }
        },
        close: {
            configurable: true,
            value: function (this: HTMLDialogElement) {
                this.removeAttribute("open");
            }
        }
    });
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
    cleanup();
    for (const name of ["showModal", "close"] as const) {
        const descriptor = dialogDescriptors[name];
        if (descriptor === undefined) Reflect.deleteProperty(HTMLDialogElement.prototype, name);
        else Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    }
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
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

it("refreshes chart sources after returning from management without restarting the workspace", async () => {
    const source = binanceSource();
    let available: readonly MarketDataSource[] = [];
    const listSources = vi.fn<MarketDataApiClient["listSources"]>(() => Promise.resolve(available));
    renderWorkspace(
        marketDataClient({
            listSources,
            listInstruments: () => Promise.resolve([binanceInstrument()]),
            queryBars: (_reference, query) =>
                Promise.resolve(
                    marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
                )
        })
    );
    await screen.findByText("尚未配置可用的行情来源，请先添加行情来源。", {
        selector: "p[role=status]"
    });
    expect(screen.getByRole("button", { name: "搜索商品" })).toBeEnabled();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "管理数据源" }));
    available = [source];
    await user.click(
        within(screen.getByRole("dialog", { name: "管理数据源" })).getByRole("button", {
            name: "关闭"
        })
    );
    await waitFor(() => {
        expect(screen.getByRole("combobox", { name: "数据源" })).toHaveValue(
            marketDataSourceChoiceKey(source)
        );
    });
    expect(screen.getByRole("button", { name: "搜索商品" })).toBeEnabled();
    expect(listSources).toHaveBeenCalledTimes(2);
});

it("offers visible symbol search and preserves a manual choice after unchanged source refresh", async () => {
    const source = binanceSource();
    const btc = binanceInstrument();
    const eth = marketDataInstrument({
        instrument_id: "ETHUSDT.BINANCE",
        display_symbol: "ETH/USDT",
        venue: "BINANCE"
    });
    const listInstruments = vi.fn<MarketDataApiClient["listInstruments"]>(
        (_ref, query, _signal, ids) =>
            Promise.resolve(query === "ETH" || ids?.includes(eth.instrument_id) ? [eth] : [btc])
    );
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_ref, query) =>
        Promise.resolve(
            marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
        )
    );
    renderWorkspace(
        marketDataClient({
            listSources: () => Promise.resolve([{ ...source }]),
            listInstruments,
            queryBars
        })
    );
    await waitFor(() => {
        expect(streams.requests).toHaveLength(1);
    });
    const user = userEvent.setup();
    await user.type(await searchInput(user), "ETH");
    await user.click(await screen.findByRole("button", { name: /查看 ETH.?USDT/ }));
    await waitFor(() => {
        expect(queryBars).toHaveBeenCalledTimes(2);
    });
    await user.click(screen.getByRole("button", { name: "数据源" }));
    await user.click(screen.getByRole("button", { name: "管理数据源…" }));
    await user.click(
        within(screen.getByRole("dialog", { name: "管理数据源" })).getByRole("button", {
            name: "关闭"
        })
    );
    expect(screen.getByRole("combobox", { name: "数据源" })).toHaveValue(
        marketDataSourceChoiceKey(source)
    );
    expect(queryBars).toHaveBeenCalledTimes(2);
    expect(queryBars.mock.calls.at(-1)?.[1].instrument_id).toBe(eth.instrument_id);
    expect(listInstruments).toHaveBeenCalledTimes(3);
});

it.each(["name", "revision"])(
    "preserves period and requires explicit reselection when the exact source %s changes",
    async (change) => {
        let source = binanceSource();
        const btc = binanceInstrument();
        const eth = marketDataInstrument({
            instrument_id: "ETHUSDT.BINANCE",
            display_symbol: "ETH/USDT",
            venue: "BINANCE"
        });
        const listInstruments = vi.fn<MarketDataApiClient["listInstruments"]>(
            (_ref, query, _signal, ids) =>
                Promise.resolve(query === "ETH" || ids?.includes(eth.instrument_id) ? [eth] : [btc])
        );
        const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_ref, query) =>
            Promise.resolve(
                marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
            )
        );
        renderWorkspace(
            marketDataClient({
                listSources: () => Promise.resolve([{ ...source }]),
                listInstruments,
                queryBars
            })
        );
        await waitFor(() => {
            expect(streams.requests).toHaveLength(1);
        });
        const user = userEvent.setup();
        await user.type(await searchInput(user), "ETH");
        await user.click(await screen.findByRole("button", { name: /查看 ETH.?USDT/ }));
        await waitFor(() => {
            expect(queryBars).toHaveBeenCalledTimes(2);
        });
        await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "5");
        await waitFor(() => {
            expect(queryBars).toHaveBeenCalledTimes(3);
        });
        const oldStream = streams.callbacks.at(-1);
        source = {
            ...source,
            display_name: "Updated source",
            ...(change === "revision" ? { integration_revision_fingerprint: "c".repeat(64) } : {})
        };
        await user.click(screen.getByRole("button", { name: "数据源" }));
        await user.click(screen.getByRole("button", { name: "管理数据源…" }));
        await user.click(
            within(screen.getByRole("dialog", { name: "管理数据源" })).getByRole("button", {
                name: "关闭"
            })
        );
        expect(screen.getByRole("combobox", { name: "时间周期" })).toHaveValue("5");
        expect(queryBars).toHaveBeenCalledTimes(3);
        const last = queryBars.mock.calls.at(-1);
        if (last === undefined) throw new Error("No exact Source query");
        expect(fixedDurationMinutes(last[1].bar_semantic)).toBe(5);
        expect(last[0].integration_revision_fingerprint).toBe("b".repeat(64));
        expect(last[1].instrument_id).toBe(eth.instrument_id);
        if (change === "revision") {
            expect(screen.getByRole("combobox", { name: "数据源" })).toHaveValue("");
            expect(screen.getByTestId("market-data-status")).toHaveTextContent("不会自动换源");
            expect(renderedPrices()).toEqual([]);
            const lateBar = marketDataBars().bars[1];
            if (lateBar === undefined) throw new Error("Missing Bar fixture");
            act(() =>
                oldStream?.({
                    schema_version: 2,
                    event: "BAR_PREVIEW",
                    timing: null,
                    source_id: source.source_id,
                    instrument_id: eth.instrument_id,
                    bar_semantic: marketDataBarSemantic(5),
                    bar: { ...lateBar, closed: false }
                })
            );
            expect(renderedPrices()).toEqual([]);
            expect(
                queryBars.mock.calls.some(
                    ([reference]) => reference.integration_revision_fingerprint === "c".repeat(64)
                )
            ).toBe(false);
            expect(
                (
                    streams.requests as {
                        source_reference: { integration_revision_fingerprint: string };
                    }[]
                ).some(
                    (request) =>
                        request.source_reference.integration_revision_fingerprint === "c".repeat(64)
                )
            ).toBe(false);
        } else {
            expect(screen.getByRole("combobox", { name: "数据源" })).toHaveValue(
                marketDataSourceChoiceKey(source)
            );
            expect(renderedPrices()).toEqual([...Array<number>(1999).fill(101), 102.5]);
        }
        expect(listInstruments).toHaveBeenCalledTimes(3);
    }
);

it("does not replace newer symbol search results with an older response", async () => {
    let completeOlder: ((value: ReturnType<typeof marketDataInstrument>[]) => void) | undefined;
    const eth = marketDataInstrument({ instrument_id: "ETHUSDT.TEST", display_symbol: "ETH/USDT" });
    renderWorkspace(
        marketDataClient({
            listInstruments: (_ref, query) =>
                query === "BTC"
                    ? new Promise((resolve) => {
                          completeOlder = resolve;
                      })
                    : Promise.resolve([eth])
        })
    );
    const user = userEvent.setup();
    await selectSource(user);
    const search = await searchInput(user);
    await user.type(search, "BTC");
    await waitFor(() => {
        expect(completeOlder).toBeTypeOf("function");
    });
    await user.clear(search);
    await user.type(search, "ETH");
    await screen.findByRole("button", { name: /查看 ETH.?USDT/ });
    await act(() => {
        completeOlder?.([marketDataInstrument()]);
        return Promise.resolve();
    });
    expect(screen.queryByRole("button", { name: /查看 BTCUSDT/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看 ETH.?USDT/ })).toBeInTheDocument();
});

it("does not let a delayed default instrument replace a user's completed manual search", async () => {
    const source = binanceSource();
    const eth = marketDataInstrument({
        instrument_id: "ETHUSDT.BINANCE",
        display_symbol: "ETH/USDT",
        venue: "BINANCE"
    });
    let completeDefault: ((value: ReturnType<typeof binanceInstrument>[]) => void) | undefined;
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_ref, query) =>
        Promise.resolve(
            marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
        )
    );
    renderWorkspace(
        marketDataClient({
            listSources: () => Promise.resolve([source]),
            listInstruments: (_ref, query) =>
                query === "BTCUSDT"
                    ? new Promise((resolve) => {
                          completeDefault = resolve;
                      })
                    : Promise.resolve([eth]),
            queryBars
        })
    );
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "搜索商品" })).toBeEnabled();
    });
    const user = userEvent.setup();
    await user.type(await searchInput(user), "ETH");
    await user.click(await screen.findByRole("button", { name: /查看 ETH.?USDT/ }));
    await waitFor(() => {
        expect(queryBars).toHaveBeenCalledTimes(1);
    });
    await act(() => {
        completeDefault?.([binanceInstrument()]);
        return Promise.resolve();
    });
    expect(queryBars).toHaveBeenCalledTimes(1);
    expect(queryBars.mock.calls[0]?.[1].instrument_id).toBe(eth.instrument_id);
});

it("preserves configuration-only discovery in Shipping Workspace without a local bearer", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "false");
    const fixture = chartCatalogFixture();
    const reads: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
        const path =
            typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        reads.push(path);
        expect(path.startsWith("/api/v2/research/")).toBe(true);
        return Promise.resolve(
            new Response(
                JSON.stringify(
                    path.endsWith("/active")
                        ? { detail: "RUNTIME_GENERATION_NOT_ACTIVE" }
                        : fixture.discovery
                ),
                { status: path.endsWith("/active") ? 503 : 200 }
            )
        );
    });
    const user = userEvent.setup();
    const workspace = renderWorkspace(
        marketDataClient({ listInstruments: () => Promise.resolve([marketDataInstrument()]) })
    );
    await selectSource(user);
    await selectBtcInstrument(user);
    await user.click(screen.getByRole("button", { name: "指标" }));
    await user.click(await screen.findByRole("button", { name: "选择 SMA · 配置草稿" }));
    await user.click(screen.getByText("高级选项"));
    // jsdom does not load the Shipping accent CSS custom property.
    expect(screen.queryByRole("textbox", { name: "颜色" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "颜色" })).getAllByRole("button")).toHaveLength(
        16
    );
    await user.click(screen.getByRole("button", { name: /^红色$/ }));
    expect(screen.getByRole("button", { name: "添加" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "添加" }));
    const instance = await screen.findByTestId("chart-study-instance");
    expect(instance).toHaveAttribute("data-registration-source", "REGISTERED_DISCOVERY");
    expect(instance).toHaveTextContent("已配置，尚未接入后端计算");
    expect(screen.getByTestId("real-overlay-note")).toHaveTextContent("指标尚未接入计算");
    expect(screen.queryByTestId("chart-study-query-status")).not.toBeInTheDocument();
    expect(screen.getByTestId("price-chart")).toHaveAttribute("data-study-series-count", "0");
    expect(reads).toEqual([
        "/api/v2/research/runtime-generations/active",
        "/api/v2/research/catalog/calculations",
        "/api/v2/research/catalog/calculations",
        "/api/v2/research/catalog/calculations"
    ]);
    workspace.unmount();
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
        target_bar_count: 2000,
        bar_semantic: marketDataBarSemantic(15)
    });
    expect(streams.requests[0]).toMatchObject({
        source_reference: reference,
        instrument_id: instrument.instrument_id,
        bar_semantic: marketDataBarSemantic(15)
    });
    expect(screen.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
    expect(renderedPrices()).toEqual([...Array<number>(1999).fill(101), 102.5]);
    expect(chartMocks.overlays.setData).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "指标" })).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.getByRole("button", { name: "因子" })).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
});

it("keeps the default chart incarnation when reselecting its source, instrument and 15m", async () => {
    const source = binanceSource();
    const instrument = binanceInstrument();
    const queryBars = vi.fn<MarketDataApiClient["queryBars"]>((_reference, query) =>
        Promise.resolve(
            marketDataBarsForQuery(query, { source_selection: sourceSelection(source) })
        )
    );
    renderWorkspace(
        marketDataClient({
            listSources: () => Promise.resolve([source]),
            listInstruments: () => Promise.resolve([instrument]),
            queryBars
        })
    );
    await waitFor(() => {
        expect(streams.requests).toHaveLength(1);
    });
    const user = userEvent.setup();
    const observation = screen.getByTestId("market-data-observation");
    const context = observation.getAttribute("data-chart-context-key");
    await user.selectOptions(await sourceControl(user), marketDataSourceChoiceKey(source));
    await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "15");
    await user.type(await searchInput(user), "BTCUSDT{Enter}");
    await user.click(await screen.findByRole("button", { name: /查看 BTCUSDT/ }));
    expect(queryBars).toHaveBeenCalledTimes(1);
    expect(streams.requests).toHaveLength(1);
    expect(observation).toHaveAttribute("data-chart-context-key", context);
    expect(renderedPrices()).toEqual([...Array<number>(1999).fill(101), 102.5]);
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
                sources.length === 0
                    ? "尚未配置可用的行情来源，请先添加行情来源。"
                    : "请在左上角搜索并选择商品。"
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
            "请在左上角搜索并选择商品。"
        );
    });
    expect(queryBars).not.toHaveBeenCalled();
    expect(listInstruments).not.toHaveBeenCalled();
    const user = userEvent.setup();
    const chosen = sources[1];
    if (chosen === undefined) throw new Error("fixture requires the second exact Source");
    await user.selectOptions(await sourceControl(user), marketDataSourceChoiceKey(chosen));
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
                    binanceSource({ source_id: "conflicting-owner-for-the-same-exact-reference" })
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
    await user.selectOptions(
        await sourceControl(user),
        marketDataSourceChoiceKey(marketDataSource({ integration_id: "other-source" }))
    );
    await act(async () => {
        release([binanceInstrument()]);
        await Promise.resolve();
    });
    expect(queryBars).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox", { name: "数据源" })).toHaveValue(
        marketDataSourceChoiceKey(marketDataSource({ integration_id: "other-source" }))
    );
    expect(screen.getByTestId("market-data-observation")).toHaveAttribute(
        "data-observation-mode",
        "unavailable"
    );
});

it("defaults fence the aborted workspace bootstrap before starting one Source discovery in StrictMode", async () => {
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
                integrationClient={configuredSources()}
                marketDataClient={
                    (temporaryProducer = marketDataClient({
                        listSources,
                        listInstruments,
                        queryBars
                    }))
                }
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
    expect(listSources).toHaveBeenCalledTimes(1);
    expect(listSources.mock.calls[0]?.[0]?.aborted).toBe(false);
    expect(
        vi.mocked(fetch).mock.calls.find(([url]) => url === "/api/v2/workspace")?.[1]?.signal
            ?.aborted
    ).toBe(true);
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
                listInstruments: (_ref, _query, _signal, ids) =>
                    Promise.resolve(
                        ids === undefined
                            ? [initial, next]
                            : [initial, next].filter((item) => ids.includes(item.instrument_id))
                    ),
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
        expect(inspector.getByText(TEMPORARY_VECTOR_FINGERPRINT)).toBeInTheDocument();
        if (variant === "timeframe")
            await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "5");
        else {
            await user.type(await searchInput(user), "ETH");
            await user.keyboard("{Enter}");
            await user.click(await screen.findByRole("button", { name: /查看 ETH.?USDT/ }));
        }
        await waitFor(() => {
            expect(queryBars).toHaveBeenCalledTimes(2);
        });
        expect(inspector.queryByText("COMPLETE")).not.toBeInTheDocument();
        expect(inspector.queryByText(TEMPORARY_VECTOR_FINGERPRINT)).not.toBeInTheDocument();
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
        expect(inspector.queryByText(TEMPORARY_VECTOR_FINGERPRINT)).not.toBeInTheDocument();
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
    expect(chartMocks.overlays.update).toHaveBeenLastCalledWith({
        time: updated.time,
        value: updated.numeric.close
    });
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
    const activeHandler = chartMocks.created.subscribeCrosshairMove.mock.calls.at(-1)?.[0];
    const retiredHandler = chartMocks.created.subscribeCrosshairMove.mock.calls[0]?.[0];
    // Context is refreshed through the existing chart's committed live ref.
    // Retained presentation intent must not remount or duplicate subscriptions.
    expect(activeHandler).toBe(retiredHandler);
    expect(chartMocks.created.subscribeCrosshairMove).toHaveBeenCalledTimes(1);
    expect(chartMocks.created.unsubscribeCrosshairMove).not.toHaveBeenCalled();
    const handler = activeHandler as (event: object) => void;
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
        timing: null,
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
    const activeHandler = chartMocks.created.subscribeCrosshairMove.mock.calls.at(-1)?.[0];
    const retiredHandler = chartMocks.created.subscribeCrosshairMove.mock.calls[0]?.[0];
    // Context is refreshed through the existing chart's committed live ref.
    // Retained presentation intent must not remount or duplicate subscriptions.
    expect(activeHandler).toBe(retiredHandler);
    expect(chartMocks.created.subscribeCrosshairMove).toHaveBeenCalledTimes(1);
    expect(chartMocks.created.unsubscribeCrosshairMove).not.toHaveBeenCalled();
    const move = activeHandler as (event: object) => void;
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
            timing: null,
            sequence: "29453762",
            bar: { ...bar, closed: true }
        });
    });
    expect(observation).toHaveAttribute("data-observation-mode", "latest-closed");
    expect(observation).toHaveTextContent("103.000000000000000001");
    act(() => {
        move({ time: projectMarketDataBar(bar).time, point: { x: 10, y: 10 } });
    });
    await user.selectOptions(await sourceControl(user), "");
    const unavailableObservation = screen.getByTestId("market-data-observation");
    expect(observation).toBe(unavailableObservation);
    act(() => {
        move({ time: projectMarketDataBar(bar).time, point: { x: 10, y: 10 } });
    });
    expect(unavailableObservation).toHaveAttribute("data-observation-mode", "unavailable");
    expect(unavailableObservation).toHaveAttribute("data-bar-start-ns", "");
});

it("conflicting closed history withdraws its fingerprint without starting acquisition", async () => {
    const user = userEvent.setup();
    let current: MarketDataBars | null = null;
    const acquire = vi.fn();
    renderWorkspace(
        marketDataClient({
            listInstruments: () => Promise.resolve([marketDataInstrument()]),
            queryBars: (_reference, query) => {
                current = marketDataBarsForQuery(query);
                return Promise.resolve(current);
            },
            createAcquisition: acquire
        })
    );
    await selectSource(user);
    await selectBtcInstrument(user);
    await waitFor(() => {
        expect(streams.callbacks).toHaveLength(1);
    });
    const history = current as MarketDataBars | null;
    const bar = history?.bars[0];
    if (history === null || bar === undefined) throw new Error("Expected owning closed history");
    expect(screen.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready");
    expect(screen.getByTestId("market-data-status")).toHaveAttribute(
        "data-temporary-window-fingerprint",
        TEMPORARY_VECTOR_FINGERPRINT
    );
    act(() => {
        streams.callbacks[0]?.({
            schema_version: 2,
            event: "BAR_CLOSED",
            timing: null,
            source_id: history.source_selection.source_id,
            instrument_id: history.instrument_id,
            bar_semantic: history.bar_semantic,
            sequence: "29453762",
            bar: { ...bar, close: "101.500000000000" }
        });
    });
    expect(screen.getByTestId("market-data-status")).toHaveAttribute("data-status", "failed");
    // The Shipping consumer receives null rather than retaining a stale witness.
    expect(screen.getByTestId("market-data-status")).toHaveAttribute(
        "data-temporary-window-fingerprint",
        ""
    );
    expect(acquire).not.toHaveBeenCalled();
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
    expect(chartMocks.candles.setData).toHaveBeenLastCalledWith(
        historical.map((bar) => renderedBar(bar.time === preview.time ? preview : bar))
    );
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
        from: history.length - 30,
        to: history.length + 4
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
    ["right append only", [1, 2, 3], 1],
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
        from: historical.length - 30,
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
    expect(chartMocks.candles.setData).toHaveBeenLastCalledWith(
        [...historical, next].map(renderedBar)
    );

    view.rerender(
        <PriceChart
            barSemantic={specification}
            bars={historical}
            contextKey="revision-a"
            liveBar={{ ...last, close: "999", numeric: { ...last.numeric, close: 999 } }}
        />
    );
    expect(chartMocks.candles.setData).toHaveBeenLastCalledWith(
        [...historical, next].map(renderedBar)
    );
});

it("renders no invented candles in an unconfigured workspace", async () => {
    renderWorkspace(marketDataClient({ listSources: () => Promise.resolve([]) }));

    await waitFor(() => {
        expect(renderedPrices()).toEqual([]);
    });
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(
            "尚未配置可用的行情来源，请先添加行情来源。"
        );
    });
    expect(screen.queryByTestId("real-overlay-note")).not.toBeInTheDocument();
});

it("never renders invented prices through a partial temporary window or a failed explicit re-read", async () => {
    const pending: {
        resolve: (window: MarketDataBars) => void;
        reject: (error: Error) => void;
    }[] = [];
    const acquisition = vi.fn<MarketDataApiClient["createAcquisition"]>();
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: () =>
            new Promise((resolve, reject) => {
                pending.push({ resolve, reject });
            }),
        createAcquisition: acquisition
    });
    renderWorkspace(client);
    const user = userEvent.setup();
    await selectSource(user);
    await selectBtcInstrument(user);
    expect(screen.getByTestId("market-data-status")).toHaveAttribute("data-status", "loading");
    expect(renderedPrices()).toEqual([]);
    act(() => {
        pending[0]?.resolve(incompleteBars());
    });
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveAttribute(
            "data-status",
            "incomplete"
        );
    });
    expect(renderedPrices()).toEqual([]);
    expect(acquisition).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "重新读取临时行情" }));
    expect(screen.getByTestId("market-data-status")).toHaveAttribute("data-status", "loading");
    act(() => {
        pending[1]?.reject(new MarketDataWebError("TRANSPORT_ERROR", "Provider unavailable"));
    });
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveAttribute("data-status", "failed");
    });
    expect(renderedPrices()).toEqual([]);
    expect(acquisition).not.toHaveBeenCalled();
    expect(chartMocks.overlays.setData).not.toHaveBeenCalled();
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
        expect(screen.getByTestId("market-data-source-tag")).toHaveTextContent("临时行情 · 仅内存");
    });
    expect(renderedPrices()).toEqual([...Array<number>(1999).fill(101), 102.5]);
    expect(chartMocks.overlays.setData).not.toHaveBeenCalled();
    expect(screen.queryByTestId("real-overlay-note")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /指标/ })).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.getByRole("button", { name: /因子/ })).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
    expect(screen.getByTestId("market-data-status")).toHaveTextContent("● 连接中");
    await user.click(
        within(screen.getByRole("toolbar", { name: "工作区面板" })).getByRole("button", {
            name: "检查器"
        })
    );
    const inspector = within(screen.getByRole("complementary", { name: "上下文面板" }));
    expect(inspector.getByText("test.market_data.live")).toBeVisible();
    expect(inspector.getByText(TEMPORARY_VECTOR_FINGERPRINT)).toBeVisible();
    expect(screen.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "2000"
    );
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

it("refuses temporary data for read-only credentials without falling back to retained data or acquisition", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "false");
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: (_reference, query) =>
            Promise.resolve(marketDataBarsForQuery(query, incompleteBars()))
    });
    const acquisition = vi.spyOn(client, "createAcquisition");
    renderWorkspace(client);
    const user = userEvent.setup();
    await user.click(screen.getByText("本地只读访问", { exact: true }));
    await user.type(screen.getByLabelText("本地行情凭据"), "ee".repeat(32));
    await user.click(screen.getByRole("button", { name: "连接只读行情" }));
    await selectSource(user);
    await selectBtcInstrument(user);
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(
            "MARKET_DATA_ACCESS_DENIED"
        );
    });
    expect(acquisition).not.toHaveBeenCalled();
    expect(streams.requests).toEqual([]);
    expect(renderedPrices()).toEqual([]);
});

it.each([
    ["LOCAL_READ_UNAUTHORIZED", 401, true],
    ["MARKET_DATA_ACCESS_DENIED", 403, false]
] as const)(
    "offers a page reload only when the local session expires: %s",
    async (code, status, expired) => {
        const client = marketDataClient({
            listInstruments: () => Promise.resolve([marketDataInstrument()]),
            queryBars: () => Promise.reject(new MarketDataWebError(code, code, status))
        });
        const history = vi.spyOn(client, "queryBars");
        const acquisition = vi.spyOn(client, "createAcquisition");
        renderWorkspace(client);
        const user = userEvent.setup();
        await selectSource(user);
        await selectBtcInstrument(user);
        await waitFor(() => {
            expect(screen.getByTestId("market-data-status")).toHaveAttribute(
                "data-status",
                "failed"
            );
        });
        if (expired) {
            expect(screen.getByRole("link", { name: "重新载入页面" })).toHaveAttribute("href", "/");
            expect(screen.getByTestId("market-data-status")).toHaveTextContent("本地会话已失效");
            expect(
                screen.queryByRole("button", { name: "重新读取临时行情" })
            ).not.toBeInTheDocument();
        } else {
            expect(screen.queryByRole("link", { name: "重新载入页面" })).not.toBeInTheDocument();
            expect(screen.getByTestId("market-data-status")).toHaveTextContent(code);
        }
        expect(history).toHaveBeenCalledTimes(1);
        expect(acquisition).not.toHaveBeenCalled();
        expect(streams.requests).toEqual([]);
        expect(renderedPrices()).toEqual([]);
    }
);

it("shows an honest partial temporary window and offers explicit re-read without automatic collection", async () => {
    let available = false;
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: (_reference, query) =>
            Promise.resolve(marketDataBarsForQuery(query, available ? {} : incompleteBars()))
    });
    const acquisition = vi.spyOn(client, "createAcquisition");
    renderWorkspace(client);
    const user = userEvent.setup();
    await selectSource(user);
    await selectBtcInstrument(user);
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent("临时行情窗口不完整");
    });
    expect(acquisition).not.toHaveBeenCalled();
    expect(renderedPrices()).toEqual([]);
    available = true;
    await user.click(screen.getByRole("button", { name: "重新读取临时行情" }));
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready");
    });
    expect(acquisition).not.toHaveBeenCalled();
    expect(renderedPrices()).toEqual([...Array<number>(1999).fill(101), 102.5]);
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
        "Fixture Source · 当前 Revision · aaaaaaaa · 可采集",
        "Testnet Source · 当前 Revision · aaaaaaaa · 可采集"
    ]);
});
