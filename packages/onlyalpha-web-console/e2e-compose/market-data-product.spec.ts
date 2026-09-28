import { expect, test, type Page } from "@playwright/test";

const minuteNs = BigInt("60000000000");

const lastMatch = <T>(values: readonly T[], predicate: (value: T) => boolean): T | undefined =>
    [...values].reverse().find(predicate);

async function matchingProductEvidence(
    observed: ReturnType<typeof observeProduct>,
    durationMinutes: number,
    mode: "PROVIDER_NATIVE" | "DERIVED"
) {
    await expect
        .poll(
            () => {
                const http = lastMatch(
                    observed.bars,
                    (value) =>
                        (
                            value.bar_semantic as
                                { formation?: { window_minutes?: number } } | undefined
                        )?.formation?.window_minutes === durationMinutes
                );
                return observed.subscribed.some(
                    (value) =>
                        value.resolution_mode === mode &&
                        value.resolution_plan_fingerprint === http?.resolution_plan_fingerprint
                );
            },
            { timeout: 45_000 }
        )
        .toBe(true);
    const http = lastMatch(
        observed.bars,
        (value) =>
            (value.bar_semantic as { formation?: { window_minutes?: number } } | undefined)
                ?.formation?.window_minutes === durationMinutes
    );
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
    page.on("response", async (response) => {
        const url = new URL(response.url());
        if (url.pathname === "/api/v2/market-data/bars" && response.ok()) {
            requests.push(url);
            bars.push((await response.json()) as Record<string, unknown>);
        }
    });
    page.on("websocket", (socket) => {
        socket.on("framereceived", ({ payload }) => {
            const value = JSON.parse(String(payload)) as Record<string, unknown>;
            if (value.event === "SUBSCRIBED") subscribed.push(value);
        });
    });
    return { bars, subscribed, requests };
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

test("real Browser uses one native 15m resolution across HTTP and stream", async ({ page }) => {
    test.setTimeout(120_000);
    await scenario(page);
    const observed = observeProduct(page);
    const integrationId = await provision(page, "Native 15m Product Vertical");
    await openBtc(page, integrationId);
    await scenario(page);

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("15");
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    const { http, stream } = await matchingProductEvidence(observed, 15, "PROVIDER_NATIVE");
    expect(http).toMatchObject({
        resolution_mode: "PROVIDER_NATIVE",
        base_revision_id: null
    });
    expect(http?.resolution_plan_fingerprint).toBe(stream?.resolution_plan_fingerprint);
    expect(http?.construction_fingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(stream).toMatchObject({
        resolution_mode: "PROVIDER_NATIVE",
        cursor_bar_stride_minutes: 15
    });
    const provider = await stats(page);
    expect(provider.kline_requests.length).toBeGreaterThan(0);
    expect(provider.kline_requests.every((request) => request.interval === "15m")).toBe(true);
    expect(provider.stream_requests).toContain("btcusdt@kline_15m");
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
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    const { http, stream } = await matchingProductEvidence(observed, 7, "DERIVED");
    expect(http).toMatchObject({
        resolution_mode: "DERIVED",
        aggregation_semantics_version: "TIME_BAR_V1"
    });
    expect(http?.base_revision_id).toBe(http?.revision_id);
    expect(http?.resolution_plan_fingerprint).toBe(stream?.resolution_plan_fingerprint);
    expect(stream).toMatchObject({
        resolution_mode: "DERIVED",
        cursor_bar_stride_minutes: 1
    });
    expect(BigInt(String(http?.resume_after_sequence))).toBe(
        BigInt(String(http?.end_ns)) / minuteNs - BigInt(1)
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
