import { requiredValue } from "../../test/requiredValue";
import { openTemporaryMarketDataStream } from "../../api/marketData/temporaryStream";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppProviders } from "../../app/providers";
import {
    marketDataClient,
    marketDataSource,
    marketDataInstrument
} from "../../test/marketDataClient";
import { integrationClient } from "../../test/integrationClient";
import { temporaryWindowForQuery } from "../../test/temporaryMarketDataClient";
import { readTemporaryMarketData } from "../../api/marketData/temporary";
import { marketDataBarSemantic } from "../../api/marketData/model";
import { WorkspacePage } from "./WorkspacePage";
vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: () => <div data-testid="price-chart" />
}));
vi.mock("../../api/marketData/temporary", () => ({ readTemporaryMarketData: vi.fn() }));
vi.mock("../../api/marketData/temporaryStream", () => ({
    openTemporaryMarketDataStream: vi.fn(() => vi.fn())
}));
afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    sessionStorage.clear();
});
it("restores saved selection, saves only after an explicit click, and reloads configuration through its normal button", async () => {
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    vi.mocked(readTemporaryMarketData).mockImplementation((_c, r, q) =>
        Promise.resolve(temporaryWindowForQuery(r, q))
    );
    const source = marketDataSource();
    const configuration = {
        source: {
            integration_id: source.integration_id,
            integration_revision_fingerprint: source.integration_revision_fingerprint,
            expected_type_id: source.type_id
        },
        instrument_id: "BTCUSDT.TEST",
        bar_semantic: marketDataBarSemantic(7),
        studies: []
    };
    let book = { schema_version: 2, version: 1, configuration };
    const writes: unknown[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (url === "/api/v2/workspace") {
                    if (init?.method === "PUT") {
                        if (typeof init.body !== "string")
                            throw new Error("Expected JSON save intent");
                        const body = JSON.parse(init.body) as {
                            configuration: typeof configuration;
                        };
                        writes.push(body);
                        book = {
                            ...book,
                            version: book.version + 1,
                            configuration: body.configuration
                        };
                    }
                    return new Response(JSON.stringify(book));
                }
                if (url === "/api/v2/watchlists")
                    return new Response(
                        JSON.stringify({ schema_version: 2, version: 0, lists: [] })
                    );
                throw new Error(`unexpected technical test request: ${url}`);
            })
        )
    );
    render(
        <AppProviders
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient({
                listInstruments: () => Promise.resolve([marketDataInstrument()])
            })}
        >
            <WorkspacePage />
        </AppProviders>
    );
    await waitFor(() => {
        expect(readTemporaryMarketData).toHaveBeenCalled();
    });
    expect(writes).toHaveLength(0);
    expect(vi.mocked(readTemporaryMarketData).mock.calls[0]?.[2].bar_semantic).toEqual(
        marketDataBarSemantic(7)
    );
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox", { name: "时间周期" }), "1");
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "保存默认工作区" })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "保存默认工作区" }));
    await waitFor(() => {
        expect(writes).toHaveLength(1);
    });
    expect(writes[0]).toMatchObject({
        expected_version: 1,
        configuration: { ...configuration, bar_semantic: marketDataBarSemantic(1) }
    });
    expect(writes[0]).not.toHaveProperty("bars");
    expect(vi.mocked(readTemporaryMarketData).mock.calls).toHaveLength(2);
    book = { ...book, version: 3, configuration };
    await user.click(screen.getByRole("button", { name: "载入已保存工作区" }));
    await waitFor(() => {
        expect(vi.mocked(readTemporaryMarketData).mock.calls.at(-1)?.[2].bar_semantic).toEqual(
            marketDataBarSemantic(7)
        );
    });
    await waitFor(() => {
        expect(openTemporaryMarketDataStream).toHaveBeenCalledTimes(3);
    });
    act(() => {
        requiredValue(vi.mocked(openTemporaryMarketDataStream).mock.calls.at(-1))[1]({
            schema_version: 2,
            event: "ERROR",
            code: "MARKET_DATA_SOURCE_TIMEOUT",
            detail: "timeout"
        });
    });
    expect(screen.getByRole("button", { name: "重新读取临时行情" })).toBeVisible();
    const reads = vi.mocked(readTemporaryMarketData).mock.calls.length;
    await user.click(screen.getByRole("button", { name: "重新读取临时行情" }));
    await waitFor(() => {
        expect(readTemporaryMarketData).toHaveBeenCalledTimes(reads + 1);
    });
});
