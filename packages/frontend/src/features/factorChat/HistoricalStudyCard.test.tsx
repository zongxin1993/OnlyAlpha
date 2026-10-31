import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { HistoricalStudyCard } from "./HistoricalStudyCard";
import { request } from "./api";
vi.mock(import("./api"), async (original) => ({ ...(await original()), request: vi.fn() }));
vi.mock(import("./ResearchStudyPanel"), () => ({
    ResearchStudyPanel: ({ newWorkBlocked }: { newWorkBlocked: boolean }) => (
        <div>原研究记录；新研究{newWorkBlocked ? "不可提交" : "可提交"}</div>
    )
}));
const head = "a".repeat(64),
    fingerprint = "b".repeat(64);
const sessionId = "00000000-0000-4000-8000-000000000001";
const reference = { head, fingerprint, command: sessionId };
const advice = {
    source: {
        integration_id: sessionId,
        integration_revision_fingerprint: head,
        expected_type_id: "spot",
        source_id: "spot",
        environment: "test",
        instrument_id: "BTCUSDT"
    },
    timeframe_minutes: 15,
    start_at: "2026-01-01T00:00:00Z",
    development_end_at: "2026-01-02T00:00:00Z",
    end_at: "2026-01-03T00:00:00Z",
    protected_start_at: "2026-01-04T00:00:00Z",
    protected_end_at: "2026-01-05T00:00:00Z",
    horizon_bars: 1,
    expected_block_length: 12,
    replicates: 4096,
    confidence_bps: 9500,
    seed: head,
    rationale: "原研究条件"
};
const study = {
    schema_version: 1,
    fingerprint,
    is_current: false,
    withdrawn: true,
    snapshot: {
        schema_version: 1,
        owner: "owner",
        factor_proposal_fingerprint: head,
        origin: { session_id: sessionId, event_fingerprint: head },
        advice
    }
};
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
});
it("opens an exact withdrawn historical study for original run observation without enabling new work", async () => {
    vi.mocked(request).mockResolvedValue(study);
    render(
        <HistoricalStudyCard
            sessionId={sessionId}
            head={head}
            reference={reference}
            advice={advice}
        />
    );
    fireEvent.click(screen.getByRole("button", { name: "查看研究记录" }));
    expect(await screen.findByText("原研究记录；新研究不可提交")).toBeVisible();
    expect(vi.mocked(request).mock.calls[0]?.[0]).toBe(`/api/v2/factor-studies/${fingerprint}`);
    expect(vi.mocked(request).mock.calls.every((call) => call[2] === undefined)).toBe(true);
});
it.each(["session_id", "event_fingerprint"])(
    "refuses a historical record with a different %s",
    async (field) => {
        vi.mocked(request).mockResolvedValue({
            ...study,
            snapshot: {
                ...study.snapshot,
                origin: {
                    ...study.snapshot.origin,
                    [field]:
                        field === "session_id"
                            ? "00000000-0000-4000-8000-000000000002"
                            : "c".repeat(64)
                }
            }
        });
        render(
            <HistoricalStudyCard
                sessionId={sessionId}
                head={head}
                reference={reference}
                advice={advice}
            />
        );
        fireEvent.click(screen.getByRole("button", { name: "查看研究记录" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("原研究记录暂时无法核对");
        expect(screen.queryByText(/原研究记录；/)).toBeNull();
    }
);
