import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BacktestPage } from "./BacktestPage";
import * as api from "./api";

vi.mock("../strategies/api", () => ({ loadWorkflows: vi.fn() }));
vi.mock("./api", async (original) => ({
    ...(await original<typeof api>()),
    loadRuns: vi.fn(),
    loadRun: vi.fn(),
    loadResult: vi.fn(),
    prepareBacktest: vi.fn(),
    pendingPreparation: vi.fn(),
    loadCreationContext: vi.fn(),
    loadSources: vi.fn(),
    loadPreparation: vi.fn(),
    confirmBacktest: vi.fn(),
    cancelBacktest: vi.fn(),
    cancelPreparation: vi.fn(),
    resumePreparation: vi.fn(),
    loadModels: vi.fn(),
    interpretResult: vi.fn(),
    loadInterpretation: vi.fn()
}));
vi.mock("echarts", () => ({
    init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })
}));
const run = "12345678-1234-4234-8234-123456789abc";
const preparation = "12345678-1234-4234-8234-123456789abd";
const research = "12345678-1234-4234-8234-123456789abe";
const sha = "a".repeat(64);
const ready = {
    profile: "BTC_SPOT_NEXT_OPEN_BACKTEST_V1",
    reserved_run_id: run,
    source: {
        integration_id: "12345678-1234-4234-8234-123456789ab1",
        integration_revision_fingerprint: sha,
        expected_type_id: "binance.spot.market_data",
        source_id: "binance.spot.market_data.live",
        environment: "LIVE",
        instrument_id: "BTCUSDT.BINANCE"
    },
    detail: null,
    accepted_at: "2026-11-02T00:00:00Z",
    schema_version: 2,
    command_id: preparation,
    backtest_command_id: "12345678-1234-4234-8234-123456789abf",
    revision: "4",
    state: "READY",
    phase: "READY_FOR_HUMAN_CONFIRMATION",
    preparation_fingerprint: sha,
    readiness: { state: "VERIFIED", code: null },
    backtest_outcome: "NOT_SUBMITTED",
    run_id: null,
    origin: {
        kind: "MANUAL_STRATEGY",
        strategy_id: "private.strategy.btc_momentum",
        strategy_revision_fingerprint: sha
    },
    strategy_fingerprint: sha,
    validation_fingerprint: sha,
    freeze_relation_fingerprint: sha,
    qualification_decision_fingerprint: sha,
    promotion_fingerprint: sha
} satisfies api.BacktestPreparation;
const status = {
    schema_version: 1,
    run_id: run,
    strategy_fingerprint: sha,
    state: "COMPLETED",
    revision: "2",
    accepted_at: "2026-11-02T00:00:00Z",
    report_status: { state: "VERIFIED", code: null },
    preparation_command_id: preparation
} satisfies api.BacktestRun;
const result = {
    schema_version: 1,
    run_id: run,
    strategy_fingerprint: sha,
    evidence_fingerprint: sha,
    result_fingerprint: sha,
    determinism_fingerprint: sha,
    state: "COMPLETED",
    sample: {
        instrument: "BTCUSDT",
        start_at: "2025-01-03T00:00:00Z",
        end_at: "2025-01-03T12:00:00Z",
        quantity: "0.01",
        rule_observed_at: "2026-11-02T00:00:00Z"
    },
    metrics: {
        initial_equity: "10000",
        final_equity: "9994.60119940",
        return_since_start: "-0.00053988",
        net_pnl: "-5.39880060",
        realized_pnl: "-3.3998",
        unrealized_pnl: "0",
        fees: "1.99900060",
        maximum_drawdown: "-0.00054000",
        fill_count: 2,
        roundtrip_count: 1
    },
    curve: [{ at_ns: "1735862460000000000", nav: "9998", drawdown: "-0.0002" }],
    baseline: {
        final_equity: "10001",
        net_pnl: "1",
        return_since_start: "0.0001"
    },
    trades: [
        {
            ordinal: 1,
            time_ns: "1735862460000000000",
            side: "BUY",
            quantity: "0.01",
            price: "100120.02",
            fee: "1.00120020",
            signal_time_ns: "1735862400000000000",
            signal: "动量达到开仓条件",
            order_id: "order-one",
            trade_id: "trade-one"
        }
    ],
    positions: [
        {
            instrument: "BTCUSDT.BINANCE",
            quantity: "0.01",
            average_price: "100120.02",
            state: "OPEN"
        }
    ],
    limitations: ["样本较短，仅作探索。"]
} satisfies api.BacktestResult;
function page(path = "/backtest") {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <BacktestPage />
        </MemoryRouter>
    );
}
beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.mocked(api.pendingPreparation).mockReturnValue(null);
    vi.mocked(api.loadRuns).mockResolvedValue({ schema_version: 1, items: [] });
    vi.mocked(api.loadModels).mockResolvedValue({
        items: [
            {
                id: "12345678-1234-4234-8234-123456789ab2",
                owner: "local-developer",
                base_url: "http://127.0.0.1:58080/v1",
                credential_generation: "12345678-1234-4234-8234-123456789ab3",
                parent: null,
                revision: sha,
                name: "聊天模型",
                model_id: "current-model",
                model_version: "v1"
            }
        ]
    });
    vi.mocked(api.loadPreparation).mockResolvedValue(ready);
    vi.mocked(api.loadRun).mockResolvedValue(status);
    vi.mocked(api.loadResult).mockResolvedValue(result);
    vi.mocked(api.loadInterpretation).mockResolvedValue(null);
});

describe("Shipping backtest workflow", () => {
    it("shows ordinary history without starting a new qualification or backtest", async () => {
        page();
        expect(await screen.findByText("尚无回测记录")).toBeVisible();
        expect(api.prepareBacktest).not.toHaveBeenCalled();
        expect(api.confirmBacktest).not.toHaveBeenCalled();
    });
    it.each(["accepted", "refused", "original-accepted"])(
        "separates preparation from Start and reviews an explicitly refused invocation (%s)",
        async (mode) => {
            const refused = mode !== "accepted";
            const originalAccepted = mode === "original-accepted";
            const origin = {
                kind: "MANUAL_STRATEGY" as const,
                strategy_id: "private.strategy.btc_momentum",
                strategy_revision_fingerprint: sha
            };
            const context = {
                schema_version: 2 as const,
                strategy_name: "BTC 价量动量",
                input_defaults: {
                    schema_version: 2 as const,
                    profile: "BTC_SPOT_NEXT_OPEN_BACKTEST_V1" as const,
                    origin,
                    release_manifest_fingerprint: sha,
                    expected_active_generation: sha,
                    initialize_fresh_runtime: false as const
                },
                sample_start_at: "2025-01-03T00:00:00Z" as const,
                sample_end_at: "2025-01-03T12:00:00Z" as const,
                initial_cash: "10000" as const,
                quantity: "0.01" as const,
                fee_bps: 10 as const,
                slippage_bps: 2 as const,
                limitations: [],
                existing_preparations: []
            };
            const source = {
                is_current_revision: true,
                integration_id: ready.source.integration_id,
                integration_revision_fingerprint: sha,
                type_id: "binance.spot.market_data",
                source_id: ready.source.source_id,
                environment: ready.source.environment,
                display_name: "Binance 现货",
                new_work_status: "AVAILABLE" as const,
                new_work_unavailable_code: null,
                history_read_policy: "EXACT_SEALED_PROOF" as const,
                time_bar_capability: {
                    provider_base_semantic: {
                        schema_version: 3 as const,
                        formation: {
                            schema_version: 1 as const,
                            kind: "FIXED_DURATION" as const,
                            window_minutes: 1,
                            stride_minutes: 1,
                            alignment: "UTC" as const
                        },
                        price_type: "LAST" as const,
                        adjustment_policy: "RAW" as const
                    },
                    derived_algorithm: null,
                    minimum_window_minutes: 1,
                    maximum_window_minutes: 1440
                }
            };
            vi.mocked(api.loadCreationContext).mockResolvedValue(context);
            vi.mocked(api.loadSources).mockResolvedValue([source]);
            vi.mocked(api.prepareBacktest).mockResolvedValue(ready);
            const reviewConditions = vi.fn().mockResolvedValue(originalAccepted ? ready : null);
            if (refused)
                vi.mocked(api.prepareBacktest).mockRejectedValueOnce(
                    new api.PreparationNotStarted(reviewConditions, "CONDITIONS_CHANGED")
                );
            page(
                `/backtest/new?strategy_id=${origin.strategy_id}&strategy_revision_fingerprint=${sha}`
            );
            expect(await screen.findByText(/每笔 0.01 BTC/)).toBeVisible();
            expect(screen.getByText(/手续费.*0.1%/)).toBeVisible();
            expect(screen.getByText(/滑点.*0.02%/)).toBeVisible();
            expect(screen.queryByRole("button", { name: "开始回测" })).not.toBeInTheDocument();
            fireEvent.mouseDown(await screen.findByRole("combobox", { name: "回测行情数据源" }));
            fireEvent.click(await screen.findByText("Binance 现货"));
            fireEvent.click(screen.getByRole("button", { name: "确认策略并准备回测" }));
            if (refused) {
                expect(
                    await screen.findByText("应用已更新，这次准备尚未开始。请返回条件重新确认。")
                ).toBeVisible();
                expect(reviewConditions).not.toHaveBeenCalled();
                expect(api.prepareBacktest).toHaveBeenCalledTimes(1);
                expect(screen.queryByRole("button", { name: "开始回测" })).not.toBeInTheDocument();
                fireEvent.click(screen.getByRole("button", { name: "返回条件重新确认" }));
                expect(reviewConditions).toHaveBeenCalledTimes(1);
                if (!originalAccepted) {
                    await waitFor(() => {
                        expect(api.loadCreationContext).toHaveBeenCalledTimes(2);
                    });
                    await waitFor(() => {
                        expect(
                            screen.getByRole("combobox", { name: "回测行情数据源" })
                        ).not.toBeDisabled();
                    });
                    fireEvent.mouseDown(
                        await screen.findByRole("combobox", {
                            name: "回测行情数据源"
                        })
                    );
                    fireEvent.click(await screen.findByText("Binance 现货"));
                    fireEvent.click(screen.getByRole("button", { name: "确认策略并准备回测" }));
                }
            }
            await waitFor(() => {
                expect(screen.getByRole("button", { name: "开始回测" })).toBeEnabled();
            });
            expect(api.prepareBacktest).toHaveBeenCalledTimes(refused && !originalAccepted ? 2 : 1);
            if (originalAccepted) expect(api.loadCreationContext).toHaveBeenCalledTimes(1);
            expect(api.prepareBacktest).toHaveBeenLastCalledWith(context, ready.source);
            expect(api.confirmBacktest).not.toHaveBeenCalled();
            expect(api.loadModels).not.toHaveBeenCalled();
        }
    );
    it("loads the original result after refresh and presents metrics and causal trades", async () => {
        page(`/backtest/runs/${run}`);
        expect(await screen.findByText("回测结果")).toBeVisible();
        expect(screen.getByText("9994.60119940")).toBeVisible();
        expect(screen.getByText("1.99900060")).toBeVisible();
        expect(screen.getByText("买入")).toBeVisible();
        expect(
            within(screen.getByRole("row", { name: /买入/ })).getByRole("cell", {
                name: "100120.02"
            })
        ).toBeVisible();
        expect(
            screen.queryByText(/Fingerprint|Reducer|DTO|Lease|Revision Hash/)
        ).not.toBeInTheDocument();
        expect(api.prepareBacktest).not.toHaveBeenCalled();
        expect(api.confirmBacktest).not.toHaveBeenCalled();
    });
    it("requests interpretation only after an explicit action and binds the current model and exact result", async () => {
        let finish!: (value: { message: string }) => void;
        vi.mocked(api.interpretResult).mockReturnValue(
            new Promise((resolve) => {
                finish = resolve;
            })
        );
        page(`/backtest/runs/${run}`);
        await screen.findByText("回测结果");
        expect(api.interpretResult).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: "解读本次结果" }));
        await waitFor(() => {
            expect(api.interpretResult).toHaveBeenCalledWith(result, sha);
        });
        expect(screen.getByRole("button", { name: "正在解读" })).toBeDisabled();
        await act(() =>
            Promise.resolve().then(() => {
                finish({ message: "这段样本出现亏损，不能据此判断长期表现。" });
            })
        );
        expect(await screen.findByText("这段样本出现亏损，不能据此判断长期表现。")).toBeVisible();
    });
});

it.each(["pending", "failed"] as const)(
    "does not reuse another result's model selection while current model metadata is %s",
    async (metadataState) => {
        const otherRun = "12345678-1234-4234-8234-123456789ab9";
        const originalModels = {
            items: [
                {
                    id: "12345678-1234-4234-8234-123456789ab2",
                    owner: "local-developer",
                    base_url: "http://127.0.0.1:58080/v1",
                    credential_generation: "12345678-1234-4234-8234-123456789ab3",
                    parent: null,
                    revision: sha,
                    name: "聊天模型",
                    model_id: "current-model",
                    model_version: "v1"
                }
            ]
        };
        let rejectModels!: (reason: Error) => void;
        const delayedModels = new Promise<Awaited<ReturnType<typeof api.loadModels>>>(
            (_, reject) => {
                rejectModels = reject;
            }
        );
        vi.mocked(api.loadModels)
            .mockResolvedValueOnce(originalModels)
            .mockReturnValueOnce(delayedModels);
        vi.mocked(api.loadRun).mockImplementation((runId) =>
            Promise.resolve({ ...status, run_id: runId })
        );
        vi.mocked(api.loadResult).mockImplementation((runId) =>
            Promise.resolve({
                ...result,
                run_id: runId,
                metrics: {
                    ...result.metrics,
                    final_equity: runId === otherRun ? "9988.00" : result.metrics.final_equity
                }
            })
        );
        render(
            <MemoryRouter initialEntries={[`/backtest/runs/${run}`]}>
                <Link to={`/backtest/runs/${otherRun}`}>查看另一回测</Link>
                <BacktestPage />
            </MemoryRouter>
        );
        await screen.findByText("回测结果");
        await waitFor(() => {
            expect(screen.getByRole("button", { name: "解读本次结果" })).toBeEnabled();
        });
        fireEvent.click(screen.getByRole("link", { name: "查看另一回测" }));
        await screen.findByText("9988.00");
        try {
            if (metadataState === "failed") {
                await act(() =>
                    Promise.resolve().then(() => {
                        rejectModels(new Error("controlled current model metadata unavailable"));
                    })
                );
                expect(
                    await screen.findByText("模型暂时无法加载，请在设置中查看模型配置。")
                ).toBeVisible();
            }
            expect(screen.getByRole("button", { name: "解读本次结果" })).toBeDisabled();
            expect(api.interpretResult).not.toHaveBeenCalled();
            expect(api.loadRun).toHaveBeenLastCalledWith(otherRun);
            expect(api.loadResult).toHaveBeenLastCalledWith(otherRun);
        } finally {
            if (metadataState === "pending")
                await act(() =>
                    Promise.resolve().then(() => {
                        rejectModels(new Error("controlled model request settled at test cleanup"));
                    })
                );
        }
    }
);

it("reloads an unknown original start as unconfirmed and only observes its accepted original Run", async () => {
    vi.mocked(api.loadPreparation).mockResolvedValue({
        ...ready,
        backtest_outcome: "OUTCOME_UNKNOWN"
    });
    page(`/backtest/preparations/${preparation}`);
    expect(await screen.findByText(/结果尚未确认/)).toBeVisible();
    expect(screen.queryByText("可以开始回测")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始回测" })).toBeDisabled();
    expect(api.confirmBacktest).not.toHaveBeenCalled();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
    vi.mocked(api.loadPreparation).mockResolvedValue({
        ...ready,
        backtest_outcome: "ACCEPTED",
        run_id: run
    });
    fireEvent.click(screen.getByRole("button", { name: "重新查看" }));
    expect(await screen.findByText("回测结果")).toBeVisible();
    expect(api.loadPreparation).toHaveBeenLastCalledWith(preparation);
    expect(api.loadRun).toHaveBeenLastCalledWith(run);
    expect(api.loadResult).toHaveBeenLastCalledWith(run);
    expect(api.confirmBacktest).not.toHaveBeenCalled();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
    expect(api.resumePreparation).not.toHaveBeenCalled();
});

it.each([
    ["UNKNOWN", "回测执行状态尚未确认"],
    ["UNAVAILABLE", "回测执行服务暂不可用"],
    ["STOPPED", "回测执行服务已停止"]
] as const)(
    "shows active worker %s separately and preserves cancellation of the same original Run",
    async (workerState, message) => {
        const active = {
            ...status,
            state: "RUNNING" as const,
            report_status: { state: "PENDING" as const, code: null },
            worker_observation: {
                state: workerState,
                code: "CONTROLLED_WORKER_DIAGNOSTIC",
                run_id: research
            }
        };
        vi.mocked(api.loadRun).mockResolvedValue(active);
        vi.mocked(api.cancelBacktest).mockResolvedValue({
            ...active,
            state: "CANCEL_REQUESTED"
        });
        page(`/backtest/runs/${run}`);
        expect(await screen.findByText(message)).toBeVisible();
        expect(screen.getByText("正在回测")).toBeVisible();
        expect(screen.queryByText("未完成")).not.toBeInTheDocument();
        expect(screen.queryByText("CONTROLLED_WORKER_DIAGNOSTIC")).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "取消回测" }));
        await waitFor(() => {
            expect(api.cancelBacktest).toHaveBeenCalledExactlyOnceWith(active);
        });
        expect(api.loadRun).toHaveBeenLastCalledWith(run);
        expect(api.loadResult).not.toHaveBeenCalled();
        expect(api.prepareBacktest).not.toHaveBeenCalled();
        expect(api.confirmBacktest).not.toHaveBeenCalled();
        expect(api.interpretResult).not.toHaveBeenCalled();
    }
);
it("displays the original verified historical result while its worker is stopped", async () => {
    const historical = {
        ...status,
        worker_observation: { state: "STOPPED" as const }
    };
    vi.mocked(api.loadRun).mockResolvedValue(historical);
    page(`/backtest/runs/${run}`);
    expect(await screen.findByText("回测结果")).toBeVisible();
    expect(screen.getByText("9994.60119940")).toBeVisible();
    expect(screen.queryByText("回测执行服务已停止")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "取消回测" })).not.toBeInTheDocument();
    expect(api.loadRun).toHaveBeenLastCalledWith(run);
    expect(api.loadResult).toHaveBeenLastCalledWith(run);
    expect(api.prepareBacktest).not.toHaveBeenCalled();
    expect(api.confirmBacktest).not.toHaveBeenCalled();
    expect(api.interpretResult).not.toHaveBeenCalled();
});

it("presents net profit and the original ending equity as distinct financial results", async () => {
    page(`/backtest/runs/${run}`);
    expect(await screen.findByText("回测结果")).toBeVisible();
    expect(screen.getByText("净收益（USDT）")).toBeVisible();
    expect(screen.getByText(result.metrics.net_pnl)).toBeVisible();
    expect(screen.getByText(result.metrics.final_equity)).toBeVisible();
    expect(api.loadResult).toHaveBeenCalledWith(run);
    expect(api.prepareBacktest).not.toHaveBeenCalled();
    expect(api.confirmBacktest).not.toHaveBeenCalled();
    expect(api.interpretResult).not.toHaveBeenCalled();
});

it("separately displays realized and remaining-position profit in USDT without adding headline metrics", async () => {
    const held = {
        ...result,
        metrics: {
            ...result.metrics,
            realized_pnl: "17.2500",
            unrealized_pnl: "-8.1250"
        }
    };
    vi.mocked(api.loadResult).mockResolvedValue(held);
    const { container } = page(`/backtest/runs/${run}`);
    expect(await screen.findByText("回测结果")).toBeVisible();
    expect(screen.getByText("已实现盈亏（USDT）")).toBeVisible();
    expect(screen.getByText("未实现盈亏（USDT）")).toBeVisible();
    expect(screen.getByText("17.2500")).toBeVisible();
    expect(screen.getByText("-8.1250")).toBeVisible();
    const headline = container.querySelector(".backtest-metrics");
    expect(headline).not.toHaveTextContent("已实现盈亏");
    expect(headline).not.toHaveTextContent("未实现盈亏");
    expect(api.confirmBacktest).not.toHaveBeenCalled();
});

it("does not display a result bound to another Strategy even when its Run ID is shaped correctly", async () => {
    vi.mocked(api.loadResult).mockResolvedValue({
        ...result,
        strategy_fingerprint: "b".repeat(64)
    });
    page(`/backtest/runs/${run}`);
    expect(
        await screen.findByText("暂时无法读取当前记录。已有策略与回测仍然保留，请重新查看。")
    ).toBeVisible();
    expect(screen.queryByText(result.metrics.final_equity)).not.toBeInTheDocument();
    expect(screen.queryByText("回测结果")).not.toBeInTheDocument();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
    expect(api.confirmBacktest).not.toHaveBeenCalled();
    expect(api.interpretResult).not.toHaveBeenCalled();
});

it.each([false, true])(
    "recovers the original pending preparation with unavailable conditions and navigates its original task (run=%s)",
    async (withRun) => {
        const original = {
            ...ready,
            run_id: withRun ? run : null,
            backtest_outcome: withRun ? ("ACCEPTED" as const) : ("NOT_SUBMITTED" as const)
        };
        const observe = vi.fn().mockResolvedValue(original);
        vi.mocked(api.pendingPreparation).mockReturnValue({ observe });
        vi.mocked(api.loadCreationContext).mockRejectedValue(
            new Error("controlled conditions unavailable")
        );
        vi.mocked(api.loadSources).mockResolvedValue([]);
        page(
            `/backtest/new?strategy_id=${ready.origin.strategy_id}&strategy_revision_fingerprint=${sha}`
        );
        fireEvent.click(await screen.findByRole("button", { name: "查看任务进度" }));
        if (withRun) {
            await screen.findByText("回测结果");
            expect(api.loadRun).toHaveBeenCalledWith(run);
        } else {
            expect(await screen.findByRole("button", { name: "开始回测" })).toBeEnabled();
            expect(api.loadPreparation).toHaveBeenCalledWith(preparation);
        }
        expect(observe).toHaveBeenCalledOnce();
        expect(api.prepareBacktest).not.toHaveBeenCalled();
        expect(api.confirmBacktest).not.toHaveBeenCalled();
        expect(api.interpretResult).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: "重新查看" }));
        if (withRun) await screen.findByText("回测结果");
        else await screen.findByRole("button", { name: "开始回测" });
        expect(observe).toHaveBeenCalledOnce();
        expect(api.prepareBacktest).not.toHaveBeenCalled();
        expect(api.confirmBacktest).not.toHaveBeenCalled();
    }
);
it("keeps one usable original progress action after recovery is still unknown and never starts a new preparation", async () => {
    let known = false;
    const observe = vi.fn<() => Promise<api.BacktestPreparation>>();
    observe.mockImplementation(() => {
        if (known) return Promise.resolve(ready);
        return Promise.reject(Object.assign(new Error("controlled unknown original"), { observe }));
    });
    vi.mocked(api.pendingPreparation).mockReturnValue({ observe });
    vi.mocked(api.loadCreationContext).mockRejectedValue(new Error("controlled context outage"));
    vi.mocked(api.loadSources).mockResolvedValue([]);
    page(
        `/backtest/new?strategy_id=${ready.origin.strategy_id}&strategy_revision_fingerprint=${sha}`
    );
    fireEvent.click(await screen.findByRole("button", { name: "查看任务进度" }));
    await screen.findByText("操作结果尚未确认，请查看原任务的进度。");
    expect(screen.getAllByRole("button", { name: "查看任务进度" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "查看任务进度" })).toBeEnabled();
    const prepare = screen.getByRole("button", { name: /确认策略并准备回测/ });
    expect(prepare).toBeDisabled();
    fireEvent.click(prepare);
    expect(observe).toHaveBeenCalledOnce();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
    expect(api.confirmBacktest).not.toHaveBeenCalled();
    known = true;
    fireEvent.click(screen.getByRole("button", { name: "查看任务进度" }));
    expect(await screen.findByRole("button", { name: "开始回测" })).toBeEnabled();
    expect(observe).toHaveBeenCalledTimes(2);
    expect(api.prepareBacktest).not.toHaveBeenCalled();
    expect(api.confirmBacktest).not.toHaveBeenCalled();
});
