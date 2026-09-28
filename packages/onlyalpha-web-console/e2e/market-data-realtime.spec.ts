import { expect, test, type Page, type Route, type WebSocketRoute } from "@playwright/test";

const integrationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const integrationRevision = "a".repeat(64);
const historicalRevision = "d".repeat(64);
const sourceId = "binance.spot.market_data.us";
const minuteNs = BigInt("60000000000");
const planFingerprint = (step: number) => step.toString(16).padStart(64, "0");
const nativeSteps = new Set([1, 3, 5, 15, 30, 60, 120, 240]);

const source = {
    integration_id: integrationId,
    integration_revision_fingerprint: integrationRevision,
    display_name: "Binance Spot US",
    type_id: "binance.spot.market_data",
    source_id: sourceId,
    environment: "US",
    time_bar_capability: {
        aggregation: "TIME",
        external_base_step_minutes: 1,
        derived_supported: true,
        minimum_step_minutes: 1,
        maximum_step_minutes: 240
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

const json = (route: Route, body: unknown) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });

async function controlledRealtime(page: Page, holdRecovery = false, acquireHistory = false) {
    let socket: WebSocketRoute | null = null;
    let connections = 0;
    const completedSteps = new Set<number>();
    let acquisitions = 0;
    const acquisitionSteps: number[] = [];
    let releaseRecovery: (() => void) | null = null;
    let emitStalePreview: (() => void) | null = null;
    const cursors: string[] = [];
    const steps: number[] = [];
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
            const end = BigInt(url.searchParams.get("end_ns") ?? "0");
            const step = Number(url.searchParams.get("bar_step") ?? "1");
            const native = nativeSteps.has(step);
            const historyComplete = !acquireHistory || completedSteps.has(step);
            const duration = BigInt(step) * minuteNs;
            const bar = (offset: bigint, close: string) => ({
                bar_start_ns: (start + offset).toString(),
                bar_end_ns: (start + offset + duration).toString(),
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
                bar_specification: { aggregation: "TIME", step, price_type: "LAST" },
                aggregation_source: native ? "EXTERNAL" : "INTERNAL",
                adjustment: "RAW",
                closed_only: true,
                start_ns: start.toString(),
                end_ns: end.toString(),
                coverage: {
                    status: historyComplete ? "COMPLETE" : "INCOMPLETE",
                    manifest_id: "manifest",
                    manifest_fingerprint: "c".repeat(64),
                    expected_bar_count: 1440,
                    actual_bar_count: historyComplete ? 1440 : 0,
                    issues: historyComplete ? [] : ["BAR_GRID_INCOMPLETE"],
                    gaps: historyComplete ? [] : [{ start_ns: String(start), end_ns: String(end) }],
                    planned_acquisition_ranges: historyComplete
                        ? []
                        : [{ start_ns: String(start), end_ns: String(end) }]
                },
                revision_id: historyComplete ? "revision" : null,
                revision_fingerprint: historyComplete ? historicalRevision : null,
                seal_id: historyComplete ? "seal" : null,
                aggregation_semantics_version: native ? null : "TIME_BAR_V1",
                calendar_fingerprint: native ? null : "a".repeat(64),
                resolution_mode: native ? "EXTERNAL_NATIVE" : "INTERNAL_DERIVED",
                resolution_plan_fingerprint: planFingerprint(step),
                base_revision_id: native ? null : "revision",
                construction_fingerprint: (step + 256).toString(16).padStart(64, "0"),
                resume_after_sequence: historyComplete
                    ? (
                          end / (step === 15 ? BigInt(15) * minuteNs : minuteNs) -
                          BigInt(1)
                      ).toString()
                    : null,
                resume_plan_fingerprint: historyComplete ? planFingerprint(step) : null,
                bars: historyComplete ? [bar(BigInt(0), "101"), bar(duration, "102")] : []
            });
        }
        if (
            url.pathname === "/api/v2/market-data/acquisitions" &&
            route.request().method() === "POST"
        ) {
            acquisitions += 1;
            const request = route.request().postDataJSON() as {
                start_ns: string;
                end_ns: string;
                bar_specification: { step: number };
            };
            acquisitionSteps.push(request.bar_specification.step);
            completedSteps.add(request.bar_specification.step);
            return json(route, {
                schema_version: 1,
                acquisition_id: `acquisition:${"b".repeat(64)}`,
                status: "COMPLETE",
                source_id: sourceId,
                integration_binding_fingerprint: "f".repeat(64),
                instrument_id: instrument.instrument_id,
                bar_specification: {
                    aggregation: "TIME",
                    step: request.bar_specification.step,
                    price_type: "LAST"
                },
                start_ns: request.start_ns,
                end_ns: request.end_ns,
                provenance: "REST_BACKFILL",
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
                failure_detail: null
            });
        }
        return route.fallback();
    });
    await page.routeWebSocket("**/api/v2/market-data/stream", (ws) => {
        socket = ws;
        const connection = ++connections;
        ws.onMessage((message) => {
            const request = JSON.parse(String(message)) as {
                resume_after_sequence: string;
                resume_plan_fingerprint: string;
                bar_specification: { aggregation: "TIME"; step: number; price_type: "LAST" };
            };
            cursors.push(request.resume_after_sequence);
            steps.push(request.bar_specification.step);
            const send = (event: object) => {
                ws.send(JSON.stringify({ schema_version: 2, ...event }));
            };
            send({
                event: "SUBSCRIBED",
                stream_id: `stream-${String(connection)}`,
                source_id: sourceId,
                instrument_id: instrument.instrument_id,
                resolution_mode: nativeSteps.has(request.bar_specification.step)
                    ? "EXTERNAL_NATIVE"
                    : "INTERNAL_DERIVED",
                resolution_plan_fingerprint: planFingerprint(request.bar_specification.step),
                cursor_bar_step_minutes: nativeSteps.has(request.bar_specification.step)
                    ? request.bar_specification.step
                    : 1
            });
            send({ event: "STATE", state: "RECOVERING" });
            const sequence = (BigInt(request.resume_after_sequence) + BigInt(1)).toString();
            const derivedBar = {
                bar_start_ns: (BigInt(sequence) * minuteNs).toString(),
                bar_end_ns: (
                    (BigInt(sequence) + BigInt(request.bar_specification.step)) *
                    minuteNs
                ).toString(),
                open: "102",
                high: "104",
                low: "101",
                close: "103",
                volume: "3",
                closed: false
            };
            send({
                event: "BAR_PREVIEW",
                source_id: sourceId,
                instrument_id: instrument.instrument_id,
                bar_specification: request.bar_specification,
                bar: derivedBar
            });
            send({
                event: "BAR_CLOSED",
                source_id: sourceId,
                instrument_id: instrument.instrument_id,
                bar_specification: request.bar_specification,
                sequence,
                bar: { ...derivedBar, closed: true }
            });
            emitStalePreview = () => {
                send({
                    event: "BAR_PREVIEW",
                    source_id: sourceId,
                    instrument_id: instrument.instrument_id,
                    bar_specification: request.bar_specification,
                    bar: {
                        ...derivedBar,
                        bar_start_ns: ((BigInt(sequence) - BigInt(1)) * minuteNs).toString(),
                        bar_end_ns: (BigInt(sequence) * minuteNs).toString()
                    }
                });
                send({ event: "STATE", state: "RECOVERING" });
            };
            if (connection === 1 || !holdRecovery) send({ event: "STATE", state: "READY" });
            else
                releaseRecovery = () => {
                    send({ event: "STATE", state: "READY" });
                };
        });
    });
    return {
        cursors,
        steps,
        acquisitions: () => acquisitions,
        acquisitionSteps,
        releaseRecovery: () => releaseRecovery?.(),
        emitStalePreview: () => emitStalePreview?.(),
        disconnect: async () => {
            await socket?.close({ code: 1012, reason: "controlled disconnect" });
        }
    };
}

test("history to realtime rollover and reconnect gap repair — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page, true);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await fixture.disconnect();
    await expect(page.getByTestId("market-data-status")).toContainText("● 行情中断");
    await expect(page.getByTestId("market-data-status")).toContainText("● 恢复中");
    fixture.releaseRecovery();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.cursors).toHaveLength(2);
    expect(BigInt(fixture.cursors[1] ?? "0")).toBe(BigInt(fixture.cursors[0] ?? "0") + BigInt(1));
});

test("explicit history acquisition, typed realtime and exact reconnect — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page, true, true);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-source-tag")).toHaveText("real · DB");
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.acquisitions()).toBe(1);
    await expect(page.getByTestId("price-chart").locator("canvas").first()).toBeVisible();

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("5");
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(5);
    fixture.releaseRecovery();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    await fixture.disconnect();
    await expect(page.getByTestId("market-data-status")).toContainText("● 行情中断");
    await expect(page.getByTestId("market-data-status")).toContainText("● 恢复中");
    fixture.releaseRecovery();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.acquisitions()).toBe(2);
    expect(BigInt(fixture.cursors[fixture.cursors.length - 1] ?? "0")).toBeGreaterThan(
        BigInt(fixture.cursors[fixture.cursors.length - 2] ?? "0")
    );
});

test("preset and custom periods subscribe to matching derived realtime bars — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("15");
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(15);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("60");
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(60);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("custom");
    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("7");
    await page.getByRole("button", { name: "应用" }).click();
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(7);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("37");
    await page.getByRole("button", { name: "应用" }).click();
    await expect.poll(() => fixture.steps[fixture.steps.length - 1]).toBe(37);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.steps).toEqual([1, 15, 60, 7, 37]);
});

test("native 15m and derived 7m use target acquisition and Product resume metadata", async ({
    page
}) => {
    const fixture = await controlledRealtime(page, false, true);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("15");
    await expect.poll(() => fixture.acquisitionSteps).toEqual([1, 15]);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    await page.getByRole("combobox", { name: "时间周期" }).selectOption("custom");
    await page.getByRole("spinbutton", { name: "自定义周期分钟数" }).fill("7");
    await page.getByRole("button", { name: "应用" }).click();
    await expect.poll(() => fixture.acquisitionSteps).toEqual([1, 15, 7]);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
    expect(fixture.steps).toEqual([1, 15, 7]);
});

test("a stale realtime preview cannot crash the chart — CONTROLLED_TEST_EVIDENCE", async ({
    page
}) => {
    const fixture = await controlledRealtime(page);
    await page.goto("/");
    await page.getByRole("combobox", { name: "数据源" }).selectOption(integrationId);
    await page.getByRole("searchbox", { name: "搜索标的" }).fill("BTCUSDT");
    await page.getByRole("searchbox", { name: "搜索标的" }).press("Enter");
    await page.getByRole("button", { name: /BTCUSDT\.BINANCE/ }).click();
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");

    fixture.emitStalePreview();
    await expect(page.getByTestId("market-data-status")).toContainText("● 恢复中");
    await expect(page.getByTestId("price-chart").locator("canvas").first()).toBeVisible();
});
