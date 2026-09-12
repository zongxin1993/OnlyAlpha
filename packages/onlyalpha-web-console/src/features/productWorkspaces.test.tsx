import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ResearchApiClient } from "../api/research/client";
import { ProductWebError, ResearchWebError } from "../api/research/errors";
import type {
    BacktestEvidenceTransport,
    BacktestRunTransport,
    ProductHealthTransport,
    StrategyTransport
} from "../api/research/schemas";
import { AppProviders } from "../app/providers";
import { parseBacktestRunId, parseSha256Fingerprint } from "../domain/research/identity";
import { researchClient } from "../test/researchClient";
import { BacktestPage } from "./backtest/BacktestPage";
import { StrategyPage } from "./strategies/StrategyPage";
import { SystemHealthPage } from "./system/SystemHealthPage";

const strategyId = parseSha256Fingerprint("a".repeat(64));
const runId = parseBacktestRunId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
const strategy: StrategyTransport = {
    schema_version: 1,
    strategy_fingerprint: strategyId,
    revision: { private_semantic_payload: "Not a browser-owned model" },
    freeze_relation_fingerprints: ["b".repeat(64)],
    current_stage: "BACKTEST",
    promotion_records: [{ actor: "fixture-author" }]
};
const completedRun: BacktestRunTransport = {
    schema_version: 1,
    run_id: runId,
    state: "COMPLETED",
    revision: 2,
    specification_fingerprint: "c".repeat(64),
    admission_resolution_fingerprint: "d".repeat(64),
    queued_at: "2026-09-01T00:00:00+00:00",
    started_at: "2026-09-01T00:00:01+00:00",
    cancel_requested_at: null,
    finished_at: "2026-09-01T00:00:02+00:00",
    result_fingerprint: "e".repeat(64),
    evidence_fingerprint: "f".repeat(64),
    determinism_fingerprint: "1".repeat(64),
    failure: null
};
const evidence: BacktestEvidenceTransport = {
    schema_version: 1,
    manifest: {
        schema_version: 1,
        backtest_run_id: runId,
        specification_fingerprint: "c".repeat(64),
        admission_resolution_fingerprint: "d".repeat(64),
        strategy_fingerprint: strategyId,
        dataset_binding_fingerprint: "2".repeat(64),
        base_dataset_snapshot_fingerprint: "3".repeat(64),
        market_product_composition_fingerprint: "4".repeat(64),
        portfolio_profile_fingerprint: "5".repeat(64),
        risk_profile_fingerprint: "6".repeat(64),
        execution_profile_fingerprint: "7".repeat(64),
        kernel_semantics_version: "1",
        implementation_fingerprints: ["8".repeat(64)],
        result_fingerprint: "e".repeat(64),
        determinism_fingerprint: "1".repeat(64),
        evidence_fingerprint: "f".repeat(64),
        artifacts: [
            {
                name: "result.json",
                sha256: "9".repeat(64),
                size: 128,
                media_type: "application/json"
            }
        ]
    }
};
const health: Record<"live" | "ready" | "execution", ProductHealthTransport> = {
    live: { status: "LIVE", checks: { http: "LIVE" } },
    ready: {
        status: "NOT_READY",
        checks: { product_kernel: "RECOVERING" },
        reason: "KERNEL_RECOVERING"
    },
    execution: {
        status: "DEGRADED",
        checks: { backtest_worker: "ABSENT" },
        reason: "BACKTEST_WORKER_ABSENT"
    }
};

afterEach(() => {
    vi.restoreAllMocks();
});

function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<T>((done, fail) => {
        resolve = done;
        reject = fail;
    });
    return { promise, resolve, reject };
}

function renderWorkspace(entry: string, overrides: Partial<ResearchApiClient> = {}) {
    const client = researchClient({
        getStrategy: () => Promise.resolve(strategy),
        getBacktestRun: () => Promise.resolve(completedRun),
        getBacktestEvidence: () => Promise.resolve(evidence),
        getHealth: (selector) => Promise.resolve(health[selector]),
        ...overrides
    });
    const getStrategy = vi.spyOn(client, "getStrategy");
    const getBacktestRun = vi.spyOn(client, "getBacktestRun");
    const getBacktestEvidence = vi.spyOn(client, "getBacktestEvidence");
    const getHealth = vi.spyOn(client, "getHealth");
    const router = createMemoryRouter(
        [
            { path: "/strategies", element: <StrategyPage /> },
            { path: "/strategies/:strategyFingerprint", element: <StrategyPage /> },
            { path: "/backtest/runs", element: <BacktestPage /> },
            { path: "/backtest/runs/:backtestRunId", element: <BacktestPage /> },
            { path: "/system/health", element: <SystemHealthPage /> },
            { path: "/research/results", element: <h1>Research Results</h1> }
        ],
        { initialEntries: [entry] }
    );
    const rendered = render(
        <AppProviders client={client}>
            <RouterProvider router={router} />
        </AppProviders>
    );
    return { ...rendered, router, getStrategy, getBacktestRun, getBacktestEvidence, getHealth };
}

describe("exact read-only Strategy workspace", () => {
    it("starts with an exact identity form rather than a fabricated global Strategy catalog", () => {
        const browserFetch = vi.spyOn(globalThis, "fetch");
        const { getStrategy, getBacktestRun, getBacktestEvidence, getHealth } =
            renderWorkspace("/strategies");
        expect(screen.getByRole("heading", { name: "Strategy Workspace" })).toBeInTheDocument();
        expect(screen.getByRole("form", { name: "Open Strategy" })).toBeInTheDocument();
        expect(screen.getByLabelText("Strategy fingerprint")).toHaveValue("");
        expect(
            screen.getByText("No global Strategy catalog is exposed by the current Product API.")
        ).toBeInTheDocument();
        expect(screen.queryByRole("table")).not.toBeInTheDocument();
        expect(getStrategy).not.toHaveBeenCalled();
        expect(getBacktestRun).not.toHaveBeenCalled();
        expect(getBacktestEvidence).not.toHaveBeenCalled();
        expect(getHealth).not.toHaveBeenCalled();
        expect(browserFetch).not.toHaveBeenCalled();
    });

    it("opens an exact Strategy URL and reads identity and promotion references without interpreting its open payload", async () => {
        const { router, getStrategy } = renderWorkspace("/strategies");
        const user = userEvent.setup();
        await user.type(screen.getByLabelText("Strategy fingerprint"), strategyId);
        await user.click(screen.getByRole("button", { name: "Open Strategy" }));
        expect(
            await screen.findByRole("heading", { name: "Strategy identity" })
        ).toBeInTheDocument();
        expect(router.state.location.pathname).toBe(`/strategies/${strategyId}`);
        expect(getStrategy).toHaveBeenCalledWith(strategyId, expect.any(AbortSignal));
        expect(screen.getByText("BACKTEST", { selector: "dd" })).toBeInTheDocument();
        expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
        expect(screen.getByText(/server returned 1 promotion records/)).toBeInTheDocument();
        expect(screen.queryByText("Not a browser-owned model")).not.toBeInTheDocument();
        expect(
            screen.getByText(/Promotion stage does not activate LIVE trading/)
        ).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Inspect a Backtest" })).toHaveAttribute(
            "href",
            "/backtest/runs"
        );
    });

    it("rejects invalid Strategy SHA before a request, both in a URL and in the form", async () => {
        const { getStrategy, router } = renderWorkspace(`/strategies/${"A".repeat(64)}`);
        expect(screen.getByRole("alert")).toHaveTextContent("INVALID_QUERY");
        expect(getStrategy).not.toHaveBeenCalled();
        const user = userEvent.setup();
        await user.clear(screen.getByLabelText("Strategy fingerprint"));
        await user.type(screen.getByLabelText("Strategy fingerprint"), "not-a-fingerprint");
        await user.click(screen.getByRole("button", { name: "Open Strategy" }));
        const form = screen.getByRole("form", { name: "Open Strategy" });
        expect(within(form).getByRole("alert")).toHaveTextContent("exact lower-case SHA256");
        expect(router.state.location.pathname).toBe(`/strategies/${"A".repeat(64)}`);
        expect(getStrategy).not.toHaveBeenCalled();
    });

    it("refreshes the mutable promotion projection from the API while preserving immutable identity", async () => {
        const getStrategy = vi
            .fn<ResearchApiClient["getStrategy"]>()
            .mockResolvedValueOnce(strategy)
            .mockResolvedValue({ ...strategy, current_stage: "SIM" });
        renderWorkspace(`/strategies/${strategyId}`, { getStrategy });
        expect(await screen.findByText("BACKTEST", { selector: "dd" })).toBeInTheDocument();
        await userEvent.click(screen.getByRole("button", { name: "Refresh Strategy" }));
        expect(await screen.findByText("SIM", { selector: "dd" })).toBeInTheDocument();
        expect(screen.queryByText("BACKTEST", { selector: "dd" })).not.toBeInTheDocument();
        expect(screen.getByText(strategyId, { selector: "dd" })).toBeInTheDocument();
        expect(getStrategy).toHaveBeenCalledTimes(2);
    });

    it("reports pending Strategy and a Product failure without fabricating an identity view", async () => {
        const pending = deferred<StrategyTransport>();
        renderWorkspace(`/strategies/${strategyId}`, { getStrategy: () => pending.promise });
        expect(screen.getByRole("status")).toHaveTextContent(
            "Loading authoritative Strategy references"
        );
        expect(
            screen.queryByRole("heading", { name: "Strategy identity" })
        ).not.toBeInTheDocument();
        pending.reject(
            new ProductWebError(
                "STRATEGY_REVISION_NOT_FOUND",
                "No frozen revision for this identity",
                404,
                "COMMAND"
            )
        );
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "STRATEGY_REVISION_NOT_FOUND: No frozen revision for this identity"
        );
        expect(screen.queryByText("BACKTEST", { selector: "dd" })).not.toBeInTheDocument();
    });

    it("renders returned promotion text safely and reports genuinely empty reference lists", async () => {
        const payload = "<script>window.untrusted=true</script>";
        const { container } = renderWorkspace(`/strategies/${strategyId}`, {
            getStrategy: () =>
                Promise.resolve({
                    ...strategy,
                    current_stage: payload,
                    freeze_relation_fingerprints: [],
                    promotion_records: []
                })
        });
        expect(await screen.findByText(payload, { selector: "dd" })).toBeInTheDocument();
        expect(container.querySelector("script")).toBeNull();
        expect(
            screen.getByText("No Freeze relation references were returned.")
        ).toBeInTheDocument();
        expect(screen.getByText(/server returned 0 promotion records/)).toBeInTheDocument();
    });
});

describe("exact Backtest lifecycle and Evidence workspace", () => {
    it("starts with an exact Run input and no fabricated list, performance, or execution controls", () => {
        const { getBacktestRun, getBacktestEvidence } = renderWorkspace("/backtest/runs");
        expect(screen.getByRole("heading", { name: "Backtest Workspace" })).toBeInTheDocument();
        expect(screen.getByLabelText("Backtest Run ID")).toHaveValue("");
        expect(screen.getByText(/Product API has no global Backtest Run list/)).toBeInTheDocument();
        expect(
            screen.getByText(/No returns, Sharpe or equity curve are invented here/)
        ).toBeInTheDocument();
        expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
        expect(
            screen.queryByRole("button", { name: /Run Backtest|Cancel|Promote|Activate/ })
        ).not.toBeInTheDocument();
        expect(getBacktestRun).not.toHaveBeenCalled();
        expect(getBacktestEvidence).not.toHaveBeenCalled();
    });

    it("rejects invalid UUID4 before any Run or Evidence request", async () => {
        const invalid = "aaaaaaaa-aaaa-1aaa-8aaa-aaaaaaaaaaaa";
        const { getBacktestRun, getBacktestEvidence, router } = renderWorkspace(
            `/backtest/runs/${invalid}`
        );
        expect(screen.getByRole("alert")).toHaveTextContent("INVALID_QUERY");
        const user = userEvent.setup();
        await user.clear(screen.getByLabelText("Backtest Run ID"));
        await user.type(screen.getByLabelText("Backtest Run ID"), "invalid");
        await user.click(screen.getByRole("button", { name: "Open Backtest" }));
        expect(
            within(screen.getByRole("form", { name: "Open Backtest" })).getByRole("alert")
        ).toHaveTextContent("canonical UUID4");
        expect(router.state.location.pathname).toBe(`/backtest/runs/${invalid}`);
        expect(getBacktestRun).not.toHaveBeenCalled();
        expect(getBacktestEvidence).not.toHaveBeenCalled();
    });

    it.each(["QUEUED", "FAILED"])(
        "shows authoritative %s Run state without asking for premature Evidence",
        async (state) => {
            const run: BacktestRunTransport = {
                ...completedRun,
                state,
                started_at: null,
                finished_at: state === "FAILED" ? completedRun.finished_at : null,
                result_fingerprint: null,
                evidence_fingerprint: null,
                determinism_fingerprint: null,
                failure:
                    state === "FAILED"
                        ? {
                              phase: "EXECUTION",
                              code: "BACKTEST_EXECUTION_FAILED",
                              detail: "Controlled execution failure"
                          }
                        : null
            };
            const { getBacktestEvidence } = renderWorkspace(`/backtest/runs/${runId}`, {
                getBacktestRun: () => Promise.resolve(run)
            });
            expect(
                await screen.findByText(state, { selector: ".product-state strong" })
            ).toBeInTheDocument();
            expect(
                screen.getByText(/Evidence becomes available only after the Run completes/)
            ).toBeInTheDocument();
            expect(getBacktestEvidence).not.toHaveBeenCalled();
            expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
            if (state === "FAILED")
                expect(screen.getByRole("alert")).toHaveTextContent(
                    "EXECUTION · BACKTEST_EXECUTION_FAILED"
                );
        }
    );

    it("opens an exact completed Run and displays only its fully linked immutable manifest", async () => {
        const { router, getBacktestRun, getBacktestEvidence } = renderWorkspace("/backtest/runs");
        const user = userEvent.setup();
        await user.type(screen.getByLabelText("Backtest Run ID"), runId);
        await user.click(screen.getByRole("button", { name: "Open Backtest" }));
        expect(
            await screen.findByText("Verified manifest linked to the exact completed Run.")
        ).toBeInTheDocument();
        expect(router.state.location.pathname).toBe(`/backtest/runs/${runId}`);
        expect(getBacktestRun).toHaveBeenCalledWith(runId, expect.any(AbortSignal));
        expect(getBacktestEvidence).toHaveBeenCalledWith(runId, expect.any(AbortSignal));
        const panel = screen.getByRole("complementary", { name: "Backtest Evidence" });
        expect(within(panel).getByText(evidence.manifest.evidence_fingerprint)).toBeInTheDocument();
        expect(within(panel).getByText(evidence.manifest.result_fingerprint)).toBeInTheDocument();
        expect(
            within(panel).getByText(evidence.manifest.determinism_fingerprint)
        ).toBeInTheDocument();
        expect(
            within(panel).getByText(evidence.manifest.base_dataset_snapshot_fingerprint)
        ).toBeInTheDocument();
        expect(within(panel).getByRole("link", { name: strategyId })).toHaveAttribute(
            "href",
            `/strategies/${strategyId}`
        );
        expect(within(panel).getByText("result.json")).toBeInTheDocument();
        expect(within(panel).getByText("128 bytes · application/json")).toBeInTheDocument();
        expect(
            within(panel).getByText(/manifest does not expose returns, Sharpe or an equity curve/)
        ).toBeInTheDocument();
        expect(
            screen.queryByRole("heading", { name: /Performance|Sharpe|Equity curve/ })
        ).not.toBeInTheDocument();
        expect(screen.queryByText(/^[-+]?\d+(?:\.\d+)?%$/)).not.toBeInTheDocument();
    });

    const mismatches = [
        { field: "backtest_run_id", value: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" },
        { field: "evidence_fingerprint", value: "0".repeat(64) },
        { field: "result_fingerprint", value: "0".repeat(64) },
        { field: "determinism_fingerprint", value: "0".repeat(64) },
        { field: "specification_fingerprint", value: "0".repeat(64) },
        { field: "admission_resolution_fingerprint", value: "0".repeat(64) }
    ];
    it.each(mismatches)(
        "fails closed when manifest $field is not linked to this Run",
        async ({ field, value }) => {
            renderWorkspace(`/backtest/runs/${runId}`, {
                getBacktestEvidence: () =>
                    Promise.resolve({
                        ...evidence,
                        manifest: { ...evidence.manifest, [field]: value }
                    })
            });
            expect(await screen.findByRole("alert")).toHaveTextContent(
                "Run and Evidence references do not match"
            );
            const panel = screen.getByRole("complementary", { name: "Backtest Evidence" });
            expect(
                within(panel).queryByRole("heading", { name: "Artifact metadata" })
            ).not.toBeInTheDocument();
            expect(within(panel).queryByText("result.json")).not.toBeInTheDocument();
            expect(within(panel).queryByRole("link", { name: strategyId })).not.toBeInTheDocument();
        }
    );

    it("rejects completed Runs with no Evidence reference without attempting another authority path", async () => {
        const { getBacktestEvidence } = renderWorkspace(`/backtest/runs/${runId}`, {
            getBacktestRun: () => Promise.resolve({ ...completedRun, evidence_fingerprint: null })
        });
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "completed Run has no Evidence reference"
        );
        expect(getBacktestEvidence).not.toHaveBeenCalled();
        expect(screen.queryByText("result.json")).not.toBeInTheDocument();
    });

    it("keeps pending or unavailable Evidence distinct from completed operational state", async () => {
        const pending = deferred<BacktestEvidenceTransport>();
        renderWorkspace(`/backtest/runs/${runId}`, { getBacktestEvidence: () => pending.promise });
        expect(
            await screen.findByText("COMPLETED", { selector: ".product-state strong" })
        ).toBeInTheDocument();
        expect(screen.getByRole("status")).toHaveTextContent("Loading verified Evidence manifest");
        expect(screen.queryByText("result.json")).not.toBeInTheDocument();
        pending.reject(
            new ProductWebError(
                "BACKTEST_EVIDENCE_UNAVAILABLE",
                "Evidence authority unavailable",
                503,
                "OPERATIONAL"
            )
        );
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "BACKTEST_EVIDENCE_UNAVAILABLE: Evidence authority unavailable"
        );
        expect(
            screen.getByText("COMPLETED", { selector: ".product-state strong" })
        ).toBeInTheDocument();
        expect(screen.queryByText("result.json")).not.toBeInTheDocument();
    });

    it("renders untrusted failure details as text and never as active HTML", async () => {
        const detail = "<img src=x onerror=alert(1)>";
        const { container } = renderWorkspace(`/backtest/runs/${runId}`, {
            getBacktestRun: () =>
                Promise.resolve({
                    ...completedRun,
                    state: "FAILED",
                    evidence_fingerprint: null,
                    failure: { phase: "EXECUTION", code: "BACKTEST_EXECUTION_FAILED", detail }
                })
        });
        expect(await screen.findByText(detail)).toBeInTheDocument();
        expect(container.querySelector("img")).toBeNull();
    });
});

describe("independent read-only System health observations", () => {
    it("shows process LIVE, API NOT_READY and execution DEGRADED independently without granting LIVE permission", async () => {
        const { getHealth } = renderWorkspace("/system/health");
        expect(screen.getByRole("heading", { name: "System Health" })).toBeInTheDocument();
        const process = screen.getByRole("region", { name: "HTTP process" });
        const readiness = screen.getByRole("region", { name: "API readiness" });
        const execution = screen.getByRole("region", { name: "Backtest execution" });
        expect(
            await within(process).findByText("LIVE", { selector: "strong" })
        ).toBeInTheDocument();
        expect(
            within(readiness).getByText("NOT_READY", { selector: "strong" })
        ).toBeInTheDocument();
        expect(within(execution).getByText("DEGRADED", { selector: "strong" })).toBeInTheDocument();
        expect(within(readiness).getByText("KERNEL_RECOVERING")).toBeInTheDocument();
        expect(within(execution).getByText("BACKTEST_WORKER_ABSENT")).toBeInTheDocument();
        expect(within(process).getByText(/LIVE here never means live trading/)).toBeInTheDocument();
        expect(screen.getByText(/observations do not authorize LIVE trading/)).toBeInTheDocument();
        expect(getHealth).toHaveBeenCalledTimes(3);
        for (const selector of ["live", "ready", "execution"]) {
            expect(getHealth).toHaveBeenCalledWith(selector, expect.any(AbortSignal));
        }
        expect(
            screen.queryByRole("button", { name: /Start|Activate|Authorize|Stop/ })
        ).not.toBeInTheDocument();
    });

    it("does not retain a previous healthy fact on screen after its refresh fails", async () => {
        let readyRequests = 0;
        const getHealth = vi.fn<ResearchApiClient["getHealth"]>().mockImplementation((selector) => {
            if (selector !== "ready") return Promise.resolve(health[selector]);
            readyRequests += 1;
            return readyRequests === 1
                ? Promise.resolve({
                      status: "READY",
                      checks: { product_kernel: "READY" },
                      reason: null
                  })
                : Promise.reject(
                      new ResearchWebError("TRANSPORT_ERROR", "Readiness connection lost")
                  );
        });
        renderWorkspace("/system/health", { getHealth });
        const readiness = screen.getByRole("region", { name: "API readiness" });
        expect(
            await within(readiness).findByText("READY", { selector: "strong" })
        ).toBeInTheDocument();
        await userEvent.click(
            within(readiness).getByRole("button", { name: "Refresh API readiness" })
        );
        expect(await within(readiness).findByRole("alert")).toHaveTextContent(
            "Readiness connection lost"
        );
        expect(within(readiness).queryByText("READY")).not.toBeInTheDocument();
        expect(within(readiness).queryByText("product_kernel")).not.toBeInTheDocument();
        expect(
            within(readiness).queryByText("Last response read by this browser:")
        ).not.toBeInTheDocument();
        expect(
            within(screen.getByRole("region", { name: "HTTP process" })).getByText("LIVE", {
                selector: "strong"
            })
        ).toBeInTheDocument();
        expect(getHealth).toHaveBeenCalledTimes(4);
    });

    it("keeps pending and failed health authorities independent of a reachable process", async () => {
        const pending = deferred<ProductHealthTransport>();
        renderWorkspace("/system/health", {
            getHealth: (selector) => {
                if (selector === "live") return Promise.resolve(health.live);
                if (selector === "ready") return pending.promise;
                return Promise.reject(
                    new ResearchWebError("CONTRACT_ERROR", "Invalid execution health response")
                );
            }
        });
        const readiness = screen.getByRole("region", { name: "API readiness" });
        expect(within(readiness).getByRole("status")).toHaveTextContent("Reading health response");
        const process = screen.getByRole("region", { name: "HTTP process" });
        expect(
            await within(process).findByText("LIVE", { selector: "strong" })
        ).toBeInTheDocument();
        const execution = screen.getByRole("region", { name: "Backtest execution" });
        expect(await within(execution).findByRole("alert")).toHaveTextContent(
            "Invalid execution health response"
        );
        expect(
            within(execution).queryByText("DEGRADED", { selector: "strong" })
        ).not.toBeInTheDocument();
        pending.resolve(health.ready);
        expect(
            await within(readiness).findByText("NOT_READY", { selector: "strong" })
        ).toBeInTheDocument();
    });

    it("escapes returned health reasons and distinguishes an empty checks map", async () => {
        const reason = "<script>window.untrusted=true</script>";
        const { container } = renderWorkspace("/system/health", {
            getHealth: () => Promise.resolve({ status: "UNKNOWN", checks: {}, reason })
        });
        const process = screen.getByRole("region", { name: "HTTP process" });
        expect(await within(process).findByText(reason)).toBeInTheDocument();
        expect(
            within(process).getByText("No individual checks were returned.")
        ).toBeInTheDocument();
        expect(container.querySelector("script")).toBeNull();
    });
});
