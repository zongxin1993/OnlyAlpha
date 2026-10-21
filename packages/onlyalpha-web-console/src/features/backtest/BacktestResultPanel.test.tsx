import { render, screen, within } from "@testing-library/react";
import { AppProviders } from "../../app/providers";
import { researchClient } from "../../test/researchClient";
import { parseBacktestRunId } from "../../domain/research/identity";
import type { BacktestRunTransport } from "../../api/research/schemas";
import { BacktestResultPanel } from "./BacktestResultPanel";

it("presents the owning Order snapshot instead of reading fields from its result wrapper", async () => {
    const id = parseBacktestRunId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    const run: BacktestRunTransport = {
        schema_version: 1,
        run_id: id,
        state: "COMPLETED",
        revision: 2,
        specification_fingerprint: "a".repeat(64),
        admission_resolution_fingerprint: "b".repeat(64),
        queued_at: "2026-10-21T00:00:00+00:00",
        started_at: "2026-10-21T00:00:01+00:00",
        cancel_requested_at: null,
        finished_at: "2026-10-21T00:00:02+00:00",
        failure: null,
        result_fingerprint: "c".repeat(64),
        determinism_fingerprint: "d".repeat(64),
        evidence_fingerprint: "e".repeat(64)
    };
    const result = {
        result_fingerprint: run.result_fingerprint,
        determinism_fingerprint: run.determinism_fingerprint,
        run: { status: "COMPLETED" },
        execution: { order_count: 1, trade_count: 1 },
        orders: [
            {
                creation: {},
                submission: {},
                snapshot: {
                    order_id: { schema_version: 1, value: "runtime-ORDER-000001" },
                    status: "FILLED",
                    side: "BUY",
                    quantity: { schema_version: 1, value: "2", precision: 0 },
                    price: { schema_version: 1, value: "100.00", precision: 2 }
                }
            }
        ],
        trades: []
    };
    render(
        <AppProviders
            client={researchClient({
                getBacktestResult: () =>
                    Promise.resolve({
                        schema_version: 1,
                        implementation: "RUST",
                        runtime: {},
                        result
                    })
            })}
        >
            <BacktestResultPanel id={id} run={run} />
        </AppProviders>
    );
    const panel = await screen.findByRole("region", { name: "Backtest result" });
    const order = within(panel).getAllByRole("table")[0];
    expect(order).toHaveTextContent("runtime-ORDER-000001");
    expect(order).toHaveTextContent("FILLED");
    expect(order).toHaveTextContent("BUY");
    expect(order).toHaveTextContent("100.00");
    expect(order).not.toHaveTextContent("Not reported");
});
