import { FetchMarketDiscoveryClient } from "./discovery";
import { LocalReadCredentials } from "./localReadCredentials";
import {
    FIXTURE_SELECTION,
    marketDataInstrument,
    marketDataSource
} from "../../test/marketDataClient";

const search = () => ({
    schema_version: 1,
    results: [{ source_selection: FIXTURE_SELECTION, instrument: marketDataInstrument() }],
    sources: [
        {
            source_selection: FIXTURE_SELECTION,
            status: "COMPLETE",
            asset_classes: ["CRYPTOCURRENCY"],
            truncated: false
        }
    ],
    truncated: false
});
afterEach(() => vi.unstubAllGlobals());

it("rejects orphaned and duplicate search results rather than presenting selectable identities", async () => {
    const client = new FetchMarketDiscoveryClient(new LocalReadCredentials(true));
    for (const body of [
        { ...search(), sources: [] },
        { ...search(), results: [...search().results, ...search().results] },
        { ...search(), sources: [{ ...search().sources[0], status: "TIMEOUT" }] }
    ]) {
        vi.stubGlobal(
            "fetch",
            vi.fn(() => Promise.resolve(new Response(JSON.stringify(body))))
        );
        await expect(client.search("BTC", "", new AbortController().signal)).rejects.toThrow();
    }
});

it("keeps partial source failure distinct from empty results and fences credential replacement", async () => {
    const credentials = new LocalReadCredentials(true);
    const client = new FetchMarketDiscoveryClient(credentials);
    const body = {
        ...search(),
        results: [],
        sources: [{ ...search().sources[0], status: "TIMEOUT" }]
    };
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response(JSON.stringify(body))))
    );
    expect((await client.search("BTC", "")).sources[0]?.status).toBe("TIMEOUT");
    vi.stubGlobal(
        "fetch",
        vi.fn(() => {
            credentials.replace(null);
            return Promise.resolve(new Response(JSON.stringify(search())));
        })
    );
    await expect(client.search("BTC", "")).rejects.toThrow("本地访问已改变");
});

it("rejects quote responses from another source or another set of instruments", async () => {
    const client = new FetchMarketDiscoveryClient(new LocalReadCredentials(true));
    const quote = {
        instrument_id: "BTCUSDT.TEST",
        status: "AVAILABLE",
        last_price: "12.34",
        change_pct: "-1.2",
        change_basis: "ROLLING_24H",
        ts_event_ns: "1767225720000000000"
    };
    for (const body of [
        {
            schema_version: 1,
            source_selection: { ...FIXTURE_SELECTION, source_id: "other" },
            status: "COMPLETE",
            quotes: [quote]
        },
        {
            schema_version: 1,
            source_selection: FIXTURE_SELECTION,
            status: "COMPLETE",
            quotes: [{ ...quote, instrument_id: "ETHUSDT.TEST" }]
        },
        {
            schema_version: 1,
            source_selection: FIXTURE_SELECTION,
            status: "TIMEOUT",
            quotes: [quote]
        }
    ]) {
        vi.stubGlobal(
            "fetch",
            vi.fn(() => Promise.resolve(new Response(JSON.stringify(body))))
        );
        await expect(client.quotes(marketDataSource(), ["BTCUSDT.TEST"])).rejects.toThrow();
    }
});
