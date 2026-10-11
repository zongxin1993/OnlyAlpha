import { FetchMarketDataApiClient, MarketDataWebError } from "./client";
import { LocalReadCredentials } from "./localReadCredentials";
import { marketDataBarSemantic } from "./model";
import {
    FIXTURE_REFERENCE,
    marketDataAcquisition,
    marketDataBars,
    marketDataInstrument,
    marketDataSource
} from "../../test/marketDataClient";

const json = (body: unknown, status = 200): Response =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const instrumentList = {
    schema_version: 1 as const,
    source_selection: marketDataBars().source_selection,
    instruments: [marketDataInstrument()]
};

const sources = { schema_version: 1 as const, sources: [marketDataSource()] };

const query = {
    instrument_id: "BTCUSDT.TEST",
    anchor_kind: "BEFORE_TIME" as const,
    before_ns: "1767225720000000000",
    target_bar_count: 2,
    bar_semantic: marketDataBarSemantic(1)
};

const acquisitionQuery = {
    instrument_id: query.instrument_id,
    start_ns: "1767225600000000000",
    end_ns: query.before_ns,
    bar_semantic: query.bar_semantic
};

function stubFetch(response: Response): ReturnType<typeof vi.fn> {
    const fetchMock = vi.fn(() => Promise.resolve(response));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
}

afterEach(() => {
    vi.unstubAllGlobals();
});

it("uses memory-only bearer headers for every read, never as Acquisition authority", async () => {
    const credentials = new LocalReadCredentials();
    const token = "ee".repeat(32);
    credentials.replace(token);
    const fetchMock = vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(json(sources))
        .mockResolvedValueOnce(json(instrumentList))
        .mockResolvedValueOnce(json(marketDataBars()))
        .mockResolvedValueOnce(json(marketDataAcquisition()))
        .mockResolvedValueOnce(json(marketDataAcquisition()));
    vi.stubGlobal("fetch", fetchMock);
    const client = new FetchMarketDataApiClient(credentials);
    await client.listSources();
    await client.listInstruments(FIXTURE_REFERENCE, "BTC");
    await client.queryBars(FIXTURE_REFERENCE, query);
    await client.getAcquisition(FIXTURE_REFERENCE, "a");
    await client.createAcquisition(FIXTURE_REFERENCE, acquisitionQuery);
    for (const [url, init] of fetchMock.mock.calls.slice(0, 4)) {
        expect(url instanceof Request ? url.url : url.toString()).not.toContain(token);
        expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${token}`);
        expect(init?.credentials).toBe("omit");
    }
    expect(new Headers(fetchMock.mock.calls[4]?.[1]?.headers).has("Authorization")).toBe(false);
    expect(JSON.stringify(credentials)).toBe("{}");
});

it.each(["logout", "replacement", "restored-token"])(
    "fences delayed Source reads after %s without relying on abort",
    async (operation) => {
        const credentials = new LocalReadCredentials();
        const token = "ee".repeat(32);
        credentials.replace(token);
        let release!: (response: Response) => void;
        vi.stubGlobal(
            "fetch",
            vi.fn(
                () =>
                    new Promise<Response>((resolve) => {
                        release = resolve;
                    })
            )
        );
        const pending = new FetchMarketDataApiClient(credentials).listSources();
        credentials.replace(operation === "replacement" ? "ff".repeat(32) : null);
        if (operation === "restored-token") credentials.replace(token);
        release(json(sources));
        await expect(pending).rejects.toMatchObject({ code: "LOCAL_READ_GENERATION_CHANGED" });
    }
);

it("reads the eligible source projection from the formal Product query", async () => {
    const fetchMock = stubFetch(json(sources));
    const found = await new FetchMarketDataApiClient().listSources();

    expect(found).toEqual([marketDataSource()]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v2/market-data/sources");
});

it("sends only the exact Revision reference and never asserts canonical source identity", async () => {
    const fetchMock = stubFetch(json(instrumentList));
    const instruments = await new FetchMarketDataApiClient().listInstruments(
        FIXTURE_REFERENCE,
        "BTC"
    );

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost");
    expect(url.pathname).toBe("/api/v2/market/instruments");
    expect(Object.fromEntries(url.searchParams)).toEqual({
        integration_id: FIXTURE_REFERENCE.integration_id,
        integration_revision_fingerprint: FIXTURE_REFERENCE.integration_revision_fingerprint,
        expected_type_id: FIXTURE_REFERENCE.expected_type_id,
        query: "BTC"
    });
    expect(instruments).toEqual([marketDataInstrument()]);
});

it.each([
    { integration_id: "foreign-integration" },
    { integration_revision_fingerprint: "b".repeat(64) },
    { type_id: "foreign.market_data" }
])("rejects instrument responses for a different exact source reference: %j", async (mutation) => {
    stubFetch(
        json({
            ...instrumentList,
            source_selection: { ...instrumentList.source_selection, ...mutation }
        })
    );
    await expect(
        new FetchMarketDataApiClient().listInstruments(FIXTURE_REFERENCE, "BTCUSDT")
    ).rejects.toMatchObject({ code: "CONTRACT_ERROR" });
});

it("omits an absent type guard and projects the server-derived canonical identity", async () => {
    const fetchMock = stubFetch(json(marketDataBars()));
    const bars = await new FetchMarketDataApiClient().queryBars(
        { ...FIXTURE_REFERENCE, expected_type_id: undefined },
        query
    );

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost");
    expect(url.searchParams.has("expected_type_id")).toBe(false);
    expect(JSON.parse(url.searchParams.get("bar_semantic") ?? "null")).toEqual(
        marketDataBarSemantic(1)
    );
    expect(url.searchParams.get("anchor_kind")).toBe("BEFORE_TIME");
    expect(url.searchParams.get("before_ns")).toBe(query.before_ns);
    expect(url.searchParams.get("target_bar_count")).toBe("2");
    expect(url.searchParams.has("start_ns")).toBe(false);
    expect(bars.source_selection.source_id).toBe("test.market_data.live");
    expect(bars.history_projection_fingerprint).toBe("8".repeat(64));
});

it("rejects a historical response with a different Bar Semantic", async () => {
    stubFetch(
        json(
            marketDataBars({
                bar_semantic: marketDataBarSemantic(7)
            })
        )
    );
    await expect(
        new FetchMarketDataApiClient().queryBars(FIXTURE_REFERENCE, query)
    ).rejects.toMatchObject({
        code: "MARKET_DATA_HISTORY_RESPONSE_MISMATCH"
    });
});

it("accepts incomplete history with verified partial Revision evidence", async () => {
    const complete = marketDataBars();
    stubFetch(
        json({
            ...complete,
            coverage: {
                ...complete.coverage,
                status: "INCOMPLETE",
                actual_bar_count: 1,
                issues: ["BAR_GRID_INCOMPLETE"],
                gaps: [{ start_ns: query.before_ns, end_ns: "1767225780000000000" }],
                planned_acquisition_ranges: [
                    { start_ns: query.before_ns, end_ns: "1767225780000000000" }
                ]
            },
            bars: [],
            history_projection_fingerprint: null,
            derived_projection_fingerprint: null,
            resume_after_sequence: null,
            resume_plan_fingerprint: null
        })
    );

    const partial = await new FetchMarketDataApiClient().queryBars(FIXTURE_REFERENCE, query);
    expect(partial.coverage.status).toBe("INCOMPLETE");
    expect(partial.revision_evidence).toEqual(complete.revision_evidence);
});

it("posts an acquisition command carrying a source reference rather than a source selection", async () => {
    const fetchMock = stubFetch(json(marketDataAcquisition()));
    const acquisition = await new FetchMarketDataApiClient().createAcquisition(
        FIXTURE_REFERENCE,
        acquisitionQuery
    );

    expect(acquisition.status).toBe("COMPLETE");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    expect(init?.method).toBe("POST");
    expect(body).toEqual({
        source_reference: FIXTURE_REFERENCE,
        instrument_id: query.instrument_id,
        start_ns: acquisitionQuery.start_ns,
        end_ns: acquisitionQuery.end_ns,
        bar_semantic: marketDataBarSemantic(1),
        provenance: "REST_BACKFILL"
    });
});

it("reads exact acquisition status by reference", async () => {
    const fetchMock = stubFetch(
        json(marketDataAcquisition({ status: "FAILED", failure_detail: "X" }))
    );
    const acquisition = await new FetchMarketDataApiClient().getAcquisition(
        FIXTURE_REFERENCE,
        "acquisition:" + "b".repeat(64)
    );

    expect(acquisition.status).toBe("FAILED");
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
        "/api/v2/market-data/acquisitions/acquisition%3A" + "b".repeat(64)
    );
});

it("maps Product and transport failures to explicit Market Data errors", async () => {
    stubFetch(
        json(
            { error: { phase: "QUERY", code: "MARKET_DATA_CATALOG_UNAVAILABLE", detail: "down" } },
            503
        )
    );
    await expect(new FetchMarketDataApiClient().listSources()).rejects.toMatchObject({
        code: "MARKET_DATA_CATALOG_UNAVAILABLE",
        status: 503
    });

    stubFetch(json({ schema_version: 1, sources: [{ nope: true }] }));
    await expect(new FetchMarketDataApiClient().listSources()).rejects.toBeInstanceOf(
        MarketDataWebError
    );
    await expect(new FetchMarketDataApiClient().listSources()).rejects.toMatchObject({
        code: "CONTRACT_ERROR"
    });

    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.reject(new Error("offline")))
    );
    await expect(new FetchMarketDataApiClient().listSources()).rejects.toMatchObject({
        code: "TRANSPORT_ERROR"
    });
});
