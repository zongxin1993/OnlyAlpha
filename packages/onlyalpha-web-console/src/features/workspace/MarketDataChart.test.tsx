import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProviders } from "../../app/providers";
import { MarketDataWebError } from "../../api/marketData/client";
import type { MarketDataApiClient } from "../../api/marketData/client";
import type { MarketDataAcquisition, MarketDataBars } from "../../api/marketData/model";
import { buildPlaceholderBars } from "../../charts/lightweight/placeholderBars";
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
    marketDataClient,
    marketDataSource,
    marketDataInstrument
} from "../../test/marketDataClient";
import { researchClient } from "../../test/researchClient";
import { onlyBarsToCandles, onlyRecentClosedMinuteRange } from "./useMarketDataChart";
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
    const candles = { setData: vi.fn<(bars: readonly unknown[]) => void>() };
    const overlays = { setData: vi.fn<(points: readonly unknown[]) => void>() };
    const addSeries = vi.fn<(definition: string) => typeof candles>((definition) =>
        definition === "Candlestick" ? candles : overlays
    );
    const created = { addSeries, timeScale: () => ({ fitContent: vi.fn() }), remove: vi.fn() };
    return {
        candles,
        overlays,
        addSeries,
        createChart: vi.fn<() => typeof created>(() => created)
    };
});

vi.mock("lightweight-charts", () => ({
    CandlestickSeries: "Candlestick",
    LineSeries: "Line",
    ColorType: { Solid: "solid" },
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
    chartMocks.overlays.setData.mockClear();
});

it("requests and renders exact minute-aligned nanoseconds on the canonical 1m grid", () => {
    const range = onlyRecentClosedMinuteRange(Date.UTC(2026, 0, 1, 0, 0, 30), 3_600);
    expect(range.endNs).toBe("1767225600000000000");
    expect(range.startNs).toBe("1767222000000000000");
    expect(BigInt(range.endNs) % 60_000_000_000n).toBe(0n);
    expect(onlyBarsToCandles(marketDataBars().bars)).toEqual([
        { time: 1_767_225_600, open: 100, high: 102, low: 99, close: 101 },
        { time: 1_767_225_660, open: 101, high: 103, low: 100, close: 102.5 }
    ]);
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
        queryBars: () => Promise.resolve(marketDataBars())
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
        /test\.market_data\.live · canonical Revision dddddddddddd/
    );
});

it("requests an explicit acquisition for incomplete coverage and then renders database bars", async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: () => {
            calls.push("bars");
            return Promise.resolve(calls.length === 1 ? incompleteBars() : marketDataBars());
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
