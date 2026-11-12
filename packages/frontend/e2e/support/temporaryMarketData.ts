import { expect, type Page, type Route, type WebSocketRoute } from "@playwright/test";
import studySampleJson from "../../../../test-data/web/chart-studies/query.json" with { type: "json" };
import {
    TEMPORARY_VECTOR_FINGERPRINT,
    temporaryBatchVector,
    temporaryEvaluationVector
} from "../../src/test/temporaryChartVectors";

// Shared Temporary Market Data workspace fixture for realtime and chart-catalog e2e.
// Mirrors api/marketData/temporary.ts, api/marketData/temporaryStream.ts and
// api/chartStudies/client.ts admission exactly. No Acquisition, no durable
// history, no Research reads.

export const studySample = studySampleJson as unknown as {
    readonly capability: Record<string, unknown>;
    readonly evaluation: Record<string, unknown>;
};

export const integrationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const revision = "a".repeat(64);
export const sourceId = "binance.spot.market_data.us";
export const minuteNs = BigInt("60000000000");
// Aligned 15m window end reused by test-data/web/chart-studies/query.json.
export const windowEnd = "1767225600000000000";
export const calendarFingerprint = "c".repeat(64);
export const nativeSteps = new Set([1, 3, 5, 15, 30, 60, 120, 240]);
export const semantic = (durationMinutes: number) => ({
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
export const planFingerprint = (durationMinutes: number) =>
    durationMinutes.toString(16).padStart(64, "0");

export const source = {
    is_current_revision: true,
    integration_id: integrationId,
    integration_revision_fingerprint: revision,
    display_name: "Binance Spot US",
    type_id: "binance.spot.market_data",
    source_id: sourceId,
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
export const instrument = {
    instrument_id: "BTCUSDT.BINANCE",
    display_symbol: "BTCUSDT",
    venue: "BINANCE",
    market: "SPOT",
    asset_class: "CRYPTOCURRENCY",
    instrument_type: "CRYPTO_SPOT",
    status: "ACTIVE",
    market_data_capabilities: ["BAR_1M_EXTERNAL_RAW"]
};
export const selection = {
    integration_id: integrationId,
    integration_revision_fingerprint: revision,
    type_id: source.type_id,
    source_id: sourceId,
    environment: source.environment
};

// One closed Bar identity; the stream's closed Bar reuses it verbatim so the
// study evaluation re-read matches every plotted closed fact field by field.
export const closedBar = (startNs: bigint, durationNs: bigint) => ({
    bar_start_ns: startNs.toString(),
    bar_end_ns: (startNs + durationNs).toString(),
    open: "100",
    high: "102",
    low: "99",
    close: "101",
    volume: "2",
    closed: true
});

export function json(route: Route, body: unknown, status = 200) {
    return route.fulfill({
        status,
        contentType: "application/json",
        headers: { "cache-control": "no-store" },
        body: JSON.stringify(body)
    });
}

// Exact replica of api/chartStudies/client.ts canonical+fingerprint, needed to
// serve a consistently re-fingerprinted Capability after the stale switch.
export function canonical(value: unknown): string {
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    if (value !== null && typeof value === "object")
        return `{${Object.entries(value as Record<string, unknown>)
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
            .map(([name, item]) => `${JSON.stringify(name)}:${canonical(item)}`)
            .join(",")}}`;
    return JSON.stringify(value);
}
export async function fingerprint(value: unknown): Promise<string> {
    const bytes = new TextEncoder().encode(canonical(value));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

// A TemporaryMarketDataWindow exactly as api/marketData/temporary.ts admits it.
export function temporaryWindow(step: number, target: number, before: string | null) {
    const duration = BigInt(step) * minuteNs;
    const end = before === null ? BigInt(windowEnd) : BigInt(before);
    const start = end - BigInt(target) * duration;
    return {
        schema_version: 1,
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        source_kind: "TEMPORARY_MARKET_DATA",
        anchor_kind: before === null ? "LATEST_CLOSED" : "BEFORE_TIME",
        requested_before_ns: before,
        requested_bar_count: target,
        bar_semantic: semantic(step),
        instrument_id: instrument.instrument_id,
        source_selection: selection,
        resolved_start_ns: start.toString(),
        resolved_end_ns: end.toString(),
        calendar_fingerprint: calendarFingerprint,
        resolution_plan_fingerprint: planFingerprint(step),
        resolution_mode: nativeSteps.has(step) ? "PROVIDER_NATIVE" : "DERIVED",
        window_fingerprint: TEMPORARY_VECTOR_FINGERPRINT,
        bars: Array.from({ length: target }, (_, index) =>
            closedBar(start + BigInt(index) * duration, duration)
        ),
        coverage: {
            status: "COMPLETE",
            expected_bar_count: target,
            actual_bar_count: target,
            gaps: []
        }
    };
}

export interface BarQuery {
    readonly step: number;
    readonly anchor: "LATEST_CLOSED" | "BEFORE_TIME";
    readonly before: string | null;
    readonly target: number;
}

export interface TemporarySubscription {
    readonly operation: string;
    readonly schema_version: number;
    readonly page_id: string;
    readonly source_reference: {
        readonly integration_id: string;
        readonly integration_revision_fingerprint: string;
        readonly expected_type_id: string;
    };
    readonly instrument_id: string;
    readonly bar_semantic: { readonly formation: { readonly window_minutes: number } };
    readonly before_ns: string;
    readonly target_bar_count: number;
    readonly expected_window_fingerprint: string;
}

// Serves a consistent Capability Projection switch: keeps every field the client
// admission re-verifies intact, changing only the projection fingerprint.
async function refingerprintedCapability(
    capability: Record<string, unknown>
): Promise<Record<string, unknown>> {
    const entry = structuredClone(capability) as Record<string, unknown> & {
        capability_projection: Record<string, unknown>;
    };
    entry.capability_projection.catalog_generation_fingerprint = "e".repeat(64);
    entry.catalog_generation_fingerprint = "e".repeat(64);
    entry.capability_projection_fingerprint = await fingerprint(entry.capability_projection);
    return entry;
}

export async function controlledRealtime(
    page: Page,
    options: {
        readonly holdRecovery?: boolean;
        readonly staleCapabilityOnConfirm?: boolean;
        // Extra Capability variants served ahead of the SMA sample.
        readonly capabilities?: () => readonly Record<string, unknown>[];
    } = {}
) {
    const holdRecovery = options.holdRecovery === true;
    let socket: WebSocketRoute | null = null;
    let connections = 0;
    let releaseRecovery: (() => void) | null = null;
    let emitPreview: ((missingProviderEvent?: boolean) => void) | null = null;
    let emitStalePreview: (() => void) | null = null;
    let previewTicks = 0;
    // Armed by the test right before the editor's confirmation read.
    const staleVerify = { armed: false };
    let capabilitiesReads = 0;
    const evaluateReads: object[] = [];
    const barQueries: BarQuery[] = [];
    const olderRequests: URL[] = [];
    const subscriptions: TemporarySubscription[] = [];
    const steps: number[] = [];

    await page.route("**/api/v2/**", async (route) => {
        const url = new URL(route.request().url());
        if (route.request().method() === "POST") {
            if (url.pathname === "/api/v2/chart/temporary-studies/evaluate-batch") {
                const body = route.request().postDataJSON() as {
                    bar_semantic: { formation: { window_minutes: number } };
                    window: { before_ns: string };
                    calculations: readonly unknown[];
                };
                evaluateReads.push(body);
                const step = body.bar_semantic.formation.window_minutes;
                const duration = BigInt(step) * minuteNs;
                const end = BigInt(body.window.before_ns);
                const start = end - BigInt(2000) * duration;
                const points = Array.from({ length: 2000 }, (_, index) => ({
                    closed: true,
                    quality: "CLOSED_COMPLETE",
                    readiness: index < 19 ? "PARTIAL" : "READY",
                    reason: index < 19 ? "WARMUP_INCOMPLETE" : "NONE",
                    time_ns: (start + BigInt(index) * duration).toString(),
                    value: "10.500000000000"
                }));
                const evaluation = structuredClone(studySample.evaluation) as Record<
                    string,
                    unknown
                > & {
                    input: Record<string, unknown>;
                    coverage: Record<string, unknown>;
                };
                evaluation.bar_semantic = semantic(step);
                evaluation.source_selection = selection;
                evaluation.input.before_ns = body.window.before_ns;
                evaluation.input.resolved_start_ns = start.toString();
                evaluation.input.resolved_end_ns = body.window.before_ns;
                evaluation.input.calendar_fingerprint = calendarFingerprint;
                evaluation.input.resolution_plan_fingerprint = planFingerprint(step);
                evaluation.input.resolution_mode = nativeSteps.has(step)
                    ? "PROVIDER_NATIVE"
                    : "DERIVED";
                evaluation.input.target_bar_count = 2000;
                evaluation.coverage = {
                    ...evaluation.coverage,
                    status: "COMPLETE",
                    expected_bar_count: 2000,
                    actual_bar_count: 2000,
                    gaps: []
                };
                evaluation.series = [{ output_name: "value", points }];
                // Project the captured ChartStudyEvaluate into the Temporary contract
                // (drops durable-only input/coverage keys, adds the window fingerprint).
                return json(
                    route,
                    temporaryBatchVector(
                        body.calculations.map(() =>
                            temporaryEvaluationVector(
                                evaluation as unknown as Parameters<
                                    typeof temporaryEvaluationVector
                                >[0]
                            )
                        )
                    )
                );
            }
            if (url.pathname === "/api/v2/chart/temporary-studies/evaluate") {
                evaluateReads.push(route.request().postDataJSON() as object);
                return json(route, { detail: "NOT_USED_IN_TRANSIENT_CHART" }, 500);
            }
            return route.fallback();
        }
        if (url.pathname === "/api/v2/market-data/sources")
            return json(route, { schema_version: 1, sources: [source] });
        if (url.pathname === "/api/v2/market/instruments/search") {
            return json(route, {
                schema_version: 1,
                truncated: false,
                sources: [
                    {
                        source_selection: selection,
                        status: "COMPLETE",
                        asset_classes: ["CRYPTOCURRENCY"],
                        truncated: false
                    }
                ],
                results: [{ source_selection: selection, instrument }]
            });
        }
        if (url.pathname === "/api/v2/market/instruments")
            return json(route, {
                schema_version: 1,
                source_selection: selection,
                instruments: [instrument]
            });
        if (url.pathname === "/api/v2/chart/studies/capabilities") {
            capabilitiesReads += 1;
            const capabilities = options.capabilities
                ? [...options.capabilities()]
                : [structuredClone(studySample.capability)];
            if (options.staleCapabilityOnConfirm === true && staleVerify.armed)
                capabilities[capabilities.length - 1] = await refingerprintedCapability(
                    capabilities[capabilities.length - 1]
                );
            return json(route, { schema_version: 2, capabilities });
        }
        if (url.pathname === "/api/v2/chart/market-data/bars") {
            const requested = JSON.parse(
                url.searchParams.get("bar_semantic") ?? "null"
            ) as ReturnType<typeof semantic>;
            const step = requested.formation.window_minutes;
            const anchor = url.searchParams.get("anchor_kind");
            if (anchor !== "LATEST_CLOSED" && anchor !== "BEFORE_TIME")
                throw new Error(`invalid anchor_kind ${String(anchor)}`);
            const before = url.searchParams.get("before_ns");
            const target = Number(url.searchParams.get("target_bar_count"));
            expect(url.searchParams.has("start_ns")).toBe(false);
            if (anchor === "BEFORE_TIME") expect(before).not.toBeNull();
            else expect(before).toBeNull();
            barQueries.push({ step, anchor, before, target });
            if (target === 240) {
                expect(anchor).toBe("BEFORE_TIME");
                olderRequests.push(url);
            }
            return json(route, temporaryWindow(step, target, before));
        }
        return route.fallback();
    });
    await page.routeWebSocket("**/api/v2/chart/market-data/stream", (ws) => {
        socket = ws;
        const connection = ++connections;
        ws.onMessage((message) => {
            const request = JSON.parse(String(message)) as TemporarySubscription;
            expect(request.operation).toBe("SUBSCRIBE_TEMPORARY_BARS");
            expect(request.schema_version).toBe(2);
            expect(request.page_id).not.toBe("");
            expect(request.expected_window_fingerprint).toBe(TEMPORARY_VECTOR_FINGERPRINT);
            subscriptions.push(request);
            const step = request.bar_semantic.formation.window_minutes;
            steps.push(step);
            const send = (event: object) => {
                ws.send(JSON.stringify({ schema_version: 2, ...event }));
            };
            send({
                event: "SUBSCRIBED",
                authority: "DISPLAY_ONLY",
                publication_status: "NOT_A_RESEARCH_RESULT",
                source_kind: "TEMPORARY_MARKET_DATA",
                cursor_bar_stride_minutes: nativeSteps.has(step) ? step : 1,
                instrument_id: request.instrument_id,
                resolution_mode: nativeSteps.has(step) ? "PROVIDER_NATIVE" : "DERIVED",
                resolution_plan_fingerprint: planFingerprint(step),
                source_id: sourceId,
                stream_id: `stream-${String(connection)}`
            });
            send({ event: "STATE", state: "RECOVERING" });
            if (connection === 1 || !holdRecovery) send({ event: "STATE", state: "READY" });
            else
                releaseRecovery = () => {
                    send({ event: "STATE", state: "READY" });
                };
            const start = BigInt(request.before_ns);
            const duration = BigInt(step) * minuteNs;
            const end = start + duration;
            const timing = {
                stream_id: `stream-${String(connection)}`,
                provider_event_ns: (end + BigInt(1_000_000)).toString(),
                ingress_received_ns: (end + BigInt(2_000_000)).toString()
            };
            const bar = { ...closedBar(start, duration), closed: false };
            const base = {
                source_id: sourceId,
                instrument_id: request.instrument_id,
                bar_semantic: request.bar_semantic
            };
            send({ event: "BAR_PREVIEW", timing, ...base, bar });
            send({
                event: "BAR_CLOSED",
                timing,
                ...base,
                sequence: "1",
                bar: closedBar(start, duration)
            });
            emitStalePreview = () => {
                send({
                    event: "BAR_PREVIEW",
                    timing: null,
                    ...base,
                    bar: { ...closedBar(start - duration, duration), closed: false }
                });
                send({ event: "STATE", state: "RECOVERING" });
            };
            emitPreview = (missingProviderEvent = false) => {
                // Distinct content per call: the Bar ledger dedupes an identical
                // preview (sameBar), which would silently drop timing updates.
                previewTicks += 1;
                send({
                    event: "BAR_PREVIEW",
                    timing: {
                        stream_id: `stream-${String(connection)}`,
                        provider_event_ns: missingProviderEvent
                            ? null
                            : (end + BigInt(3)).toString(),
                        ingress_received_ns: (end + BigInt(2)).toString()
                    },
                    ...base,
                    bar: {
                        bar_start_ns: end.toString(),
                        bar_end_ns: (end + duration).toString(),
                        open: "102",
                        high: "104",
                        low: "101",
                        close: `103.00000000000000000${String(previewTicks)}`,
                        volume: `3.00000000000000000${String(previewTicks)}`,
                        closed: false
                    }
                });
            };
        });
    });
    return {
        barQueries,
        olderRequests,
        subscriptions,
        steps,
        evaluateReads,
        pinQueries: () => barQueries.filter((query) => query.anchor === "BEFORE_TIME"),
        armStaleVerify: () => {
            staleVerify.armed = true;
        },
        capabilitiesReads: () => capabilitiesReads,
        emitPreview: (missingProviderEvent = false) => emitPreview?.(missingProviderEvent),
        emitStalePreview: () => emitStalePreview?.(),
        releaseRecovery: () => releaseRecovery?.(),
        disconnect: async () => {
            await socket?.close({ code: 1012, reason: "controlled disconnect" });
        }
    };
}

export async function hoverLatest(page: Page) {
    const chart = page.getByTestId("price-chart");
    const canvas = await chart.locator("canvas").first().boundingBox();
    const from = Number(await chart.getAttribute("data-visible-range-from"));
    const to = Number(await chart.getAttribute("data-visible-range-to"));
    const count = Number(await chart.getAttribute("data-volume-point-count"));
    if (!canvas || !Number.isFinite(from) || !(to > from) || count < 1)
        throw new Error("Visible Bar geometry required");
    // Aim just left of the last Bar's center: a half-Bar offset would round into
    // the empty right offset (no Bar time), and the exact right edge belongs to
    // the price scale. Clamping keeps the point on the plot for both layouts.
    const x = Math.min(
        canvas.x + canvas.width - 2,
        canvas.x + (canvas.width * (count - 1.25 - from)) / (to - from)
    );
    await page.mouse.move(x, canvas.y + canvas.height / 2);
}

export async function openInspector(page: Page) {
    const inspector = page.getByRole("group", { name: "行情检查器" });
    await inspector.locator("summary").click();
    return page.getByRole("table", { name: "行情检查器明细" });
}

export const status = (page: Page) => page.getByTestId("market-data-status");
export const chart = (page: Page) => page.getByTestId("price-chart");
