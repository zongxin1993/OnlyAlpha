import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { StrategyWorkflow } from "./StrategyWorkflow";
import * as api from "./api";
import * as manualApi from "./manualApi";

vi.mock("./api", async (original) => ({
    ...(await original<typeof api>()),
    loadCreationContext: vi.fn(),
    saveDefinition: vi.fn(),
    prepareResearch: vi.fn(),
    loadPreparation: vi.fn(),
    confirmResearch: vi.fn(),
    loadResearch: vi.fn(),
    freezeStrategy: vi.fn(),
    loadStrategy: vi.fn(),
    resumePreparation: vi.fn(),
    cancelPreparation: vi.fn(),
    cancelResearch: vi.fn(),
    loadWorkflows: vi.fn(),
    loadWorkflow: vi.fn()
}));
vi.mock("./manualApi", async (original) => ({
    ...(await original<typeof manualApi>()),
    loadFactors: vi.fn()
}));
const factor = "a".repeat(64),
    study = "b".repeat(64),
    strategy = "c".repeat(64);
const command = "00000000-0000-4000-8000-000000000001";
const run = "00000000-0000-4000-8000-000000000002";
const context = {
    schema_version: 1 as const,
    factor_name: "价量动量",
    formula: "(close / lag(close,20) - 1) * volume / mean(volume,20)",
    factor_proposal_fingerprint: factor,
    study_proposal_fingerprint: study,
    draft: {
        schema_version: 1 as const,
        strategy_id: "private.strategy.btc_momentum",
        semantic_version: "1",
        base_revision_fingerprint: null,
        definition: {},
        description: "BTCUSDT 价量动量",
        tags: []
    },
    source: { instrument_id: "BTCUSDT.BINANCE" },
    research_context: {},
    release_manifest_fingerprint: factor,
    expected_active_generation: factor,
    initialize_fresh_runtime: false,
    existing_preparations: []
};
const authoring = {
    schema_version: 1 as const,
    strategy_id: context.draft.strategy_id,
    draft: context.draft,
    draft_fingerprint: study,
    current_revision_fingerprint: strategy,
    revisions: [
        { ...context.draft, revision_fingerprint: strategy, definition_fingerprint: factor }
    ]
};
const ready = {
    schema_version: 1 as const,
    command_id: command,
    revision: "1",
    state: "READY",
    phase: "READY_FOR_HUMAN_CONFIRMATION",
    prepared_study_fingerprint: study,
    research_command_id: run,
    research_outcome: "NOT_SUBMITTED",
    run_id: null,
    readiness: { state: "VERIFIED", code: null },
    detail: null
};
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
    sessionStorage.clear();
});
function page() {
    return render(
        <MemoryRouter initialEntries={[`/strategies/new?factor=${factor}&study=${study}&preparation=${command}`]}>
            <StrategyWorkflow />
        </MemoryRouter>
    );
}
it("routes a fresh Study-only selection to normal manual strategy authoring without creating or starting research", async () => {
    vi.mocked(api.loadCreationContext).mockResolvedValue(context);
    vi.mocked(manualApi.loadFactors).mockResolvedValue([]);
    const identities = vi.spyOn(crypto, "randomUUID");
    render(
        <StrictMode>
            <MemoryRouter initialEntries={[`/strategies/new?factor=${factor}&study=${study}`]}>
                <StrategyWorkflow />
            </MemoryRouter>
        </StrictMode>
    );
    expect(await screen.findByRole("heading", { name: "新建回测策略" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "已保存因子" })).toBeVisible();
    expect(screen.getByRole("link", { name: "回测记录" })).toHaveAttribute("href", "/backtest");
    expect(screen.queryByRole("button", { name: "准备研究数据" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始策略研究" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Fingerprint|Reducer|DTO|Lease|Revision Hash/)).not.toBeInTheDocument();
    expect(api.loadCreationContext).not.toHaveBeenCalled();
    expect(api.saveDefinition).not.toHaveBeenCalled();
    expect(api.prepareResearch).not.toHaveBeenCalled();
    expect(api.confirmResearch).not.toHaveBeenCalled();
    expect(api.freezeStrategy).not.toHaveBeenCalled();
    expect(identities).not.toHaveBeenCalled();
});
it("retains the original Study-bound saved definition address without reopening research preparation or start", async () => {
    vi.mocked(api.loadCreationContext).mockResolvedValue(context);
    vi.mocked(api.loadWorkflow).mockResolvedValue({
        schema_version: 1,
        strategy_id: authoring.strategy_id,
        authoring: { ...authoring, current_revision_fingerprint: null },
        preparations: [],
        backtest_preparations: []
    });
    vi.mocked(api.saveDefinition).mockResolvedValue(authoring);
    render(
        <MemoryRouter initialEntries={[`/strategies/${authoring.strategy_id}?factor=${factor}&study=${study}`]}>
            <StrategyWorkflow />
        </MemoryRouter>
    );
    const save = await screen.findByRole("button", { name: "保存策略定义" });
    await waitFor(() => { expect(save).toBeEnabled(); });
    fireEvent.click(save);
    await waitFor(() => { expect(api.saveDefinition).toHaveBeenCalledExactlyOnceWith(context); });
    expect(await screen.findByText("策略定义已保存")).toBeVisible();
    expect(screen.queryByRole("button", { name: "准备研究数据" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始策略研究" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "配置普通回测" })).toBeVisible();
    expect(api.loadCreationContext).toHaveBeenCalledWith(factor, study, authoring.strategy_id);
    expect(api.prepareResearch).not.toHaveBeenCalled();
    expect(api.confirmResearch).not.toHaveBeenCalled();
});
it("keeps Freeze unavailable without verified full strategy evidence", async () => {
    vi.mocked(api.loadCreationContext).mockResolvedValue({
        ...context,
        existing_preparations: [{ ...ready, research_outcome: "ACCEPTED", run_id: run }]
    });
    vi.mocked(api.loadPreparation).mockResolvedValue({
        ...ready,
        research_outcome: "ACCEPTED",
        run_id: run
    });
    vi.mocked(api.loadResearch).mockResolvedValue({
        schema_version: 1,
        run_id: run,
        state: "COMPLETED",
        report: null,
        report_status: { state: "UNAVAILABLE" }
    });
    page();
    expect(await screen.findByText(/研究结果暂时无法核验/)).toBeVisible();
    expect(screen.getByRole("button", { name: "冻结策略" })).toBeDisabled();
    expect(api.freezeStrategy).not.toHaveBeenCalled();
});

it("observes original preparation and run when current new-work context is unavailable", async () => {
    vi.mocked(api.loadCreationContext).mockRejectedValue(
        new Error("current source no longer available")
    );
    vi.mocked(api.loadPreparation).mockResolvedValue({
        ...ready,
        research_outcome: "ACCEPTED",
        run_id: run
    });
    vi.mocked(api.loadResearch).mockResolvedValue({
        schema_version: 1,
        run_id: run,
        state: "RUNNING",
        report: null
    });
    const identities = vi.spyOn(crypto, "randomUUID");
    render(
        <MemoryRouter
            initialEntries={[
                `/strategies/private.strategy.btc_momentum?factor=${factor}&study=${study}&preparation=${command}&run=${run}`
            ]}
        >
            <StrategyWorkflow />
        </MemoryRouter>
    );
    expect(await screen.findByText("正在验证策略")).toBeVisible();
    await waitFor(() => {
        expect(api.loadPreparation).toHaveBeenCalled();
    });
    expect(vi.mocked(api.loadPreparation).mock.calls[0]?.[0]).toBe(command);
    expect(vi.mocked(api.loadResearch).mock.calls[0]?.[0]).toBe(run);
    expect(api.saveDefinition).not.toHaveBeenCalled();
    expect(api.prepareResearch).not.toHaveBeenCalled();
    expect(api.confirmResearch).not.toHaveBeenCalled();
    expect(api.freezeStrategy).not.toHaveBeenCalled();
    expect(identities).not.toHaveBeenCalled();
});

it.each(["BLOCKED", "INPUT_PENDING"])(
    "offers explicit continuation for an existing %s preparation without starting research",
    async (state) => {
        const pending = {
            ...ready,
            state,
            phase: "ACQUISITION",
            revision: "9007199254740993",
            prepared_study_fingerprint: null,
            readiness: { state: "NOT_APPLICABLE", code: null }
        };
        vi.mocked(api.loadCreationContext).mockResolvedValue({
            ...context,
            existing_preparations: [pending]
        });
        vi.mocked(api.loadPreparation).mockResolvedValue(pending);
        vi.mocked(api.resumePreparation).mockResolvedValue(ready);
        page();
        fireEvent.click(await screen.findByRole("button", { name: "继续准备" }));
        await waitFor(() => {
            expect(api.resumePreparation).toHaveBeenCalledExactlyOnceWith(pending);
        });
        expect(await screen.findByText("原研究准备已完成")).toBeVisible();
        expect(screen.queryByRole("button", { name: "开始策略研究" })).not.toBeInTheDocument();
        expect(screen.getByRole("link", { name: "配置普通回测" })).toHaveAttribute("href", "/strategies/new");
        expect(api.prepareResearch).not.toHaveBeenCalled();
        expect(api.confirmResearch).not.toHaveBeenCalled();
    }
);
it("offers preparation cancellation and displays the requested state without claiming it has drained", async () => {
    const preparing = {
        ...ready,
        state: "RUNNING",
        phase: "ACQUISITION",
        prepared_study_fingerprint: null,
        readiness: { state: "NOT_APPLICABLE", code: null }
    };
    vi.mocked(api.loadCreationContext).mockResolvedValue({
        ...context,
        existing_preparations: [preparing]
    });
    vi.mocked(api.loadPreparation).mockResolvedValue(preparing);
    vi.mocked(api.cancelPreparation).mockResolvedValue({
        ...preparing,
        state: "CANCEL_REQUESTED",
        revision: "2"
    });
    page();
    fireEvent.click(await screen.findByRole("button", { name: "取消准备" }));
    await waitFor(() => {
        expect(api.cancelPreparation).toHaveBeenCalledExactlyOnceWith(preparing);
    });
    expect(await screen.findByText("正在取消研究准备")).toBeVisible();
    expect(screen.queryByText("研究准备已取消")).not.toBeInTheDocument();
    expect(api.confirmResearch).not.toHaveBeenCalled();
    expect(api.prepareResearch).not.toHaveBeenCalled();
});
it("offers cancellation of the actual running research and preserves its pending outcome", async () => {
    const running = {
        schema_version: 1 as const,
        kind: "PRIVATE_STRATEGY",
        run_id: run,
        state: "RUNNING",
        revision: "3",
        report: null
    };
    vi.mocked(api.loadCreationContext).mockResolvedValue({
        ...context,
        existing_preparations: [{ ...ready, research_outcome: "ACCEPTED", run_id: run }]
    });
    vi.mocked(api.loadPreparation).mockResolvedValue({
        ...ready,
        research_outcome: "ACCEPTED",
        run_id: run
    });
    vi.mocked(api.loadResearch).mockResolvedValue(running);
    vi.mocked(api.cancelResearch).mockResolvedValue({
        ...running,
        state: "CANCEL_REQUESTED",
        revision: "4"
    });
    page();
    fireEvent.click(await screen.findByRole("button", { name: "取消研究" }));
    await waitFor(() => {
        expect(api.cancelResearch).toHaveBeenCalledExactlyOnceWith(running);
    });
    expect(await screen.findByText("正在取消策略研究")).toBeVisible();
    expect(screen.getByRole("button", { name: "冻结策略" })).toBeDisabled();
    expect(api.freezeStrategy).not.toHaveBeenCalled();
    expect(api.confirmResearch).not.toHaveBeenCalled();
});
it("opens saved workflow history from the strategy menu without requiring current factor or source access", async () => {
    const accepted = { ...ready, research_outcome: "ACCEPTED", run_id: run };
    const history = {
        strategy_id: authoring.strategy_id,
        authoring,
        preparations: [accepted],
        backtest_preparations: []
    };
    vi.mocked(api.loadWorkflows).mockResolvedValue({ schema_version: 1, items: [history] });
    vi.mocked(api.loadWorkflow).mockResolvedValue({ schema_version: 1, ...history });
    vi.mocked(api.loadStrategy).mockResolvedValue(authoring);
    vi.mocked(api.loadPreparation).mockResolvedValue(accepted);
    vi.mocked(api.loadResearch).mockResolvedValue({
        schema_version: 1,
        kind: "PRIVATE_STRATEGY",
        run_id: run,
        state: "RUNNING",
        report: null
    });
    const identities = vi.spyOn(crypto, "randomUUID");
    render(
        <MemoryRouter initialEntries={["/strategies"]}>
            <StrategyWorkflow />
        </MemoryRouter>
    );
    expect(await screen.findByText("BTCUSDT 价量动量")).toBeVisible();
    const open = screen.getByRole("link", { name: "查看研究" });
    const target = new URL(open.getAttribute("href") ?? "", "http://localhost");
    expect(target.pathname).toBe(`/strategies/${authoring.strategy_id}`);
    expect(target.searchParams.get("preparation")).toBe(command);
    expect(target.searchParams.get("run")).toBe(run);
    expect(target.searchParams.has("factor")).toBe(false);
    expect(target.searchParams.has("study")).toBe(false);
    fireEvent.click(open);
    expect(await screen.findByText("正在验证策略")).toBeVisible();
    await waitFor(() => {
        expect(api.loadWorkflow).toHaveBeenCalledWith(authoring.strategy_id);
    });
    expect(api.loadCreationContext).not.toHaveBeenCalled();
    expect(api.saveDefinition).not.toHaveBeenCalled();
    expect(api.prepareResearch).not.toHaveBeenCalled();
    expect(api.confirmResearch).not.toHaveBeenCalled();
    expect(identities).not.toHaveBeenCalled();
});

it.each(["ready-preparation", "completed-preparation", "completed-run"])(
    "rejects a foreign %s history reference before starting or freezing another strategy",
    async (mode) => {
        const otherPreparation = "00000000-0000-4000-8000-000000000081";
        const otherRun = "00000000-0000-4000-8000-000000000082";
        const own = { ...ready, strategy_id: authoring.strategy_id };
        const foreign = {
            ...ready,
            strategy_id: "private.strategy.other",
            command_id: otherPreparation,
            research_command_id: otherRun,
            research_outcome: mode === "ready-preparation" ? "NOT_SUBMITTED" : "ACCEPTED",
            run_id: mode === "ready-preparation" ? null : otherRun
        };
        vi.mocked(api.loadCreationContext).mockResolvedValue({
            ...context,
            existing_preparations: [own]
        });
        vi.mocked(api.loadWorkflow).mockResolvedValue({
            schema_version: 1,
            strategy_id: authoring.strategy_id,
            authoring,
            preparations: [own],
            backtest_preparations: []
        });
        vi.mocked(api.loadPreparation).mockResolvedValue(foreign);
        vi.mocked(api.loadResearch).mockResolvedValue({
            schema_version: 1,
            kind: "PRIVATE_STRATEGY",
            run_id: otherRun,
            state: "COMPLETED",
            revision: "3",
            report_status: { state: "VERIFIED" },
            report: {
                candidate_fingerprint: "d".repeat(64),
                research_result_fingerprint: "e".repeat(64),
                start_at: "2025-01-02T12:00:00Z",
                end_at: "2025-01-03T00:00:00Z",
                observation_count: 720,
                warmup_bars: 20,
                node_count: 6,
                execution_graph_verified: true,
                limitations: []
            }
        });
        const reference =
            mode === "completed-run"
                ? `run=${otherRun}`
                : `preparation=${otherPreparation}${mode === "completed-preparation" ? `&run=${otherRun}` : ""}`;
        render(
            <MemoryRouter
                initialEntries={[
                    `/strategies/${authoring.strategy_id}?factor=${factor}&study=${study}&${reference}`
                ]}
            >
                <StrategyWorkflow />
            </MemoryRouter>
        );
        expect(
            await screen.findByText("所选研究与当前策略不一致，请从研究记录重新选择。")
        ).toBeVisible();
        expect(screen.getByRole("button", { name: "冻结策略" })).toBeDisabled();
        expect(screen.queryByRole("button", { name: "开始策略研究" })).not.toBeInTheDocument();
        expect(api.confirmResearch).not.toHaveBeenCalled();
        expect(api.freezeStrategy).not.toHaveBeenCalled();
        expect(api.prepareResearch).not.toHaveBeenCalled();
        expect(api.saveDefinition).not.toHaveBeenCalled();
    }
);

const completedStrategy = {
    schema_version: 1,
    kind: "PRIVATE_STRATEGY",
    run_id: run,
    state: "COMPLETED",
    revision: "3",
    report_status: { state: "VERIFIED" },
    report: {
        candidate_fingerprint: "d".repeat(64),
        research_result_fingerprint: "e".repeat(64),
        start_at: "2025-01-02T12:00:00Z",
        end_at: "2025-01-03T00:00:00Z",
        observation_count: 720,
        warmup_bars: 20,
        node_count: 6,
        execution_graph_verified: true,
        limitations: []
    }
} satisfies Awaited<ReturnType<typeof api.loadResearch>>;
it("reloads a valid original preparation and run and freezes only its verified report", async () => {
    const unobserved = {
        ...ready,
        strategy_id: authoring.strategy_id,
        strategy_revision_fingerprint: strategy,
        research_outcome: "UNOBSERVED",
        run_id: null
    };
    const accepted = { ...unobserved, research_outcome: "ACCEPTED", run_id: run };
    vi.mocked(api.loadCreationContext).mockResolvedValue({
        ...context,
        existing_preparations: [unobserved]
    });
    vi.mocked(api.loadWorkflow).mockResolvedValue({
        schema_version: 1,
        strategy_id: authoring.strategy_id,
        authoring,
        preparations: [unobserved],
        backtest_preparations: []
    });
    vi.mocked(api.loadPreparation).mockResolvedValue(accepted);
    vi.mocked(api.loadResearch).mockResolvedValue(completedStrategy);
    vi.mocked(api.freezeStrategy).mockResolvedValue({
        schema_version: 1,
        command_id: command,
        strategy_fingerprint: strategy,
        freeze_relation_fingerprint: study,
        accepted_at: "2026-11-02T00:00:00Z",
        replayed: false
    });
    render(
        <MemoryRouter
            initialEntries={[
                `/strategies/${authoring.strategy_id}?factor=${factor}&study=${study}&preparation=${command}&run=${run}`
            ]}
        >
            <StrategyWorkflow />
        </MemoryRouter>
    );
    expect(await screen.findByText("完整策略规则验证通过")).toBeVisible();
    expect(screen.getByRole("button", { name: "冻结策略" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "冻结策略" }));
    await waitFor(() => {
        expect(api.freezeStrategy).toHaveBeenCalledExactlyOnceWith(completedStrategy);
    });
    const next = await screen.findByRole("link", { name: "配置回测" });
    const destination = new URL(next.getAttribute("href") ?? "", "http://localhost");
    expect(destination.pathname).toBe("/backtest/new");
    expect(Object.fromEntries(destination.searchParams)).toEqual({
        strategy_id: authoring.strategy_id,
        strategy_revision_fingerprint: strategy
    });
    expect(api.confirmResearch).not.toHaveBeenCalled();
    expect(api.prepareResearch).not.toHaveBeenCalled();
});
it("does not splice two preparations of the same strategy while the selected preparation is still being read", async () => {
    const another = "00000000-0000-4000-8000-000000000091";
    const firstRun = "00000000-0000-4000-8000-000000000092";
    const first = {
        ...ready,
        strategy_id: authoring.strategy_id,
        research_outcome: "ACCEPTED",
        run_id: firstRun
    };
    const second = {
        ...ready,
        strategy_id: authoring.strategy_id,
        command_id: another,
        research_outcome: "ACCEPTED",
        run_id: run
    };
    let finish!: (value: typeof first) => void;
    vi.mocked(api.loadCreationContext).mockResolvedValue({
        ...context,
        existing_preparations: [first, second]
    });
    vi.mocked(api.loadWorkflow).mockResolvedValue({
        schema_version: 1,
        strategy_id: authoring.strategy_id,
        authoring,
        preparations: [first, second],
        backtest_preparations: []
    });
    vi.mocked(api.loadPreparation).mockImplementation(
        () =>
            new Promise((resolve) => {
                finish = resolve;
            })
    );
    vi.mocked(api.loadResearch).mockResolvedValue(completedStrategy);
    render(
        <MemoryRouter
            initialEntries={[
                `/strategies/${authoring.strategy_id}?factor=${factor}&study=${study}&preparation=${command}&run=${run}`
            ]}
        >
            <StrategyWorkflow />
        </MemoryRouter>
    );
    await waitFor(() => {
        expect(api.loadResearch).toHaveBeenCalledWith(run);
    });
    await act(async () => {
        await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: "冻结策略" })).toBeDisabled();
    await act(() =>
        Promise.resolve().then(() => {
            finish(first);
        })
    );
    expect(
        await screen.findByText("所选研究与当前策略不一致，请从研究记录重新选择。")
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "冻结策略" })).toBeDisabled();
    expect(api.freezeStrategy).not.toHaveBeenCalled();
    expect(api.confirmResearch).not.toHaveBeenCalled();
});
it("does not authorize Freeze from another historical run when the original preparation read fails", async () => {
    const accepted = {
        ...ready,
        strategy_id: authoring.strategy_id,
        research_outcome: "ACCEPTED",
        run_id: run
    };
    let finish!: (value: Awaited<ReturnType<typeof api.loadResearch>>) => void;
    vi.mocked(api.loadCreationContext).mockResolvedValue({
        ...context,
        existing_preparations: [accepted]
    });
    vi.mocked(api.loadWorkflow).mockResolvedValue({
        schema_version: 1,
        strategy_id: authoring.strategy_id,
        authoring,
        preparations: [accepted],
        backtest_preparations: []
    });
    vi.mocked(api.loadPreparation).mockRejectedValue(new Error("original preparation unavailable"));
    vi.mocked(api.loadResearch).mockImplementation(
        () =>
            new Promise((resolve) => {
                finish = resolve;
            })
    );
    render(
        <MemoryRouter
            initialEntries={[
                `/strategies/${authoring.strategy_id}?factor=${factor}&study=${study}&preparation=${command}&run=${run}`
            ]}
        >
            <StrategyWorkflow />
        </MemoryRouter>
    );
    await waitFor(() => {
        expect(api.loadPreparation).toHaveBeenCalledWith(command);
    });
    await waitFor(() => {
        expect(api.loadResearch).toHaveBeenCalledWith(run);
    });
    await act(() =>
        Promise.resolve().then(() => {
            finish(completedStrategy);
        })
    );
    expect(screen.getByRole("button", { name: "冻结策略" })).toBeDisabled();
    expect(api.freezeStrategy).not.toHaveBeenCalled();
    expect(api.confirmResearch).not.toHaveBeenCalled();
});

it.each(["creation", "inventory"] as const)(
    "loads the ordinary %s view under Shipping StrictMode without submitting work",
    async (entry) => {
        vi.mocked(api.loadCreationContext).mockResolvedValue(context);
        vi.mocked(manualApi.loadFactors).mockResolvedValue([]);
        vi.mocked(api.loadWorkflows).mockResolvedValue({
            schema_version: 1,
            items: [
                {
                    strategy_id: authoring.strategy_id,
                    authoring,
                    preparations: [],
                    backtest_preparations: []
                }
            ]
        });
        const path =
            entry === "creation"
                ? `/strategies/new?factor=${factor}&study=${study}`
                : "/strategies";
        render(
            <StrictMode>
                <MemoryRouter initialEntries={[path]}>
                    <StrategyWorkflow />
                </MemoryRouter>
            </StrictMode>
        );
        if (entry === "creation") {
            expect(await screen.findByRole("heading", { name: "新建回测策略" })).toBeVisible();
            expect(screen.getByRole("combobox", { name: "已保存因子" })).toBeVisible();
            expect(screen.getByRole("link", { name: "回测记录" })).toHaveAttribute("href", "/backtest");
            expect(api.loadCreationContext).not.toHaveBeenCalled();
        } else {
            expect(await screen.findByText("BTCUSDT 价量动量")).toBeVisible();
            expect(screen.getByRole("link", { name: "查看策略" })).toHaveAttribute(
                "href",
                `/strategies/${authoring.strategy_id}`
            );
            expect(api.loadWorkflows).toHaveBeenCalled();
        }
        expect(api.saveDefinition).not.toHaveBeenCalled();
        expect(api.prepareResearch).not.toHaveBeenCalled();
        expect(api.confirmResearch).not.toHaveBeenCalled();
        expect(api.freezeStrategy).not.toHaveBeenCalled();
        expect(api.resumePreparation).not.toHaveBeenCalled();
        expect(api.cancelPreparation).not.toHaveBeenCalled();
        expect(api.cancelResearch).not.toHaveBeenCalled();
    }
);

// Original workflow and exact preparation/report queries supply continuation
// context. Loading fresh Factor/Study creation defaults is not a prerequisite.
it.each(["ready", "completed"] as const)(
    "continues an existing %s strategy from ordinary history without fresh creation context",
    async (stage) => {
        const original = {
            ...ready,
            strategy_id: authoring.strategy_id,
            research_outcome: stage === "completed" ? "ACCEPTED" : "NOT_SUBMITTED",
            run_id: stage === "completed" ? run : null
        };
        vi.mocked(api.loadWorkflows).mockResolvedValue({
            schema_version: 1,
            items: [
                {
                    strategy_id: authoring.strategy_id,
                    authoring,
                    preparations: [original],
                    backtest_preparations: []
                }
            ]
        });
        vi.mocked(api.loadWorkflow).mockResolvedValue({
            schema_version: 1,
            strategy_id: authoring.strategy_id,
            authoring,
            preparations: [original],
            backtest_preparations: []
        });
        vi.mocked(api.loadPreparation).mockResolvedValue(original);
        vi.mocked(api.loadResearch).mockResolvedValue(completedStrategy);
        vi.mocked(api.confirmResearch).mockResolvedValue({
            schema_version: 1,
            research_command_id: run,
            state: "ACCEPTED",
            run_id: run
        });
        vi.mocked(api.freezeStrategy).mockResolvedValue({
            schema_version: 1,
            command_id: command,
            strategy_fingerprint: strategy,
            freeze_relation_fingerprint: study,
            accepted_at: "2026-11-02T00:00:00Z",
            replayed: false
        });
        render(
            <MemoryRouter initialEntries={["/strategies"]}>
                <StrategyWorkflow />
            </MemoryRouter>
        );
        fireEvent.click(await screen.findByRole("link", { name: "查看研究" }));
        await waitFor(() => {
            expect(api.loadPreparation).toHaveBeenCalledWith(command);
        });
        expect(api.loadCreationContext).not.toHaveBeenCalled();
        expect(api.confirmResearch).not.toHaveBeenCalled();
        expect(api.freezeStrategy).not.toHaveBeenCalled();
        expect(screen.queryByRole("button", { name: "准备研究数据" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "开始策略研究" })).not.toBeInTheDocument();
        if (stage === "ready") {
            expect(await screen.findByText("原研究准备已完成")).toBeVisible();
            const target = new URL(screen.getByRole("link", { name: "配置普通回测" }).getAttribute("href") ?? "", "http://localhost");
            expect(target.pathname).toBe("/backtest/new");
            expect(Object.fromEntries(target.searchParams)).toEqual({
                strategy_id: authoring.strategy_id,
                strategy_revision_fingerprint: strategy
            });
            expect(screen.getByRole("button", { name: "取消准备" })).toBeEnabled();
            expect(api.loadResearch).not.toHaveBeenCalled();
        } else {
            const freeze = await screen.findByRole("button", { name: "冻结策略" });
            await waitFor(() => { expect(freeze).toBeEnabled(); });
            fireEvent.click(freeze);
            await waitFor(() => {
                expect(api.freezeStrategy).toHaveBeenCalledExactlyOnceWith(completedStrategy);
            });
            expect(await screen.findByRole("link", { name: "配置回测" })).toBeVisible();
        }
        expect(api.confirmResearch).not.toHaveBeenCalled();
        expect(api.saveDefinition).not.toHaveBeenCalled();
        expect(api.prepareResearch).not.toHaveBeenCalled();
    }
);

it("opens a saved strategy directly for normal backtest without a Study, Source or model", async () => {
    vi.mocked(api.loadWorkflows).mockResolvedValue({
        schema_version: 1,
        items: [
            {
                strategy_id: authoring.strategy_id,
                authoring,
                preparations: [],
                backtest_preparations: []
            }
        ]
    });
    vi.mocked(api.loadWorkflow).mockResolvedValue({
        schema_version: 1,
        strategy_id: authoring.strategy_id,
        authoring,
        preparations: [],
        backtest_preparations: []
    });
    const identities = vi.spyOn(crypto, "randomUUID");
    render(
        <StrictMode>
            <MemoryRouter initialEntries={["/strategies"]}>
                <StrategyWorkflow />
            </MemoryRouter>
        </StrictMode>
    );
    fireEvent.click(await screen.findByRole("link", { name: "查看策略" }));
    const select = await screen.findByRole("link", { name: "配置回测" });
    const target = new URL(select.getAttribute("href") ?? "", "http://localhost");
    expect(target.pathname).toBe("/backtest/new");
    expect(Object.fromEntries(target.searchParams)).toEqual({
        strategy_id: authoring.strategy_id,
        strategy_revision_fingerprint: strategy
    });
    expect(api.loadCreationContext).not.toHaveBeenCalled();
    expect(api.saveDefinition).not.toHaveBeenCalled();
    expect(api.prepareResearch).not.toHaveBeenCalled();
    expect(api.confirmResearch).not.toHaveBeenCalled();
    expect(identities).not.toHaveBeenCalled();
});
it("keeps an unpublished strategy discoverable and requires explicit exact Factor selection before saving", async () => {
    vi.mocked(api.loadWorkflow).mockResolvedValue({
        schema_version: 1,
        strategy_id: authoring.strategy_id,
        authoring: { ...authoring, current_revision_fingerprint: null },
        preparations: [],
        backtest_preparations: []
    });
    render(
        <MemoryRouter initialEntries={[`/strategies/${authoring.strategy_id}`]}>
            <StrategyWorkflow />
        </MemoryRouter>
    );
    const select = await screen.findByRole("link", { name: "选择因子继续保存" });
    const target = new URL(select.getAttribute("href") ?? "", "http://localhost");
    expect(target.pathname).toBe("/strategies/new");
    expect(target.searchParams.get("strategy_id")).toBe(authoring.strategy_id);
    expect(api.loadCreationContext).not.toHaveBeenCalled();
    expect(api.prepareResearch).not.toHaveBeenCalled();
    expect(api.saveDefinition).not.toHaveBeenCalled();
});
