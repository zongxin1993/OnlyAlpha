import { requiredValue } from "../../test/requiredValue";
import { expect, it, vi, afterEach } from "vitest";
import { loadTemporaryMarketDataWindow } from "./temporaryMarketDataLoader";
import { readTemporaryMarketData } from "../../api/marketData/temporary";
import { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import { marketDataBars } from "../../test/marketDataClient";
import { temporaryMarketDataWindowSchema } from "../../api/marketData/temporary.generated";
vi.mock("../../api/marketData/temporary", () => ({ readTemporaryMarketData: vi.fn() }));
afterEach(() => vi.clearAllMocks());
function setup() {
    const h = marketDataBars(),
        s = h.source_selection;
    const complete = temporaryMarketDataWindowSchema.parse({
        schema_version: 1,
        source_kind: "TEMPORARY_MARKET_DATA",
        authority: "DISPLAY_ONLY",
        publication_status: "NOT_A_RESEARCH_RESULT",
        source_selection: s,
        instrument_id: h.instrument_id,
        bar_semantic: h.bar_semantic,
        anchor_kind: "BEFORE_TIME",
        requested_before_ns: h.resolved_end_ns,
        requested_bar_count: 2,
        resolved_start_ns: h.resolved_start_ns,
        resolved_end_ns: h.resolved_end_ns,
        bars: h.bars,
        coverage: { status: "COMPLETE", expected_bar_count: 2, actual_bar_count: 2, gaps: [] },
        window_fingerprint: "a".repeat(64),
        calendar_fingerprint: "b".repeat(64),
        resolution_plan_fingerprint: "c".repeat(64),
        resolution_mode: "PROVIDER_NATIVE"
    });
    const partial = structuredClone(complete);
    partial.bars = partial.bars.slice(1);
    partial.coverage = {
        status: "PARTIAL",
        expected_bar_count: 2,
        actual_bar_count: 1,
        gaps: [
            {
                start_ns: requiredValue(h.bars[0]).bar_start_ns,
                end_ns: requiredValue(h.bars[0]).bar_end_ns
            }
        ]
    };
    partial.window_fingerprint = "d".repeat(64);
    partial.anchor_kind = "LATEST_CLOSED";
    partial.requested_before_ns = null;
    const ref = {
        integration_id: s.integration_id,
        integration_revision_fingerprint: s.integration_revision_fingerprint,
        expected_type_id: s.type_id
    };
    const query = {
        instrument_id: h.instrument_id,
        bar_semantic: h.bar_semantic,
        anchor_kind: "LATEST_CLOSED" as const,
        target_bar_count: 2
    };
    const options = {
        sourceId: s.source_id,
        environment: s.environment,
        signal: new AbortController().signal,
        onWindow: vi.fn<(window: typeof complete) => void>()
    };
    return { complete, partial, ref, query, options, credentials: new LocalReadCredentials(true) };
}
it("publishes the first trusted partial window then completes the same pinned range", async () => {
    const v = setup();
    vi.mocked(readTemporaryMarketData)
        .mockResolvedValueOnce(v.partial)
        .mockResolvedValueOnce(v.complete);
    await expect(
        loadTemporaryMarketDataWindow(v.credentials, v.ref, v.query, "page", v.options)
    ).resolves.toEqual(v.complete);
    expect(v.options.onWindow.mock.calls.map(([w]) => w.coverage.status)).toEqual([
        "PARTIAL",
        "COMPLETE"
    ]);
    expect(requiredValue(vi.mocked(readTemporaryMarketData).mock.calls[1])[2]).toEqual({
        ...v.query,
        anchor_kind: "BEFORE_TIME",
        before_ns: v.partial.resolved_end_ns
    });
});
it("stops at no progress and leaves the honest partial window unchanged", async () => {
    const v = setup();
    vi.mocked(readTemporaryMarketData).mockResolvedValue(v.partial);
    await expect(
        loadTemporaryMarketDataWindow(v.credentials, v.ref, v.query, "page", v.options)
    ).resolves.toEqual(v.partial);
    expect(readTemporaryMarketData).toHaveBeenCalledTimes(2);
});
it("rejects a different resolved Source environment before publishing", async () => {
    const v = setup();
    v.complete.source_selection.environment = "OTHER";
    vi.mocked(readTemporaryMarketData).mockResolvedValue(v.complete);
    await expect(
        loadTemporaryMarketDataWindow(v.credentials, v.ref, v.query, "page", v.options)
    ).rejects.toMatchObject({ code: "MARKET_DATA_TEMPORARY_RESPONSE_MISMATCH" });
    expect(v.options.onWindow).not.toHaveBeenCalled();
});
it("drops a completed read when its original context was cancelled", async () => {
    const v = setup();
    const controller = new AbortController();
    controller.abort();
    v.options.signal = controller.signal;
    vi.mocked(readTemporaryMarketData).mockResolvedValue(v.complete);
    await expect(
        loadTemporaryMarketDataWindow(v.credentials, v.ref, v.query, "page", v.options)
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(v.options.onWindow).not.toHaveBeenCalled();
});
