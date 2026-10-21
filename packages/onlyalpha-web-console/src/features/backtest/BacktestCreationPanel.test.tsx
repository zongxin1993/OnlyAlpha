import { onlineManager } from "@tanstack/react-query";
import { render, screen, waitFor, cleanup, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { AppProviders } from "../../app/providers";
import { BacktestCreationPanel } from "./BacktestCreationPanel";

const server = setupServer();
beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
});
afterEach(() => {
    cleanup();
    server.resetHandlers();
    sessionStorage.clear();
});
afterAll(() => {
    server.close();
});
function open() {
    return render(
        <AppProviders>
            <RouterProvider
                router={createMemoryRouter(
                    [
                        { path: "/backtest/runs", element: <BacktestCreationPanel /> },
                        { path: "/backtest/runs/:id", element: <p>Submitted Run</p> }
                    ],
                    { initialEntries: ["/backtest/runs"] }
                )}
            />
        </AppProviders>
    );
}

it("retains command, Run and Generation across a lost creation response and page reopen", async () => {
    const requests: { command: string | null; body: Record<string, unknown> }[] = [];
    server.use(
        http.get("*/api/v2/backtest/creation-context", () =>
            HttpResponse.json({
                schema_version: 1,
                runtime_generation_fingerprint: "a".repeat(64),
                options: [
                    {
                        strategy_fingerprint: "b".repeat(64),
                        dataset_binding_fingerprint: "c".repeat(64),
                        market_product_configuration_fingerprint: "d".repeat(64),
                        base_currency: "USD",
                        instruments: ["A.XNAS"],
                        start: "2026-01-05T00:00:00+00:00",
                        end: "2026-01-05T01:00:00+00:00",
                        row_count: 8
                    }
                ],
                denied: []
            })
        ),
        http.post("*/api/v2/backtest/runs", async ({ request }) => {
            const body = (await request.json()) as Record<string, unknown>;
            requests.push({ command: request.headers.get("Idempotency-Key"), body });
            return requests.length === 1
                ? HttpResponse.error()
                : HttpResponse.json(
                      {
                          schema_version: 1,
                          backtest_run_id: body.backtest_run_id,
                          state: "QUEUED",
                          disposition: "REPLAYED"
                      },
                      { status: 202 }
                  );
        })
    );
    const first = open();
    const user = userEvent.setup();
    await screen.findByRole("option", { name: /A.XNAS/ });
    await user.selectOptions(
        screen.getByLabelText("Strategy and dataset"),
        screen.getByRole("option", { name: /A.XNAS/ })
    );
    await user.type(screen.getByLabelText("Entry limit price"), "100.00");
    await user.type(screen.getByLabelText("Exit limit price"), "1.00");
    await user.click(screen.getByRole("button", { name: "Create and run Backtest" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Submission outcome is unconfirmed");
    expect(screen.getByRole("button", { name: "Create and run Backtest" })).toBeDisabled();
    first.unmount();
    open();
    await user.click(await screen.findByRole("button", { name: "Retry original submission" }));
    expect(await screen.findByText("Submitted Run")).toBeInTheDocument();
    await waitFor(() => {
        expect(requests).toHaveLength(2);
    });
    expect(requests[1]).toEqual(requests[0]);
    expect(requests[0]?.body.runtime_generation_fingerprint).toBe("a".repeat(64));
});

it("keeps the selected immutable input when context discovery changes ordering", async () => {
    const option = (instrument: string, fingerprint: string) => ({
        strategy_fingerprint: fingerprint.repeat(64),
        dataset_binding_fingerprint: fingerprint.repeat(64),
        market_product_configuration_fingerprint: "d".repeat(64),
        base_currency: "CNY",
        instruments: [instrument],
        start: "2026-01-05T00:00:00+00:00",
        end: "2026-01-05T01:00:00+00:00",
        row_count: 8
    });
    const first = option("A.XNAS", "a"),
        second = option("B.XNAS", "b");
    let requests = 0;
    server.use(
        http.get("*/api/v2/backtest/creation-context", () => {
            requests++;
            return HttpResponse.json({
                schema_version: 1,
                runtime_generation_fingerprint: "c".repeat(64),
                options: requests === 1 ? [first, second] : [second, first],
                denied: []
            });
        })
    );
    open();
    const user = userEvent.setup();
    const selected = await screen.findByRole("option", { name: /A.XNAS/ });
    await user.selectOptions(screen.getByLabelText("Strategy and dataset"), selected);
    act(() => {
        onlineManager.setOnline(false);
        onlineManager.setOnline(true);
    });
    await waitFor(() => {
        expect(requests).toBe(2);
        expect(screen.getAllByRole("option")[1]).toHaveTextContent("B.XNAS");
    });
    expect(screen.getByLabelText("Strategy and dataset")).toHaveDisplayValue(/A.XNAS/);
});

it("allows a fresh submission after an explicit admission rejection before Run creation", async () => {
    const requests: { command: string | null; body: Record<string, unknown> }[] = [];
    server.use(
        http.get("*/api/v2/backtest/creation-context", () =>
            HttpResponse.json({
                schema_version: 1,
                runtime_generation_fingerprint: "a".repeat(64),
                options: [
                    {
                        strategy_fingerprint: "b".repeat(64),
                        dataset_binding_fingerprint: "c".repeat(64),
                        market_product_configuration_fingerprint: "d".repeat(64),
                        base_currency: "USD",
                        instruments: ["A.XNAS"],
                        start: "2026-01-05T00:00:00+00:00",
                        end: "2026-01-05T01:00:00+00:00",
                        row_count: 8
                    }
                ],
                denied: []
            })
        ),
        http.post("*/api/v2/backtest/runs", async ({ request }) => {
            const body = (await request.json()) as Record<string, unknown>;
            requests.push({ command: request.headers.get("Idempotency-Key"), body });
            return requests.length === 1
                ? HttpResponse.json(
                      {
                          schema_version: 1,
                          error: {
                              phase: "ADMISSION",
                              code: "STRATEGY_NOT_ADMITTED_TO_BACKTEST",
                              detail: "Strategy is no longer admitted"
                          }
                      },
                      { status: 409 }
                  )
                : HttpResponse.json(
                      {
                          schema_version: 1,
                          backtest_run_id: body.backtest_run_id,
                          state: "QUEUED",
                          disposition: "REPLAYED"
                      },
                      { status: 202 }
                  );
        })
    );
    const first = open();
    const user = userEvent.setup();
    await screen.findByRole("option", { name: /A.XNAS/ });
    await user.selectOptions(
        screen.getByLabelText("Strategy and dataset"),
        screen.getByRole("option", { name: /A.XNAS/ })
    );
    await user.type(screen.getByLabelText("Entry limit price"), "100.00");
    await user.type(screen.getByLabelText("Exit limit price"), "1.00");
    await user.click(screen.getByRole("button", { name: "Create and run Backtest" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("STRATEGY_NOT_ADMITTED_TO_BACKTEST");
    expect(screen.getByRole("button", { name: "Create and run Backtest" })).toBeEnabled();
    first.unmount();
    open();
    await screen.findByRole("option", { name: /A.XNAS/ });
    await user.selectOptions(
        screen.getByLabelText("Strategy and dataset"),
        screen.getByRole("option", { name: /A.XNAS/ })
    );
    await user.type(screen.getByLabelText("Entry limit price"), "100.00");
    await user.type(screen.getByLabelText("Exit limit price"), "1.00");
    await user.click(screen.getByRole("button", { name: "Create and run Backtest" }));
    expect(await screen.findByText("Submitted Run")).toBeInTheDocument();
    await waitFor(() => {
        expect(requests).toHaveLength(2);
    });
    expect(requests[1]?.command).not.toEqual(requests[0]?.command);
    expect(requests[0]?.body.runtime_generation_fingerprint).toBe("a".repeat(64));
});
