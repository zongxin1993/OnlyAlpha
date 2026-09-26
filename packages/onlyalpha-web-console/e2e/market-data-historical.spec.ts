import { expect, test, type Page, type Route } from "@playwright/test";

const integrationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const revision = "a".repeat(64);
const revisionFingerprint = "d".repeat(64);
const minuteNs = BigInt("60000000000");

const source = {
    integration_id: integrationId,
    integration_revision_fingerprint: revision,
    display_name: "Binance Spot LIVE",
    type_id: "binance.spot.market_data",
    source_id: "binance.spot.market_data.live",
    environment: "LIVE"
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

interface Range {
    readonly start_ns: string;
    readonly end_ns: string;
}
type FixtureMode = "empty" | "complete" | "tail";

function json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function coverage(range: Range, complete: boolean, planned: readonly Range[] = []) {
    return {
        status: complete ? "COMPLETE" : "INCOMPLETE",
        manifest_id: complete ? `manifest:${"c".repeat(64)}` : null,
        manifest_fingerprint: complete ? "c".repeat(64) : null,
        expected_bar_count: 1440,
        actual_bar_count: complete ? 1440 : 0,
        issues: complete ? [] : ["BAR_GRID_INCOMPLETE"],
        gaps: planned,
        planned_acquisition_ranges: planned
    };
}

function bars(range: Range, complete: boolean, planned: readonly Range[] = []) {
    const start = BigInt(range.start_ns);
    const point = (offset: bigint, open: string, close: string) => ({
        bar_start_ns: (start + offset).toString(),
        bar_end_ns: (start + offset + minuteNs).toString(),
        open,
        high: "102",
        low: "99",
        close,
        volume: "2",
        closed: true
    });
    return {
        schema_version: 1,
        source_selection: {
            integration_id: integrationId,
            integration_revision_fingerprint: revision,
            type_id: source.type_id,
            source_id: source.source_id,
            environment: source.environment
        },
        instrument_id: instrument.instrument_id,
        display_symbol: instrument.display_symbol,
        venue: instrument.venue,
        market: instrument.market,
        bar_specification: "1m",
        aggregation_source: "EXTERNAL",
        adjustment: "RAW",
        closed_only: true,
        ...range,
        coverage: coverage(range, complete, planned),
        revision_id: complete ? `market-data-revision:${revisionFingerprint}` : null,
        revision_fingerprint: complete ? revisionFingerprint : null,
        seal_id: complete ? `seal:${"e".repeat(64)}` : null,
        bars: complete ? [point(BigInt(0), "100", "101"), point(minuteNs, "101", "101.5")] : []
    };
}

async function controlledMarketData(page: Page, initial: FixtureMode) {
    let mode = initial;
    let acquisitionCount = 0;
    const providerRequests: Range[] = [];
    await page.route("**/api/v2/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.pathname === "/api/v2/market-data/sources")
            return json(route, { schema_version: 1, sources: [source] });
        if (url.pathname === "/api/v2/market/instruments")
            return json(route, {
                schema_version: 1,
                source_selection: bars({ start_ns: "0", end_ns: "1" }, true).source_selection,
                instruments: [instrument]
            });
        if (url.pathname === "/api/v2/market-data/bars") {
            const range = {
                start_ns: url.searchParams.get("start_ns") ?? "",
                end_ns: url.searchParams.get("end_ns") ?? ""
            };
            if (mode === "complete") return json(route, bars(range, true));
            const planned =
                mode === "tail"
                    ? [
                          {
                              start_ns: (BigInt(range.end_ns) - BigInt(2) * minuteNs).toString(),
                              end_ns: range.end_ns
                          }
                      ]
                    : [range];
            return json(route, bars(range, false, planned));
        }
        if (url.pathname === "/api/v2/market-data/acquisitions" && request.method() === "POST") {
            acquisitionCount += 1;
            const body = request.postDataJSON() as Range & { readonly instrument_id: string };
            const requested = { start_ns: body.start_ns, end_ns: body.end_ns };
            providerRequests.push(
                ...(mode === "tail"
                    ? [
                          {
                              start_ns: (BigInt(body.end_ns) - BigInt(2) * minuteNs).toString(),
                              end_ns: body.end_ns
                          }
                      ]
                    : [requested])
            );
            mode = "complete";
            return json(
                route,
                {
                    schema_version: 1,
                    acquisition_id: `acquisition:${"b".repeat(64)}`,
                    status: "COMPLETE",
                    source_id: source.source_id,
                    integration_binding_fingerprint: "f".repeat(64),
                    instrument_id: body.instrument_id,
                    bar_specification: "1m",
                    ...requested,
                    provenance: "REST_BACKFILL",
                    coverage: coverage(requested, true),
                    revision_id: `market-data-revision:${revisionFingerprint}`,
                    revision_fingerprint: revisionFingerprint,
                    seal_id: `seal:${"e".repeat(64)}`,
                    failure_detail: null
                },
                201
            );
        }
        return route.fallback();
    });
    return {
        acquisitionCount: () => acquisitionCount,
        providerRequests
    };
}

async function selectBtc(page: Page) {
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
}

test.describe("W1 historical golden path — CONTROLLED_TEST_EVIDENCE", () => {
    test("first load acquires canonical bars and reload does not reacquire complete history", async ({
        page
    }) => {
        const fixture = await controlledMarketData(page, "empty");
        await selectBtc(page);

        await expect(page.getByTestId("market-data-source-tag")).toHaveText("real · DB");
        await expect(page.getByTestId("market-data-status")).toContainText(
            `canonical Revision ${revisionFingerprint.slice(0, 12)}`
        );
        await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("1m");
        await expect(page.getByRole("combobox", { name: "时间周期" })).toBeDisabled();
        await expect(page.locator(".chart-region .synthetic-tag")).toHaveCount(0);
        await expect(page.getByRole("button", { name: /指标/ })).toBeDisabled();
        await expect(page.getByRole("button", { name: /因子/ })).toBeDisabled();
        expect(fixture.acquisitionCount()).toBe(1);

        await page.reload();
        await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
        await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
        await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
        await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
        await expect(page.getByTestId("market-data-source-tag")).toHaveText("real · DB");
        expect(fixture.acquisitionCount()).toBe(1);
    });

    test("a tail gap requests only the missing provider range", async ({ page }) => {
        const fixture = await controlledMarketData(page, "tail");
        await selectBtc(page);
        await expect(page.getByTestId("market-data-source-tag")).toHaveText("real · DB");

        expect(fixture.acquisitionCount()).toBe(1);
        expect(fixture.providerRequests).toHaveLength(1);
        const requested = fixture.providerRequests[0];
        expect(BigInt(requested.end_ns) - BigInt(requested.start_ns)).toBe(BigInt(2) * minuteNs);
    });
});
