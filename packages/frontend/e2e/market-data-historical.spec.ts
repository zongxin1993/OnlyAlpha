import { expect, test, type Page, type Route } from "@playwright/test";

const integrationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const revision = "a".repeat(64);
const minuteNs = BigInt("60000000000");
// One fixed aligned window end in the past; LATEST_CLOSED reads always resolve at or before it.
const bootstrapEnd = "1767312000000000000";
const nativeSteps = new Set([1, 3, 5, 15, 30, 60, 120, 240]);
const semantic = (durationMinutes: number) => ({
    schema_version: 3,
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
    is_current_revision: true,
    integration_id: integrationId,
    integration_revision_fingerprint: revision,
    display_name: "Binance Spot Market Data",
    type_id: "binance.spot.market_data",
    source_id: "binance.spot.market_data.live",
    environment: "GLOBAL",
    new_work_status: "AVAILABLE",
    new_work_unavailable_code: null,
    history_read_policy: "EXACT_SEALED_PROOF",
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

const selection = {
    integration_id: integrationId,
    integration_revision_fingerprint: revision,
    type_id: source.type_id,
    source_id: source.source_id,
    environment: source.environment
};

function json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

interface WindowRequest {
    readonly step: number;
    readonly target: number;
    readonly anchor: "LATEST_CLOSED" | "BEFORE_TIME";
    readonly before: string | null;
    readonly partial: boolean;
}

// A TemporaryMarketDataWindow exactly as api/marketData/temporary.ts admits it: request echo,
// bars+gaps tiling [resolved_start, resolved_end), and DISPLAY_ONLY provenance markers.
function temporaryWindow(request: WindowRequest) {
    const duration = BigInt(request.step) * minuteNs;
    const end = request.before === null ? BigInt(bootstrapEnd) : BigInt(request.before);
    const start = end - BigInt(request.target) * duration;
    const point = (offset: bigint) => ({
        bar_start_ns: (start + offset).toString(),
        bar_end_ns: (start + offset + duration).toString(),
        open: "100",
        high: "102",
        low: "99",
        close: "101",
        volume: "2",
        closed: true
    });
    const bars = request.partial
        ? Array.from({ length: request.target - 1 }, (_, index) => point((BigInt(index) + BigInt(1)) * duration))
        : Array.from({ length: request.target }, (_, index) => point(BigInt(index) * duration));
    const gaps = request.partial
        ? [{ start_ns: start.toString(), end_ns: (start + duration).toString() }]
        : [];
    const native = nativeSteps.has(request.step);
    return {
        schema_version: 1,
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        source_kind: "TEMPORARY_MARKET_DATA",
        anchor_kind: request.anchor,
        requested_before_ns: request.before,
        requested_bar_count: request.target,
        bar_semantic: semantic(request.step),
        instrument_id: instrument.instrument_id,
        source_selection: selection,
        resolved_start_ns: start.toString(),
        resolved_end_ns: end.toString(),
        calendar_fingerprint: "c".repeat(64),
        resolution_plan_fingerprint: request.step.toString(16).padStart(64, "0"),
        resolution_mode: native ? "PROVIDER_NATIVE" : "DERIVED",
        window_fingerprint: `${request.step.toString(16).padStart(4, "0")}${"f".repeat(60)}`,
        bars,
        coverage: {
            status: request.partial ? "PARTIAL" : "COMPLETE",
            expected_bar_count: request.target,
            actual_bar_count: bars.length,
            gaps
        }
    };
}

async function controlledMarketData(
    page: Page,
    initial: "complete" | "tail",
    holdOlder = false,
    sources = [source]
) {
    let mode = initial;
    const queriedSteps: number[] = [];
    const queriedAnchors: string[] = [];
    const olderRequests: URL[] = [];
    const temporaryRequests: URL[] = [];
    let releaseOlder!: () => void;
    const olderBarrier = new Promise<void>((resolve) => {
        releaseOlder = resolve;
    });
    await page.route("**/api/v2/**", async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/v2/market-data/sources")
            return json(route, { schema_version: 1, sources });
        if (url.pathname === "/api/v2/market/instruments")
            return json(route, {
                schema_version: 1,
                source_selection: selection,
                instruments: [instrument]
            });
        if (url.pathname === "/api/v2/chart/market-data/bars") {
            const requested = JSON.parse(
                url.searchParams.get("bar_semantic") ?? "null"
            ) as ReturnType<typeof semantic>;
            const step = requested.formation.window_minutes;
            queriedSteps.push(step);
            const anchor = url.searchParams.get("anchor_kind");
            if (anchor !== "LATEST_CLOSED" && anchor !== "BEFORE_TIME")
                throw new Error(`invalid anchor_kind ${String(anchor)}`);
            queriedAnchors.push(anchor);
            const target = Number(url.searchParams.get("target_bar_count"));
            expect([2000, 240]).toContain(target);
            expect(url.searchParams.has("start_ns")).toBe(false);
            const before = url.searchParams.get("before_ns");
            if (anchor === "BEFORE_TIME") expect(before).not.toBeNull();
            else expect(before).toBeNull();
            if (target === 240) {
                expect(anchor).toBe("BEFORE_TIME");
                if (before === null) throw new Error("older query requires before_ns");
                olderRequests.push(url);
                if (holdOlder) await olderBarrier;
                return json(
                    route,
                    temporaryWindow({ step, target, anchor, before, partial: false })
                );
            }
            expect(target).toBe(2000);
            temporaryRequests.push(url);
            // A Provider page may close PARTIAL; the loader pages with BEFORE_TIME at the
            // resolved end until a page is COMPLETE. Only the first LATEST page is PARTIAL.
            const partial = mode === "tail" && anchor === "LATEST_CLOSED";
            if (partial) mode = "complete";
            return json(route, temporaryWindow({ step, target, anchor, before, partial }));
        }
        return route.fallback();
    });
    return {
        queriedSteps,
        queriedAnchors,
        olderRequests,
        temporaryRequests,
        releaseOlder
    };
}

async function selectBtc(page: Page) {
    await page.goto("/");
    await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "2000"
    );
    // Existing full-history/viewport regressions explicitly select their 1m fixture.
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("1");
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "2000"
    );
}

test("default BTCUSDT workspace bootstraps only server identities and first 15m window", async ({
    page
}) => {
    const providerTraffic: string[] = [];
    page.on("request", (request) => {
        if (/binance\.(com|vision)/.test(new URL(request.url()).hostname))
            providerTraffic.push(request.url());
    });
    const fixture = await controlledMarketData(page, "complete");
    await page.goto("/");
    await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
    await expect(page.getByRole("button", { name: "搜索商品" })).toContainText("BTCUSDT");
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "2000"
    );
    expect(fixture.queriedSteps).toEqual([15]);
    expect(fixture.queriedAnchors).toEqual(["LATEST_CLOSED"]);
    await expect(page.getByRole("tooltip", { name: "K 线信息" })).toHaveCount(0);
    await expect(page.getByTestId("price-chart").locator("canvas").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "目录", exact: true })).toHaveAttribute(
        "aria-haspopup",
        "dialog"
    );
    await expect(page.getByTestId("calculation-handoff")).toHaveCount(0);
    await expect(
        page.getByText(/synthetic|600519|run-0f3a91|res-4d81|bt-2f5e18|MA 20|20 日动量/)
    ).toHaveCount(0);
    expect(providerTraffic).toEqual([]);
    await test.info().attach("server-derived-default-workspace", {
        contentType: "image/png",
        body: await page.screenshot({ path: test.info().outputPath("default-workspace.png") })
    });
});

test("ambiguous default sources require explicit choice without any Bar request", async ({
    page
}) => {
    const fixture = await controlledMarketData(page, "complete", false, [
        source,
        {
            ...source,
            integration_id: "other-live-source",
            integration_revision_fingerprint: "b".repeat(64)
        }
    ]);
    await page.goto("/");
    await expect(page.getByTestId("market-data-status")).toContainText(
        "请在左上角搜索并选择商品。"
    );
    expect(fixture.queriedSteps).toEqual([]);
    await expect(page.getByRole("tooltip", { name: "K 线信息" })).toHaveCount(0);
});

test("missing exact BTCUSDT member shows unavailable without requesting Bars", async ({ page }) => {
    const fixture = await controlledMarketData(page, "complete");
    await page.route("**/api/v2/market/instruments?**", (route) =>
        json(route, {
            schema_version: 1,
            source_selection: selection,
            instruments: [{ ...instrument, instrument_id: "BTCUSDT.OTHER" }]
        })
    );
    await page.goto("/");
    await expect(page.getByTestId("market-data-status")).toContainText(
        "当前数据源未提供 BTCUSDT.BINANCE"
    );
    expect(fixture.queriedSteps).toEqual([]);
    await expect(page.getByRole("tooltip", { name: "K 线信息" })).toHaveCount(0);
});

test("unavailable discovery is not misreported as absent configuration", async ({ page }) => {
    const fixture = await controlledMarketData(page, "complete");
    await page.route("**/api/v2/market-data/sources", (route) => route.abort("failed"));
    await page.goto("/");
    await expect(page.getByTestId("market-data-status")).toContainText("行情服务不可用");
    await expect(page.getByTestId("market-data-status")).not.toContainText("未配置可用");
    expect(fixture.queriedSteps).toEqual([]);
    await expect(page.getByRole("button", { name: "管理数据源", exact: true })).toBeVisible();
});

test("loading discovery has no invented candles before the source response", async ({ page }) => {
    const fixture = await controlledMarketData(page, "complete");
    let release!: () => void;
    const responseBarrier = new Promise<void>((resolve) => {
        release = resolve;
    });
    await page.route("**/api/v2/market-data/sources", async (route) => {
        await responseBarrier;
        await json(route, { schema_version: 1, sources: [source] });
    });
    await page.goto("/");
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "loading");
    await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
    await expect(page.getByRole("tooltip", { name: "K 线信息" })).toHaveCount(0);
    expect(fixture.queriedSteps).toEqual([]);
    release();
    await expect(page.getByTestId("market-data-status")).toHaveAttribute("data-status", "ready");
    expect(fixture.queriedSteps).toEqual([15]);
});

for (const width of [1440, 1024, 390]) {
    test(`unconfigured workspace stays honest and accessible at ${String(width)}px`, async ({
        page
    }) => {
        const fixture = await controlledMarketData(page, "complete", false, []);
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/");
        await expect(page.getByTestId("market-data-status")).toContainText(
            "尚未配置可用的行情来源，请先添加行情来源。"
        );
        await expect(page.getByRole("tooltip", { name: "K 线信息" })).toHaveCount(0);
        await expect(page.getByTestId("market-data-source-tag")).toHaveCount(0);
        await expect(page.getByRole("button", { name: "管理数据源", exact: true })).toBeVisible();
        await expect(
            page.getByRole("button", { name: "管理数据源", exact: true })
        ).toBeInViewport();
        await expect(page.getByRole("button", { name: "搜索商品" })).toBeInViewport();
        await expect(page.getByTestId("market-data-status")).toBeInViewport();
        await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
        expect(fixture.queriedSteps).toEqual([]);
        await expect(page.getByText(/synthetic|600519|1486\.20|run-0f3a91/)).toHaveCount(0);
        expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
        ).toBe(true);
        await test.info().attach("honest-configuration-state", {
            contentType: "image/png",
            body: await page.screenshot({
                path: test.info().outputPath(`configuration-${String(width)}.png`)
            })
        });
        await page.getByRole("button", { name: "管理数据源", exact: true }).click();
        await expect(page.getByRole("dialog", { name: "管理数据源" })).toBeVisible();
    });
}

test.describe("W1 historical golden path — CONTROLLED_TEST_EVIDENCE", () => {
    test("chart type preserves loaded context and crosshair reads Product OHLCV", async ({
        page
    }) => {
        const errors: string[] = [];
        page.on("pageerror", (error) => errors.push(error.message));
        const fixture = await controlledMarketData(page, "complete");
        await selectBtc(page);
        const status = page.getByTestId("market-data-status");
        const chart = page.getByTestId("price-chart");
        const observation = page.getByRole("tooltip", { name: "K 线信息" });
        await expect(status).toHaveAttribute("data-loaded-bar-count", "2000");
        await expect(observation).toHaveCount(0);
        const queries = fixture.queriedSteps.length;
        const context = await chart.getAttribute("data-chart-context-key");
        await expect(chart).toHaveAttribute("data-chart-type", "CANDLESTICK");
        for (const type of ["LINE", "CANDLESTICK"]) {
            await page.getByLabel("图表类型", { exact: true }).click();
            await page
                .getByRole("menuitem", { name: type === "LINE" ? "收盘线" : "蜡烛图", exact: true })
                .click();
            await expect(chart).toHaveAttribute("data-chart-type", type);
            await expect(status).toHaveAttribute("data-loaded-bar-count", "2000");
            expect(fixture.queriedSteps).toHaveLength(queries);
        }
        const bounds = await chart.boundingBox();
        if (bounds === null) throw new Error("price chart bounds unavailable");
        await page.mouse.move(bounds.x + bounds.width * 0.5, bounds.y + bounds.height * 0.5);
        await expect(observation).toBeVisible();
        const start = await observation.getAttribute("data-bar-start-ns");
        expect(start).not.toBeNull();
        if (start === null) throw new Error("crosshair observation missing bar identity");
        const duration = minuteNs;
        const aligned = (BigInt(bootstrapEnd) / duration) * duration;
        expect((BigInt(start) - aligned) % duration).toBe(BigInt(0));
        for (const [field, value] of [
            ["open", "100"],
            ["high", "102"],
            ["low", "99"],
            ["close", "101"],
            ["volume", "2"]
        ] as const)
            await expect(observation.locator(`[data-observation-field="${field}"]`)).toHaveText(
                value
            );
        await test.info().attach("exact-crosshair-observation", {
            contentType: "image/png",
            body: await page.screenshot({
                path: test.info().outputPath("exact-crosshair-observation.png")
            })
        });
        await page.mouse.move(0, 0);
        await expect(observation).toHaveCount(0);
        await page.getByRole("combobox", { name: "时间周期" }).selectOption("5");
        await expect(chart).not.toHaveAttribute("data-chart-context-key", context ?? "");
        await expect(observation).toHaveCount(0);
        expect(errors).toEqual([]);
    });
    test("first load reads one temporary window and reload re-reads without any Acquisition", async ({
        page
    }) => {
        const acquisitionTraffic: string[] = [];
        page.on("request", (request) => {
            if (request.method() === "POST" && request.url().includes("acquisition"))
                acquisitionTraffic.push(request.url());
        });
        const fixture = await controlledMarketData(page, "complete");
        await selectBtc(page);

        expect((await page.getByTestId("price-chart").boundingBox())?.height).toBeGreaterThan(100);
        expect(
            (await page.getByTestId("price-chart").locator("canvas").first().boundingBox())?.height
        ).toBeGreaterThan(100);
        await expect(page.getByTestId("market-data-status")).toHaveAttribute(
            "data-status",
            "ready"
        );
        await expect(page.getByTestId("market-data-status")).toContainText("行情已加载");
        await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("1");
        await expect(page.getByRole("combobox", { name: "时间周期" })).toBeEnabled();
        await expect(page.locator(".chart-region .synthetic-tag")).toHaveCount(0);
        await expect(page.getByRole("button", { name: "目录", exact: true })).toHaveAttribute(
            "aria-haspopup",
            "dialog"
        );
        await expect(page.getByTestId("calculation-handoff")).toHaveCount(0);
        expect(fixture.queriedAnchors).toEqual(["LATEST_CLOSED", "LATEST_CLOSED"]);
        expect(fixture.olderRequests).toHaveLength(0);
        await expect(page.getByTestId("market-data-status")).toHaveAttribute(
            "data-older-history-status",
            "idle"
        );

        await page.reload();
        await expect(page.getByTestId("market-data-status")).toHaveAttribute(
            "data-loaded-bar-count",
            "2000"
        );
        await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
        expect(acquisitionTraffic).toEqual([]);
    });

    test("an incomplete provider page pages forward with BEFORE_TIME until COMPLETE", async ({
        page
    }) => {
        const fixture = await controlledMarketData(page, "tail");
        await page.goto("/");
        await expect(page.getByTestId("market-data-status")).toHaveAttribute(
            "data-loaded-bar-count",
            "2000"
        );
        // Page 1 is LATEST_CLOSED PARTIAL; the loader pages with BEFORE_TIME at its resolved end.
        expect(fixture.queriedAnchors.slice(0, 2)).toEqual(["LATEST_CLOSED", "BEFORE_TIME"]);
        const second = fixture.temporaryRequests[1];
        expect(second.searchParams.get("before_ns")).toBe(bootstrapEnd);
        expect(fixture.olderRequests).toHaveLength(0);
    });

    test("custom 7m and 37m switch through typed temporary windows", async ({ page }) => {
        const fixture = await controlledMarketData(page, "complete");
        await selectBtc(page);
        await page.getByRole("combobox", { name: "时间周期" }).selectOption("custom");
        await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("7");
        await page.getByRole("button", { name: "应用" }).click();
        await expect.poll(() => fixture.queriedSteps[fixture.queriedSteps.length - 1]).toBe(7);
        await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("37");
        await page.getByRole("button", { name: "应用" }).click();
        await expect.poll(() => fixture.queriedSteps[fixture.queriedSteps.length - 1]).toBe(37);
        const lastWindow = fixture.temporaryRequests[fixture.temporaryRequests.length - 1];
        expect(lastWindow.searchParams.get("target_bar_count")).toBe("2000");
    });
});

test("an explicit viewport crossing freezes one 240-Bar request while in flight", async ({
    page
}) => {
    const fixture = await controlledMarketData(page, "complete", true);
    await selectBtc(page);
    const status = page.getByTestId("market-data-status");
    await expect(status).toHaveAttribute("data-loaded-bar-count", "2000");
    await expect(status).toHaveAttribute("data-older-history-status", "idle");
    expect(fixture.olderRequests).toHaveLength(0);
    const chart = page.getByTestId("price-chart");
    const bounds = await chart.boundingBox();
    if (bounds === null) throw new Error("price chart bounds unavailable");
    const pan = async (direction = 1) => {
        await page.mouse.move(
            bounds.x + bounds.width * (direction > 0 ? 0.05 : 0.95),
            bounds.y + bounds.height * 0.5
        );
        await page.mouse.down();
        await page.mouse.move(
            bounds.x + bounds.width * (direction > 0 ? 0.95 : 0.05),
            bounds.y + bounds.height * 0.5,
            { steps: 8 }
        );
        await page.mouse.up();
    };
    // The left-edge callback arms only after the view leaves the first 24 bars.
    await pan(-1);
    await pan(-1);
    const fromBeforeFirstPan = Number(await chart.getAttribute("data-visible-range-from"));
    await pan();
    expect(Number(await chart.getAttribute("data-visible-range-from"))).toBeLessThan(
        fromBeforeFirstPan
    );
    for (let index = 0; index < 48 && fixture.olderRequests.length === 0; index += 1) await pan();
    await expect.poll(() => fixture.olderRequests.length).toBe(1);
    await expect(status).toHaveAttribute("data-older-history-status", "loading");
    await pan(-1);
    await pan();
    expect(fixture.olderRequests).toHaveLength(1);
    fixture.releaseOlder();
    await expect(status).toHaveAttribute("data-loaded-bar-count", "2240");
    await expect(status).toHaveAttribute("data-older-history-status", "idle");
});
