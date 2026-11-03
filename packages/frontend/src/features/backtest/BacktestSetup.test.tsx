import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BacktestSetup } from "./BacktestSetup";
import * as api from "./api";
import { loadWorkflows } from "../strategies/api";
const client = vi.hoisted(() => ({
    loadCreationContext: vi.fn<typeof api.loadCreationContext>(),
    loadSources: vi.fn<typeof api.loadSources>(),
    prepareBacktest: vi.fn<typeof api.prepareBacktest>(),
    pendingPreparation: vi.fn<typeof api.pendingPreparation>()
}));
vi.mock("./api", async (original) => ({
    ...(await original<typeof api>()),
    get loadCreationContext() {
        return client.loadCreationContext;
    },
    get loadSources() {
        return client.loadSources;
    },
    get prepareBacktest() {
        return client.prepareBacktest;
    },
    get pendingPreparation() {
        return client.pendingPreparation;
    }
}));
vi.mock("../strategies/api", () => ({ loadWorkflows: vi.fn() }));
const sha = "a".repeat(64),
    rev = "b".repeat(64);
const origin = {
    kind: "MANUAL_STRATEGY" as const,
    strategy_id: "private.strategy.btc_momentum",
    strategy_revision_fingerprint: rev
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
    limitations: ["短样本仅供探索"],
    existing_preparations: []
} satisfies api.BacktestCreation;
const source = {
    is_current_revision: true,
    integration_id: "binance",
    integration_revision_fingerprint: sha,
    type_id: "binance.spot.market_data",
    source_id: "binance.spot",
    environment: "GLOBAL",
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
const selected = `/backtest/new?strategy_id=${origin.strategy_id}&strategy_revision_fingerprint=${rev}`;
beforeEach(() => {
    vi.mocked(api.pendingPreparation).mockReturnValue(null);
    vi.mocked(api.loadCreationContext).mockResolvedValue(context);
    vi.mocked(api.loadSources).mockResolvedValue([source]);
    vi.mocked(loadWorkflows).mockResolvedValue({ schema_version: 1, items: [] });
});
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
});
function Route({ prepare }: { prepare: (action: () => Promise<api.BacktestPreparation>) => void }) {
    const location = useLocation();
    return <BacktestSetup query={location.search} busy={false} onPrepare={prepare} />;
}
function page(path = selected) {
    const prepare = vi.fn();
    render(
        <StrictMode>
            <MemoryRouter initialEntries={[path]}>
                <Route prepare={prepare} />
            </MemoryRouter>
        </StrictMode>
    );
    return prepare;
}
async function selectSource() {
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "回测行情数据源" }));
    fireEvent.click(await screen.findByText(source.display_name));
}
it("StrictMode reads exact defaults and sources, requires explicit source selection, and never prepares automatically", async () => {
    const prepare = page();
    await waitFor(() => {
        expect(api.loadSources).toHaveBeenCalled();
    });
    expect(api.loadCreationContext).toHaveBeenCalledWith(origin);
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeDisabled();
    expect(prepare).not.toHaveBeenCalled();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
    expect(screen.getByText(/手续费每边 0.1%/)).toBeVisible();
    expect(screen.getByText(/每笔 0.01 BTC/)).toBeVisible();
    expect(screen.getByText(/2025-01-03/)).toBeVisible();
    await selectSource();
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "确认策略并准备回测" }));
    expect(prepare).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "开始回测" })).not.toBeInTheDocument();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
});
it("prepares the first manual backtest with an explicit empty predecessor and no fabricated generation", async () => {
    vi.mocked(api.loadCreationContext).mockResolvedValue({
        ...context,
        input_defaults: { ...context.input_defaults, expected_active_generation: null }
    });
    const prepare = page();
    await selectSource();
    expect(await screen.findByText("首次使用将准备计算环境。")).toBeVisible();
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeEnabled();
    expect(prepare).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认策略并准备回测" }));
    expect(prepare).toHaveBeenCalledOnce();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
});
it("a normal new-backtest entry discovers saved strategies without internal ID input or research prerequisites", async () => {
    page("/backtest/new");
    expect(await screen.findByRole("link", { name: "选择因子创建策略" })).toHaveAttribute(
        "href",
        "/strategies/new"
    );
    expect(loadWorkflows).toHaveBeenCalled();
    expect(api.loadCreationContext).not.toHaveBeenCalled();
    expect(api.loadSources).not.toHaveBeenCalled();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
});
it("does not display another strategy's late defaults after navigation", async () => {
    let finish!: (value: typeof context) => void;
    const other = { ...origin, strategy_id: "private.strategy.other" };
    vi.mocked(api.loadCreationContext).mockImplementation((value) =>
        value.kind === "MANUAL_STRATEGY" && value.strategy_id === origin.strategy_id
            ? new Promise((resolve) => {
                  finish = resolve;
              })
            : Promise.resolve({
                  ...context,
                  input_defaults: { ...context.input_defaults, origin: other },
                  limitations: ["第二份策略的范围"]
              })
    );
    render(
        <MemoryRouter initialEntries={[selected]}>
            <Link
                to={`/backtest/new?strategy_id=${other.strategy_id}&strategy_revision_fingerprint=${rev}`}
            >
                选择另一策略
            </Link>
            <Route prepare={vi.fn()} />
        </MemoryRouter>
    );
    await waitFor(() => {
        expect(api.loadCreationContext).toHaveBeenCalledWith(origin);
    });
    fireEvent.click(screen.getByRole("link", { name: "选择另一策略" }));
    await screen.findByText("第二份策略的范围");
    await act(() =>
        Promise.resolve().then(() => {
            finish(context);
        })
    );
    expect(screen.getByText("第二份策略的范围")).toBeVisible();
    expect(screen.queryByText("短样本仅供探索")).not.toBeInTheDocument();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
});

it.each(["loading", "context-unavailable", "no-sources"])(
    "discovers the original unknown preparation independently of %s and never requires another POST",
    async (mode) => {
        const observe = vi.fn<() => Promise<api.BacktestPreparation>>();
        vi.mocked(api.pendingPreparation).mockReturnValue({ observe });
        if (mode === "loading")
            vi.mocked(api.loadCreationContext).mockReturnValue(new Promise(() => undefined));
        if (mode === "context-unavailable")
            vi.mocked(api.loadCreationContext).mockRejectedValue(
                new Error("controlled context outage")
            );
        vi.mocked(api.loadSources).mockResolvedValue([]);
        const prepare = page();
        const button = await screen.findByRole("button", { name: "查看任务进度" });
        expect(button).toBeEnabled();
        expect(api.pendingPreparation).toHaveBeenCalledWith(origin);
        expect(observe).not.toHaveBeenCalled();
        expect(prepare).not.toHaveBeenCalled();
        expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeDisabled();
        fireEvent.click(button);
        expect(prepare).toHaveBeenCalledExactlyOnceWith(observe);
        expect(api.prepareBacktest).not.toHaveBeenCalled();
    }
);
it("does not retain a different strategy's pending recovery entry after navigation", async () => {
    const observe = vi.fn<() => Promise<api.BacktestPreparation>>();
    const other = { ...origin, strategy_id: "private.strategy.other" };
    vi.mocked(api.pendingPreparation).mockImplementation((selected) =>
        selected.kind === "MANUAL_STRATEGY" && selected.strategy_id === origin.strategy_id
            ? { observe }
            : null
    );
    vi.mocked(api.loadCreationContext).mockImplementation((selected) =>
        Promise.resolve({
            ...context,
            strategy_name:
                selected.kind === "MANUAL_STRATEGY" && selected.strategy_id === other.strategy_id
                    ? "另一份策略"
                    : context.strategy_name,
            input_defaults: { ...context.input_defaults, origin: selected }
        })
    );
    render(
        <MemoryRouter initialEntries={[selected]}>
            <Link
                to={`/backtest/new?strategy_id=${other.strategy_id}&strategy_revision_fingerprint=${rev}`}
            >
                选择另一策略
            </Link>
            <Route prepare={vi.fn()} />
        </MemoryRouter>
    );
    expect(await screen.findByRole("button", { name: "查看任务进度" })).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: "选择另一策略" }));
    await screen.findByText("另一份策略");
    expect(screen.queryByRole("button", { name: "查看任务进度" })).not.toBeInTheDocument();
    expect(observe).not.toHaveBeenCalled();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
});

it("immediately drops loaded conditions and the selected Source while another strategy is loading", async () => {
    const other = { ...origin, strategy_id: "private.strategy.next" };
    let finish!: (value: api.BacktestCreation) => void;
    vi.mocked(api.loadCreationContext).mockImplementation((requested) =>
        requested.kind === "MANUAL_STRATEGY" && requested.strategy_id === origin.strategy_id
            ? Promise.resolve(context)
            : new Promise((resolve) => {
                  finish = resolve;
              })
    );
    const prepare = vi.fn();
    render(
        <MemoryRouter initialEntries={[selected]}>
            <Link
                to={`/backtest/new?strategy_id=${other.strategy_id}&strategy_revision_fingerprint=${rev}`}
            >
                选择另一策略
            </Link>
            <Route prepare={prepare} />
        </MemoryRouter>
    );
    await selectSource();
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeEnabled();
    fireEvent.click(screen.getByRole("link", { name: "选择另一策略" }));
    expect(screen.queryByText(context.strategy_name)).not.toBeInTheDocument();
    expect(
        screen.getByRole("combobox", { name: "回测行情数据源" }).closest(".ant-select")
    ).toHaveTextContent(/^选择 Binance 现货行情$/);
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeDisabled();
    await act(() =>
        Promise.resolve().then(() => {
            finish({
                ...context,
                strategy_name: "下一策略",
                input_defaults: { ...context.input_defaults, origin: other }
            });
        })
    );
    await screen.findByText("下一策略");
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeDisabled();
    expect(prepare).not.toHaveBeenCalled();
    expect(api.prepareBacktest).not.toHaveBeenCalled();
});
it("masks old conditions and Source on a same-query API change and submits only the new API's loaded context", async () => {
    const prepare = vi.fn<(action: () => Promise<api.BacktestPreparation>) => void>();
    const search = new URL(selected, "http://localhost").search;
    const element = () => (
        <MemoryRouter>
            <BacktestSetup query={search} busy={false} onPrepare={prepare} />
        </MemoryRouter>
    );
    const page = render(element());
    await selectSource();
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeEnabled();
    let finish!: (value: api.BacktestCreation) => void;
    const nextContext = { ...context, strategy_name: "新连接的策略条件" };
    const nextSource = {
        ...source,
        display_name: "新连接行情",
        source_id: "binance.other",
        integration_revision_fingerprint: "c".repeat(64)
    };
    const originalPrepare = client.prepareBacktest;
    client.loadCreationContext = vi.fn<typeof api.loadCreationContext>(
        () =>
            new Promise<api.BacktestCreation>((resolve) => {
                finish = resolve;
            })
    );
    client.loadSources = vi.fn<typeof api.loadSources>().mockResolvedValue([nextSource]);
    client.prepareBacktest = vi
        .fn<typeof api.prepareBacktest>()
        .mockRejectedValue(new Error("controlled new API preparation"));
    page.rerender(element());
    expect(screen.queryByText(context.strategy_name)).not.toBeInTheDocument();
    expect(
        screen.getByRole("combobox", { name: "回测行情数据源" }).closest(".ant-select")
    ).toHaveTextContent(/^选择 Binance 现货行情$/);
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeDisabled();
    await act(() =>
        Promise.resolve().then(() => {
            finish(nextContext);
        })
    );
    await screen.findByText(nextContext.strategy_name);
    expect(screen.getByRole("button", { name: "确认策略并准备回测" })).toBeDisabled();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "回测行情数据源" }));
    fireEvent.click(await screen.findByText(nextSource.display_name));
    fireEvent.click(screen.getByRole("button", { name: "确认策略并准备回测" }));
    const action = prepare.mock.calls[0]?.[0];
    if (action === undefined) throw new Error("expected explicit preparation action");
    await expect(action()).rejects.toThrow("controlled new API preparation");
    expect(client.prepareBacktest).toHaveBeenCalledExactlyOnceWith(nextContext, {
        integration_id: nextSource.integration_id,
        integration_revision_fingerprint: nextSource.integration_revision_fingerprint,
        expected_type_id: "binance.spot.market_data",
        source_id: nextSource.source_id,
        environment: nextSource.environment,
        instrument_id: "BTCUSDT.BINANCE"
    });
    expect(originalPrepare).not.toHaveBeenCalled();
});
