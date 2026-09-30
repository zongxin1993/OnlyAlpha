import { expect, test, type Page, type Route } from "@playwright/test";

const integrationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const revision = "a".repeat(64);
const revisionFingerprint = "d".repeat(64);
const historyFingerprint = "8".repeat(64);
const minuteNs = BigInt("60000000000");
const fixtureRange = {
    start_ns: "1767225600000000000",
    end_ns: "1767312000000000000"
};
const nativeSteps = new Set([1, 3, 5, 15, 30, 60, 120, 240]);
const semantic = (durationMinutes: number) => ({
    schema_version: 2,
    formation: {
        schema_version: 1,
        kind: "FIXED_DURATION",
        window_minutes: durationMinutes,
        stride_minutes: durationMinutes,
        alignment: "SESSION_START"
    },
    price_type: "LAST",
    adjustment_policy: "RAW"
});

const source = {
    integration_id: integrationId,
    integration_revision_fingerprint: revision,
    display_name: "Binance Spot LIVE",
    type_id: "binance.spot.market_data",
    source_id: "binance.spot.market_data.live",
    environment: "LIVE",
    time_bar_capability: {
        provider_base_semantic: semantic(1),
        derived_algorithm: "TIME_BAR@1",
        minimum_window_minutes: 1,
        maximum_window_minutes: 240
    }
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

function bars(
    range: Range,
    complete: boolean,
    planned: readonly Range[] = [],
    step = 1,
    anchorKind: "LATEST_CLOSED" | "BEFORE_TIME" = "LATEST_CLOSED",
    targetBarCount = 1440
) {
    const native = nativeSteps.has(step);
    const start = BigInt(range.start_ns);
    const duration = BigInt(step) * minuteNs;
    const day = BigInt(1_440) * minuteNs;
    const dayStart = (start / day) * day;
    const aligned = dayStart + ((start - dayStart + duration - BigInt(1)) / duration) * duration;
    const point = (offset: bigint, open: string, close: string) => ({
        bar_start_ns: (aligned + offset).toString(),
        bar_end_ns: (aligned + offset + duration).toString(),
        open,
        high: "102",
        low: "99",
        close,
        volume: "2",
        closed: true
    });
    const count = Math.min(targetBarCount, Number((BigInt(range.end_ns) - aligned) / duration));
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
        bar_semantic: semantic(step),
        closed_only: true,
        anchor_kind: anchorKind,
        requested_before_ns: anchorKind === "BEFORE_TIME" ? range.end_ns : null,
        requested_bar_count: targetBarCount,
        resolved_start_ns: range.start_ns,
        resolved_end_ns: range.end_ns,
        coverage: coverage(range, complete, planned),
        revision_evidence: complete
            ? [
                  {
                      revision_id: `market-data-revision:${revisionFingerprint}`,
                      revision_fingerprint: revisionFingerprint,
                      manifest_id: `manifest:${"c".repeat(64)}`,
                      manifest_fingerprint: "c".repeat(64),
                      seal_id: `seal:${"e".repeat(64)}`,
                      covered_start_ns: range.start_ns,
                      covered_end_ns: range.end_ns
                  }
              ]
            : [],
        history_projection_fingerprint: complete ? historyFingerprint : null,
        derived_projection_fingerprint: complete && !native ? "9".repeat(64) : null,
        aggregation_semantics_version: native ? null : "TIME_BAR_V1",
        calendar_fingerprint: native ? null : "a".repeat(64),
        resolution_mode: native ? "PROVIDER_NATIVE" : "DERIVED",
        resolution_plan_fingerprint: step.toString(16).padStart(64, "0"),
        resume_after_sequence: complete
            ? (BigInt(range.end_ns) / minuteNs - BigInt(1)).toString()
            : null,
        resume_plan_fingerprint: complete ? step.toString(16).padStart(64, "0") : null,
        bars: complete
            ? Array.from({ length: count }, (_, index) =>
                  point(BigInt(index) * duration, "100", "101")
              )
            : []
    };
}

async function controlledMarketData(page: Page, initial: FixtureMode, holdOlder = false) {
    let mode = initial;
    let acquisitionCount = 0;
    const providerRequests: Range[] = [];
    const queriedSteps: number[] = [];
    const queriedAnchors: string[] = [];
    const olderRequests: URL[] = [];
    let releaseOlder!: () => void;
    const olderBarrier = new Promise<void>((resolve) => {
        releaseOlder = resolve;
    });
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
            const requested = JSON.parse(
                url.searchParams.get("bar_semantic") ?? "null"
            ) as ReturnType<typeof semantic>;
            const step = requested.formation.window_minutes;
            queriedSteps.push(step);
            const anchor = url.searchParams.get("anchor_kind");
            expect(anchor === "LATEST_CLOSED" || anchor === "BEFORE_TIME").toBe(true);
            queriedAnchors.push(anchor ?? "");
            const targetCount = Number(url.searchParams.get("target_bar_count"));
            expect([1440, 240]).toContain(targetCount);
            expect(url.searchParams.has("start_ns")).toBe(false);
            if (targetCount === 240) {
                expect(anchor).toBe("BEFORE_TIME");
                const before = url.searchParams.get("before_ns");
                expect(before).not.toBeNull();
                olderRequests.push(url);
                if (before === null) throw new Error("older query requires before_ns");
                const end = BigInt(before);
                const olderRange = {
                    start_ns: (end - BigInt(240 * step) * minuteNs).toString(),
                    end_ns: end.toString()
                };
                if (holdOlder) await olderBarrier;
                return json(route, bars(olderRange, true, [], step, "BEFORE_TIME", 240));
            }
            expect(targetCount).toBe(1440);
            const range = fixtureRange;
            if (anchor === "BEFORE_TIME")
                expect(url.searchParams.get("before_ns")).toBe(range.end_ns);
            if (mode === "complete")
                return json(
                    route,
                    bars(range, true, [], step, anchor as "LATEST_CLOSED" | "BEFORE_TIME")
                );
            const planned =
                mode === "tail"
                    ? [
                          {
                              start_ns: (BigInt(range.end_ns) - BigInt(2) * minuteNs).toString(),
                              end_ns: range.end_ns
                          }
                      ]
                    : [range];
            return json(route, bars(range, false, planned, step));
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
                    bar_semantic: semantic(1),
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
        providerRequests,
        queriedSteps,
        queriedAnchors,
        olderRequests,
        releaseOlder
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
    test("chart type preserves exact context and crosshair reads Product OHLCV", async ({
        page
    }) => {
        const errors: string[] = [];
        page.on("pageerror", (error) => errors.push(error.message));
        const fixture = await controlledMarketData(page, "complete");
        await selectBtc(page);
        const status = page.getByTestId("market-data-status");
        const chart = page.getByTestId("price-chart");
        const observation = page.getByTestId("market-data-observation");
        await expect(status).toHaveAttribute("data-loaded-bar-count", "1440");
        await expect(observation).toHaveAttribute("data-observation-mode", "latest-closed");
        const count = fixture.queriedAnchors.length;
        const acquisitions = fixture.acquisitionCount();
        const range = await chart.getAttribute("data-visible-range-from");
        const rangeTo = await chart.getAttribute("data-visible-range-to");
        const anchor = await chart.getAttribute("data-visible-anchor-time");
        await expect(chart).toHaveAttribute("data-chart-type", "CANDLESTICK");
        for (const type of ["LINE", "CANDLESTICK"]) {
            await page.getByRole("combobox", { name: "图表类型" }).selectOption(type);
            await expect(chart).toHaveAttribute("data-chart-type", type);
            await expect(chart).toHaveAttribute("data-visible-range-from", range ?? "");
            await expect(chart).toHaveAttribute("data-visible-range-to", rangeTo ?? "");
            await expect(chart).toHaveAttribute("data-visible-anchor-time", anchor ?? "");
            await expect(status).toHaveAttribute("data-loaded-bar-count", "1440");
            expect(fixture.queriedAnchors).toHaveLength(count);
            expect(fixture.acquisitionCount()).toBe(acquisitions);
        }
        const bounds = await chart.boundingBox();
        if (bounds === null) throw new Error("price chart bounds unavailable");
        await page.mouse.move(bounds.x + bounds.width * 0.5, bounds.y + bounds.height * 0.5);
        await expect(observation).toHaveAttribute("data-observation-mode", "crosshair");
        const start = await observation.getAttribute("data-bar-start-ns");
        const selected = bars(fixtureRange, true).bars.find((bar) => bar.bar_start_ns === start);
        expect(selected).toBeDefined();
        if (selected === undefined) throw new Error("selected Bar missing from Product response");
        for (const field of ["open", "high", "low", "close", "volume"] as const)
            await expect(observation.locator(`[data-observation-field="${field}"]`)).toHaveText(
                selected[field]
            );
        await test.info().attach("exact-crosshair-observation", {
            contentType: "image/png",
            body: await page.screenshot({
                path: test.info().outputPath("exact-crosshair-observation.png")
            })
        });
        const context = await observation.getAttribute("data-chart-context-key");
        await page.mouse.move(0, 0);
        await expect(observation).toHaveAttribute("data-observation-mode", "latest-closed");
        await page.getByRole("combobox", { name: "时间周期" }).selectOption("5");
        await expect(observation).not.toHaveAttribute("data-chart-context-key", context ?? "");
        await expect(observation).toHaveAttribute("data-observation-mode", "latest-closed");
        expect(errors).toEqual([]);
    });
    test("first load acquires canonical bars and reload does not reacquire complete history", async ({
        page
    }) => {
        const fixture = await controlledMarketData(page, "empty");
        await selectBtc(page);

        await expect(page.getByTestId("market-data-source-tag")).toHaveText("real · DB");
        expect((await page.getByTestId("price-chart").boundingBox())?.height).toBeGreaterThan(100);
        expect(
            (await page.getByTestId("price-chart").locator("canvas").first().boundingBox())?.height
        ).toBeGreaterThan(100);
        await expect(page.getByTestId("market-data-status")).toContainText(
            `历史投影 ${historyFingerprint.slice(0, 12)}`
        );
        await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("1");
        await expect(page.getByRole("combobox", { name: "时间周期" })).toBeEnabled();
        await expect(page.locator(".chart-region .synthetic-tag")).toHaveCount(0);
        await expect(page.getByRole("button", { name: /指标/ })).toBeDisabled();
        await expect(page.getByRole("button", { name: /因子/ })).toBeDisabled();
        expect(fixture.acquisitionCount()).toBe(1);
        expect(fixture.queriedAnchors.slice(0, 2)).toEqual(["LATEST_CLOSED", "BEFORE_TIME"]);
        expect(fixture.olderRequests).toHaveLength(0);
        await expect(page.getByTestId("market-data-status")).toHaveAttribute(
            "data-older-history-status",
            "idle"
        );

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

    test("custom 7m and 37m switch through typed history without a provider multi-period fetch", async ({
        page
    }) => {
        const fixture = await controlledMarketData(page, "complete");
        await selectBtc(page);
        await page.getByRole("combobox", { name: "时间周期" }).selectOption("custom");
        await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("7");
        await page.getByRole("button", { name: "应用" }).click();
        await expect.poll(() => fixture.queriedSteps[fixture.queriedSteps.length - 1]).toBe(7);
        await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("37");
        await page.getByRole("button", { name: "应用" }).click();
        await expect.poll(() => fixture.queriedSteps[fixture.queriedSteps.length - 1]).toBe(37);
        expect(fixture.acquisitionCount()).toBe(0);
    });
});

test("an explicit viewport crossing freezes one 240-Bar request while in flight", async ({
    page
}) => {
    const fixture = await controlledMarketData(page, "complete", true);
    await selectBtc(page);
    const status = page.getByTestId("market-data-status");
    await expect(status).toHaveAttribute("data-loaded-bar-count", "1440");
    await expect(status).toHaveAttribute("data-older-history-status", "idle");
    expect(fixture.olderRequests).toHaveLength(0);
    const chart = page.getByTestId("price-chart");
    const bounds = await chart.boundingBox();
    if (bounds === null) throw new Error("price chart bounds unavailable");
    const pan = async (direction = 1) => {
        await page.mouse.move(
            bounds.x + bounds.width * (direction > 0 ? 0.3 : 0.9),
            bounds.y + bounds.height * 0.5
        );
        await page.mouse.down();
        await page.mouse.move(
            bounds.x + bounds.width * (direction > 0 ? 0.9 : 0.3),
            bounds.y + bounds.height * 0.5,
            { steps: 8 }
        );
        await page.mouse.up();
    };
    for (let index = 0; index < 32 && fixture.olderRequests.length === 0; index += 1) await pan();
    await expect.poll(() => fixture.olderRequests.length).toBe(1);
    await expect(status).toHaveAttribute("data-older-history-status", "loading");
    await pan(-1);
    await pan();
    expect(fixture.olderRequests).toHaveLength(1);
    fixture.releaseOlder();
    await expect(status).toHaveAttribute("data-loaded-bar-count", "1680");
    await expect(status).toHaveAttribute("data-older-history-status", "idle");
});
