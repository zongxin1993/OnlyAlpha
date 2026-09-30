import { expect, test, type Page } from "@playwright/test";

const minuteNs = BigInt("60000000000");

const lastMatch = <T>(values: readonly T[], predicate: (value: T) => boolean): T | undefined =>
    [...values].reverse().find(predicate);

async function matchingProductEvidence(
    observed: ReturnType<typeof observeProduct>,
    durationMinutes: number,
    mode: "PROVIDER_NATIVE" | "DERIVED"
) {
    const matchesHttp = (value: Record<string, unknown>) =>
        (value.bar_semantic as { formation?: { window_minutes?: number } } | undefined)?.formation
            ?.window_minutes === durationMinutes &&
        value.resolution_mode === mode &&
        (
            value.coverage as
                | { status?: string; expected_bar_count?: number; actual_bar_count?: number }
                | undefined
        )?.status === "COMPLETE" &&
        (value.coverage as { expected_bar_count?: number } | undefined)?.expected_bar_count ===
            1440 &&
        (value.coverage as { actual_bar_count?: number } | undefined)?.actual_bar_count === 1440 &&
        Array.isArray(value.bars) &&
        value.bars.length === 1440 &&
        Array.isArray(value.revision_evidence) &&
        value.revision_evidence.length > 0 &&
        typeof value.history_projection_fingerprint === "string" &&
        /^[0-9a-f]{64}$/.test(value.history_projection_fingerprint);
    await expect
        .poll(
            () => {
                const http = lastMatch(observed.bars, matchesHttp);
                return observed.subscribed.some(
                    (value) =>
                        value.resolution_mode === mode &&
                        value.resolution_plan_fingerprint === http?.resolution_plan_fingerprint
                );
            },
            { timeout: 45_000 }
        )
        .toBe(true);
    const http = lastMatch(observed.bars, matchesHttp);
    return {
        http,
        stream: lastMatch(
            observed.subscribed,
            (value) =>
                value.resolution_mode === mode &&
                value.resolution_plan_fingerprint === http?.resolution_plan_fingerprint
        )
    };
}

const scenario = async (page: Page) => {
    const response = await page.request.put("http://binance-probe-fixture:8080/scenario/ALL_PASS");
    expect(response.ok(), await response.text()).toBeTruthy();
};

async function provision(page: Page, name: string): Promise<string> {
    await page.goto("/data/sources/new");
    await page.getByRole("button", { name: /Binance Spot Market Data/ }).click();
    await page.getByLabel("显示名称").fill(name);
    const created = page.waitForResponse(
        (response) =>
            response.url().endsWith("/api/v2/integrations") &&
            response.request().method() === "POST"
    );
    await page.getByRole("button", { name: "创建数据源" }).click();
    const createdPayload = (await (await created).json()) as { integration_id: string };
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await page.getByRole("combobox", { name: "Endpoint Profile" }).selectOption("STANDARD");
    await page.getByRole("button", { name: "保存草稿" }).click();
    await expect(page.getByRole("button", { name: "保存草稿" })).toBeEnabled();
    await page.getByRole("button", { name: "发布 Revision", exact: true }).click();
    await expect(page.getByRole("button", { name: "发布 Revision", exact: true })).toBeEnabled();
    const probe = page.getByRole("button", { name: "测试连接" });
    await probe.click();
    await expect(probe).toBeEnabled({ timeout: 30_000 });
    await expect(page.getByRole("region", { name: "运行状态" })).toContainText("READY", {
        timeout: 30_000
    });
    return createdPayload.integration_id;
}

async function openBtc(page: Page, integrationId: string): Promise<void> {
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时", {
        timeout: 45_000
    });
}

function observeProduct(page: Page) {
    const bars: Record<string, unknown>[] = [];
    const subscribed: Record<string, unknown>[] = [];
    const requests: URL[] = [];
    const acquisitions: URL[] = [];
    const subscriptions: Record<string, unknown>[] = [];
    page.on("request", (request) => {
        const url = new URL(request.url());
        if (url.pathname === "/api/v2/market-data/bars") requests.push(url);
    });
    page.on("response", async (response) => {
        const url = new URL(response.url());
        if (url.pathname === "/api/v2/market-data/bars" && response.ok()) {
            bars.push((await response.json()) as Record<string, unknown>);
        }
        if (
            url.pathname === "/api/v2/market-data/acquisitions" &&
            response.request().method() === "POST"
        )
            acquisitions.push(url);
    });
    page.on("websocket", (socket) => {
        socket.on("framesent", ({ payload }) => {
            const value = JSON.parse(String(payload)) as Record<string, unknown>;
            if (value.operation === "SUBSCRIBE_BAR") subscriptions.push(value);
        });
        socket.on("framereceived", ({ payload }) => {
            const value = JSON.parse(String(payload)) as Record<string, unknown>;
            if (value.event === "SUBSCRIBED") subscribed.push(value);
        });
    });
    return { acquisitions, bars, subscribed, requests, subscriptions };
}

async function stats(page: Page) {
    const response = await page.request.get(
        "http://binance-probe-fixture:8080/__onlyalpha_e2e__/market-data-stats"
    );
    expect(response.ok(), await response.text()).toBeTruthy();
    return (await response.json()) as {
        kline_requests: { interval: string }[];
        stream_requests: string[];
    };
}

async function panChartToOlderHistory(
    page: Page,
    dragCount: number,
    stop?: () => boolean
): Promise<void> {
    const bounds = await page.getByTestId("price-chart").boundingBox();
    if (bounds === null) throw new Error("price chart bounds unavailable");
    for (let index = 0; index < dragCount; index += 1) {
        if (stop?.()) break;
        const from = Number(
            await page.getByTestId("price-chart").getAttribute("data-visible-range-from")
        );
        const distance = Math.min(bounds.width * 0.6, Math.max(8, (from - 12) * 7));
        await page.mouse.move(bounds.x + bounds.width * 0.3, bounds.y + bounds.height * 0.5);
        await page.mouse.down();
        await page.mouse.move(
            bounds.x + bounds.width * 0.3 + distance,
            bounds.y + bounds.height * 0.5,
            {
                steps: 4
            }
        );
        await page.mouse.up();
    }
}

test("real Browser uses one native 15m resolution across HTTP and stream", async ({ page }) => {
    test.setTimeout(120_000);
    await scenario(page);
    const observed = observeProduct(page);
    const integrationId = await provision(page, "Native 15m Product Vertical");
    await openBtc(page, integrationId);
    await scenario(page);

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("15");
    const { http, stream } = await matchingProductEvidence(observed, 15, "PROVIDER_NATIVE");
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(http).toMatchObject({
        requested_bar_count: 1440,
        coverage: {
            status: "COMPLETE",
            expected_bar_count: 1440,
            actual_bar_count: 1440
        },
        resolution_mode: "PROVIDER_NATIVE",
        derived_projection_fingerprint: null
    });
    expect((http?.bars as unknown[] | undefined)?.length).toBe(1440);
    expect(http?.history_projection_fingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect((http?.revision_evidence as unknown[] | undefined)?.length).toBeGreaterThan(0);
    expect(http?.resolution_plan_fingerprint).toBe(stream?.resolution_plan_fingerprint);
    expect(stream).toMatchObject({
        resolution_mode: "PROVIDER_NATIVE",
        cursor_bar_stride_minutes: 15
    });
    const provider = await stats(page);
    expect(provider.kline_requests.length).toBeGreaterThan(0);
    expect(provider.kline_requests.every((request) => request.interval === "15m")).toBe(true);
    expect(provider.stream_requests).toContain("btcusdt@kline_15m");
});

test("real Browser loads authoritative older native history without moving the viewport", async ({
    page
}) => {
    test.setTimeout(120_000);
    await scenario(page);
    const observed = observeProduct(page);
    const integrationId = await provision(page, "Native Viewport History Vertical");
    await openBtc(page, integrationId);
    await scenario(page);
    await page.getByRole("combobox", { name: "时间周期" }).selectOption("15");
    const { http } = await matchingProductEvidence(observed, 15, "PROVIDER_NATIVE");
    const status = page.getByTestId("market-data-status");
    await expect
        .poll(async () => Number(await status.getAttribute("data-loaded-bar-count")), {
            timeout: 45_000
        })
        .toBeGreaterThanOrEqual(1440);
    const initialBarCount = Number(await status.getAttribute("data-loaded-bar-count"));
    await expect(status).toHaveAttribute("data-older-history-status", "idle");
    expect(
        observed.requests.filter((url) => url.searchParams.get("target_bar_count") === "240")
    ).toHaveLength(0);
    const matchingSubscriptions = () =>
        observed.subscriptions.filter(
            (value) =>
                (value.source_reference as { integration_id?: string }).integration_id ===
                    integrationId &&
                (value.source_reference as { integration_revision_fingerprint?: string })
                    .integration_revision_fingerprint ===
                    (http?.source_selection as { integration_revision_fingerprint?: string })
                        .integration_revision_fingerprint &&
                value.instrument_id === http?.instrument_id &&
                JSON.stringify(value.bar_semantic) === JSON.stringify(http?.bar_semantic)
        );
    const matchingSubscribed = () =>
        observed.subscribed.filter(
            (value) =>
                value.source_id === (http?.source_selection as { source_id?: string }).source_id &&
                value.instrument_id === http?.instrument_id &&
                value.resolution_plan_fingerprint === http?.resolution_plan_fingerprint
        );
    expect(matchingSubscriptions()).toHaveLength(1);
    expect(matchingSubscribed()).toHaveLength(1);
    const subscriptionsBefore = matchingSubscriptions().length;
    const subscribedBefore = matchingSubscribed().length;
    await scenario(page);
    const initialAcquisitionCount = observed.acquisitions.length;
    const initialRequestCount = observed.requests.length;

    let releaseFirstBeforeRequest: () => void = () => undefined;
    const release = new Promise<void>((resolve) => {
        releaseFirstBeforeRequest = resolve;
    });
    let beforeRequestCount = 0;
    let firstResponseHeld = false;
    await page.route("**/api/v2/market-data/bars?**", async (route) => {
        const url = new URL(route.request().url());
        if (
            url.searchParams.get("anchor_kind") === "BEFORE_TIME" &&
            url.searchParams.get("target_bar_count") === "240"
        ) {
            beforeRequestCount += 1;
            if (beforeRequestCount === 1) {
                const response = await route.fetch();
                firstResponseHeld = true;
                await release;
                await route.fulfill({ response });
                return;
            }
        }
        await route.continue();
    });

    await panChartToOlderHistory(page, 32, () => beforeRequestCount > 0);
    await expect.poll(() => beforeRequestCount, { timeout: 45_000 }).toBe(1);
    await expect.poll(() => firstResponseHeld, { timeout: 45_000 }).toBe(true);

    const chart = page.getByTestId("price-chart");
    const bounds = await chart.boundingBox();
    if (bounds === null) throw new Error("price chart bounds unavailable");
    const anchorBefore = await chart.getAttribute("data-visible-anchor-time");
    const rangeBefore = Number(await chart.getAttribute("data-visible-range-from"));
    expect(anchorBefore).toMatch(/^[0-9]+$/);
    expect(rangeBefore).toBeGreaterThanOrEqual(0);
    // Actual away → left crossings re-enter the same frozen page, then return to the anchor.
    for (let index = 0; index < 3; index += 1) {
        const x = bounds.x + bounds.width * 0.65;
        const y = bounds.y + bounds.height * 0.5;
        await page.mouse.move(x, y);
        await page.mouse.down();
        await page.mouse.move(x - 240, y, { steps: 8 });
        await page.mouse.up();
        await expect
            .poll(async () => Number(await chart.getAttribute("data-visible-range-from")))
            .toBeGreaterThan(24);
        await page.mouse.down();
        await page.mouse.move(x, y, { steps: 8 });
        await page.mouse.up();
        await expect
            .poll(async () => Number(await chart.getAttribute("data-visible-range-from")))
            .toBeLessThanOrEqual(24);
    }
    expect(beforeRequestCount).toBe(1);
    if (anchorBefore === null) throw new Error("visible anchor unavailable");
    await expect(chart).toHaveAttribute("data-visible-anchor-time", anchorBefore);
    releaseFirstBeforeRequest();

    await expect
        .poll(async () => Number(await status.getAttribute("data-loaded-bar-count")), {
            timeout: 45_000
        })
        .toBeGreaterThan(initialBarCount);
    await expect(status).toHaveAttribute("data-older-history-status", "idle");
    const firstOlderBarCount = Number(await status.getAttribute("data-loaded-bar-count"));
    await expect(chart).toHaveAttribute("data-visible-anchor-time", anchorBefore);
    expect(Number(await chart.getAttribute("data-visible-range-from"))).toBeGreaterThan(
        rangeBefore
    );
    expect(matchingSubscriptions()).toHaveLength(subscriptionsBefore);
    expect(matchingSubscribed()).toHaveLength(subscribedBefore);
    await test.info().attach("viewport-continuity", {
        contentType: "application/json",
        body: JSON.stringify({
            anchorBefore,
            anchorAfter: await chart.getAttribute("data-visible-anchor-time"),
            subscriptionsBefore,
            subscriptionsAfter: matchingSubscriptions().length,
            subscribedBefore,
            subscribedAfter: matchingSubscribed().length
        })
    });

    await panChartToOlderHistory(page, 32, () => beforeRequestCount > 2);
    await expect.poll(() => beforeRequestCount, { timeout: 45_000 }).toBeGreaterThan(2);
    await expect
        .poll(async () => Number(await status.getAttribute("data-loaded-bar-count")), {
            timeout: 45_000
        })
        .toBeGreaterThan(firstOlderBarCount);
    await expect(status).toHaveAttribute("data-older-history-status", "idle");
    await expect(status).toContainText("● 实时");

    const olderRequests = observed.requests
        .slice(initialRequestCount)
        .filter((url) => url.searchParams.get("anchor_kind") === "BEFORE_TIME");
    expect(olderRequests.length).toBeGreaterThanOrEqual(2);
    expect(olderRequests.every((url) => url.searchParams.get("target_bar_count") === "240")).toBe(
        true
    );
    expect(
        observed.bars.some(
            (value) =>
                value.anchor_kind === "BEFORE_TIME" &&
                (value.coverage as { status?: string } | undefined)?.status === "INCOMPLETE" &&
                ((value.coverage as { planned_acquisition_ranges?: unknown[] } | undefined)
                    ?.planned_acquisition_ranges?.length ?? 0) > 0
        )
    ).toBe(true);
    expect(observed.acquisitions.length).toBeGreaterThan(initialAcquisitionCount);
    expect((await stats(page)).kline_requests.length).toBeGreaterThan(0);
});

test("real Browser keeps derived 7m intent while Product uses base 1m", async ({ page }) => {
    test.setTimeout(120_000);
    await scenario(page);
    const observed = observeProduct(page);
    const integrationId = await provision(page, "Derived 7m Product Vertical");
    await openBtc(page, integrationId);
    await scenario(page);

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("custom");
    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("7");
    await page.getByRole("button", { name: "应用" }).click();
    const { http, stream } = await matchingProductEvidence(observed, 7, "DERIVED");
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(http).toMatchObject({
        requested_bar_count: 1440,
        coverage: {
            status: "COMPLETE",
            expected_bar_count: 1440,
            actual_bar_count: 1440
        },
        resolution_mode: "DERIVED",
        aggregation_semantics_version: "TIME_BAR_V1"
    });
    expect((http?.bars as unknown[] | undefined)?.length).toBe(1440);
    expect(http?.history_projection_fingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(http?.derived_projection_fingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect((http?.revision_evidence as unknown[] | undefined)?.length).toBeGreaterThan(0);
    expect(http?.resolution_plan_fingerprint).toBe(stream?.resolution_plan_fingerprint);
    expect(stream).toMatchObject({
        resolution_mode: "DERIVED",
        cursor_bar_stride_minutes: 1
    });
    expect(BigInt(String(http?.resume_after_sequence))).toBe(
        BigInt(String(http?.resolved_end_ns)) / minuteNs - BigInt(1)
    );
    expect(
        observed.requests
            .filter((url) => url.searchParams.get("bar_semantic")?.includes('"window_minutes":7'))
            .every((url) => !url.searchParams.has("base_step"))
    ).toBe(true);
    const provider = await stats(page);
    expect(provider.kline_requests.length).toBeGreaterThan(0);
    expect(provider.kline_requests.every((request) => request.interval === "1m")).toBe(true);
    expect(provider.stream_requests).toContain("btcusdt@kline_1m");
});
