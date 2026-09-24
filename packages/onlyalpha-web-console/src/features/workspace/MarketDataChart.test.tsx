import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CandlestickData, UTCTimestamp } from "lightweight-charts";
import { AppProviders } from "../../app/providers";
import { MarketDataWebError } from "../../api/marketData/client";
import type { MarketDataApiClient } from "../../api/marketData/client";
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
    marketDataInstrument
} from "../../test/marketDataClient";
import { researchClient } from "../../test/researchClient";
import { WorkspacePage } from "./WorkspacePage";

const chartProps: { bars?: readonly CandlestickData<UTCTimestamp>[] | undefined }[] = [];

vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: (props: {
        readonly bars?: readonly CandlestickData<UTCTimestamp>[] | undefined;
    }) => {
        chartProps.push(props);
        return <div data-testid="price-chart">chart</div>;
    }
}));

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
    chartProps.length = 0;
});

it("loads instruments and bars from the Market Data Product API instead of the shell list", async () => {
    const user = userEvent.setup();
    const queries: string[] = [];
    const client = marketDataClient({
        listInstruments: (_selection, query) => {
            queries.push(query);
            return Promise.resolve([marketDataInstrument()]);
        },
        queryBars: () => Promise.resolve(marketDataBars())
    });
    renderWorkspace(client);

    await selectSource(user);
    await selectBtcInstrument(user);

    expect(queries).toEqual(["BTC"]);
    expect(screen.queryByRole("button", { name: /600519\.SH/ })).not.toBeInTheDocument();
    expect(await screen.findByText(/BTCUSDT\.TEST · SPOT/)).toBeInTheDocument();
    await waitFor(() => {
        expect(screen.getByTestId("market-data-source-tag")).toHaveTextContent("real · DB");
    });
    const last = chartProps.at(-1);
    expect(last?.bars?.map((bar) => bar.close)).toEqual([101, 102.5]);
    expect(screen.getByTestId("market-data-status")).toHaveTextContent(
        /canonical Revision dddddddddddd/
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
    expect(chartProps.at(-1)?.bars?.length).toBe(2);
});

it("never renders placeholder bars when the acquisition fails", async () => {
    const user = userEvent.setup();
    const client = marketDataClient({
        listInstruments: () => Promise.resolve([marketDataInstrument()]),
        queryBars: () => Promise.resolve(incompleteBars()),
        createAcquisition: () =>
            Promise.resolve(
                marketDataAcquisition({
                    status: "FAILED",
                    coverage: incompleteBars().coverage,
                    revision_id: null,
                    revision_fingerprint: null,
                    seal_id: null,
                    failure_detail: "OnlyBinanceError:BINANCE_HTTP_ERROR"
                })
            )
    });
    renderWorkspace(client);

    await selectSource(user);
    await selectBtcInstrument(user);

    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(/历史行情同步失败/);
    });
    expect(chartProps.at(-1)?.bars).toBeUndefined();
    expect(screen.getByTestId("market-data-status").closest(".chart-region")).not.toBeNull();
    expect(screen.getAllByText("synthetic").length).toBeGreaterThan(0);
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
    expect(chartProps.at(-1)?.bars).toBeUndefined();
});
