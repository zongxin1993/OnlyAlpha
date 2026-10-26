import { requiredValue } from "../../test/requiredValue";
import type { TemporaryMarketDataWindow } from "./temporary.generated";
import { readTemporaryMarketData } from "./temporary";
import { LocalReadCredentials } from "./localReadCredentials";
import { marketDataBarSemantic } from "./model";
import { FIXTURE_REFERENCE, FIXTURE_SELECTION } from "../../test/marketDataClient";
const query = {
    instrument_id: "TEST.TEST",
    bar_semantic: marketDataBarSemantic(1),
    anchor_kind: "BEFORE_TIME" as const,
    before_ns: "180000000000",
    target_bar_count: 2
};
const bar = (start: number) => ({
    bar_start_ns: String(start),
    bar_end_ns: String(start + 60000000000),
    open: "10",
    high: "11",
    low: "9",
    close: "10",
    volume: "1",
    closed: true
});
const window = (): TemporaryMarketDataWindow => ({
    schema_version: 1,
    source_kind: "TEMPORARY_MARKET_DATA",
    authority: "DISPLAY_ONLY",
    publication_status: "NOT_A_RESEARCH_RESULT",
    source_selection: FIXTURE_SELECTION,
    instrument_id: query.instrument_id,
    bar_semantic: query.bar_semantic,
    anchor_kind: "BEFORE_TIME",
    requested_before_ns: query.before_ns,
    requested_bar_count: 2,
    resolved_start_ns: "60000000000",
    resolved_end_ns: query.before_ns,
    coverage: { status: "COMPLETE", expected_bar_count: 2, actual_bar_count: 2, gaps: [] },
    bars: [bar(60000000000), bar(120000000000)],
    window_fingerprint: "b".repeat(64),
    calendar_fingerprint: "c".repeat(64),
    resolution_plan_fingerprint: "d".repeat(64),
    resolution_mode: "PROVIDER_NATIVE"
});
afterEach(() => vi.unstubAllGlobals());
function respond(value: unknown) {
    const fetch = vi
        .fn<typeof globalThis.fetch>()
        .mockResolvedValue(
            new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } })
        );
    vi.stubGlobal("fetch", fetch);
    return fetch;
}
it("uses only the temporary read route with the exact source, window and abort signal", async () => {
    const fetch = respond(window());
    const controller = new AbortController();
    const result = await readTemporaryMarketData(
        new LocalReadCredentials(true),
        FIXTURE_REFERENCE,
        query,
        "00000000-0000-4000-8000-000000000001",
        controller.signal
    );
    expect(result.coverage.status).toBe("COMPLETE");
    const requestedUrl = fetch.mock.calls[0]?.[0];
    if (typeof requestedUrl !== "string") throw new Error("Expected Product API URL");
    const url = new URL(requestedUrl, "http://localhost");
    expect(url.pathname).toBe("/api/v2/chart/market-data/bars");
    expect(url.searchParams.get("integration_revision_fingerprint")).toBe(
        FIXTURE_REFERENCE.integration_revision_fingerprint
    );
    expect(url.searchParams.get("page_id")).toBe("00000000-0000-4000-8000-000000000001");
    expect(fetch.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
    expect(fetch.mock.calls[0]?.[1]?.credentials).toBe("same-origin");
    expect(fetch).toHaveBeenCalledTimes(1);
});
it.each([
    "source",
    "semantic",
    "instrument",
    "count",
    "preview",
    "duplicate",
    "false-complete",
    "durable-proof"
])("rejects a %s mutation without falling back to history or acquisition", async (kind) => {
    const value = window();
    if (kind === "source")
        value.source_selection = {
            ...value.source_selection,
            integration_revision_fingerprint: "e".repeat(64)
        };
    if (kind === "semantic") value.bar_semantic = marketDataBarSemantic(3);
    if (kind === "instrument") value.instrument_id = "OTHER.TEST";
    if (kind === "count") value.requested_bar_count = 3;
    if (kind === "preview") requiredValue(value.bars[0]).closed = false;
    if (kind === "duplicate") value.bars[1] = requiredValue(value.bars[0]);
    if (kind === "false-complete") value.bars.pop();
    const payload = kind === "durable-proof" ? { ...value, seal_id: "invented" } : value;
    const fetch = respond(payload);
    await expect(
        readTemporaryMarketData(
            new LocalReadCredentials(true),
            FIXTURE_REFERENCE,
            query,
            "00000000-0000-4000-8000-000000000001"
        )
    ).rejects.toBeDefined();
    expect(fetch).toHaveBeenCalledTimes(1);
});
it("accepts an explicitly partial window with actual rows and honest gaps", async () => {
    const value = window();
    value.bars = [requiredValue(value.bars[1])];
    value.coverage = {
        status: "PARTIAL",
        expected_bar_count: 2,
        actual_bar_count: 1,
        gaps: [{ start_ns: "60000000000", end_ns: "120000000000" }]
    };
    respond(value);
    const result = await readTemporaryMarketData(
        new LocalReadCredentials(true),
        FIXTURE_REFERENCE,
        query,
        "00000000-0000-4000-8000-000000000001"
    );
    expect(result.bars).toHaveLength(1);
    expect(result.coverage.status).toBe("PARTIAL");
});
