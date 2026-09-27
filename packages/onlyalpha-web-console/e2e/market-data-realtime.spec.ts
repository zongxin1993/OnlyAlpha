import { expect, test, type Page, type Route, type WebSocketRoute } from "@playwright/test";

const integrationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const integrationRevision = "a".repeat(64);
const historicalRevision = "d".repeat(64);
const sourceId = "binance.spot.market_data.us";
const minuteNs = BigInt("60000000000");

const source = {
    integration_id: integrationId,
    integration_revision_fingerprint: integrationRevision,
    display_name: "Binance Spot US",
    type_id: "binance.spot.market_data",
    source_id: sourceId,
    environment: "US"
};
const instrument = {
    instrument_id: "BTCUSDT.BINANCE",
    display_symbol: "BTCUSDT",
    venue: "BINANCE",
    market: "SPOT",
    asset_class: "CRYPTOCURRENCY",
    instrument_type: "CRYPTO_SPOT",
    status: "ACTIVE",
    market_data_capabilities: ["BAR_1M_EXTERNAL_RAW"]
};

const json = (route: Route, body: unknown) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });

async function controlledRealtime(page: Page) {
    let socket: WebSocketRoute | null = null;
    let connections = 0;
    const cursors: string[] = [];
    await page.route("**/api/v2/**", (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/v2/market-data/sources")
            return json(route, { schema_version: 1, sources: [source] });
        if (url.pathname === "/api/v2/market/instruments")
            return json(route, {
                schema_version: 1,
                source_selection: {
                    integration_id: integrationId,
                    integration_revision_fingerprint: integrationRevision,
                    type_id: source.type_id,
                    source_id: sourceId,
                    environment: "US"
                },
                instruments: [instrument]
            });
        if (url.pathname === "/api/v2/market-data/bars") {
            const start = BigInt(url.searchParams.get("start_ns") ?? "0");
            const end = url.searchParams.get("end_ns") ?? "0";
            const bar = (offset: bigint, close: string) => ({
                bar_start_ns: (start + offset).toString(),
                bar_end_ns: (start + offset + minuteNs).toString(),
                open: "100",
                high: "103",
                low: "99",
                close,
                volume: "2",
                closed: true
            });
            return json(route, {
                schema_version: 1,
                source_selection: {
                    integration_id: integrationId,
                    integration_revision_fingerprint: integrationRevision,
                    type_id: source.type_id,
                    source_id: sourceId,
                    environment: "US"
                },
                instrument_id: instrument.instrument_id,
                display_symbol: instrument.display_symbol,
                venue: instrument.venue,
                market: instrument.market,
                bar_specification: "1m",
                aggregation_source: "EXTERNAL",
                adjustment: "RAW",
                closed_only: true,
                start_ns: start.toString(),
                end_ns: end,
                coverage: {
                    status: "COMPLETE",
                    manifest_id: "manifest",
                    manifest_fingerprint: "c".repeat(64),
                    expected_bar_count: 1440,
                    actual_bar_count: 1440,
                    issues: [],
                    gaps: [],
                    planned_acquisition_ranges: []
                },
                revision_id: "revision",
                revision_fingerprint: historicalRevision,
                seal_id: "seal",
                bars: [bar(BigInt(0), "101"), bar(minuteNs, "102")]
            });
        }
        return route.fallback();
    });
    await page.routeWebSocket("**/api/v2/market-data/stream", (ws) => {
        socket = ws;
        const connection = ++connections;
        ws.onMessage((message) => {
            const request = JSON.parse(String(message)) as { resume_after_sequence: string };
            cursors.push(request.resume_after_sequence);
            const send = (event: object) => {
                ws.send(JSON.stringify({ schema_version: 1, ...event }));
            };
            send({
                event: "SUBSCRIBED",
                stream_id: `stream-${String(connection)}`,
                source_id: sourceId,
                instrument_id: instrument.instrument_id
            });
            send({ event: "STATE", state: "RECOVERING" });
            const sequence = (BigInt(request.resume_after_sequence) + BigInt(1)).toString();
            send({
                event: "BAR_CLOSED",
                source_id: sourceId,
                instrument_id: instrument.instrument_id,
                bar_specification: "1m",
                sequence,
                bar: {
                    bar_start_ns: (
                        BigInt(sequence) *
                        BigInt(60) *
                        BigInt(1_000_000_000)
                    ).toString(),
                    bar_end_ns: (
                        (BigInt(sequence) + BigInt(1)) *
                        BigInt(60) *
                        BigInt(1_000_000_000)
                    ).toString(),
                    open: "102",
                    high: "104",
                    low: "101",
                    close: "103",
                    volume: "3",
                    closed: true
                }
            });
            setTimeout(
                () => {
                    send({ event: "STATE", state: "READY" });
                },
                connection === 1 ? 0 : 500
            );
        });
    });
    return {
        cursors,
        disconnect: async () => {
            await socket?.close({ code: 1012, reason: "controlled disconnect" });
        }
    };
}

test("history to realtime rollover and reconnect gap repair — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await fixture.disconnect();
    await expect(page.getByTestId("market-data-status")).toContainText("● 行情中断");
    await expect(page.getByTestId("market-data-status")).toContainText("● 恢复中");
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.cursors).toHaveLength(2);
    expect(BigInt(fixture.cursors[1] ?? "0")).toBe(BigInt(fixture.cursors[0] ?? "0") + BigInt(1));
});
