import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ManualStrategyWorkflow } from "./ManualStrategyWorkflow";
import * as api from "./manualApi";
vi.mock("./manualApi", () => ({
    loadFactors: vi.fn(),
    loadManualContext: vi.fn(),
    saveManualDefinition: vi.fn(),
    pendingManualDefinition: vi.fn(),
    loadWorkflow: vi.fn(),
    loadWorkflows: vi.fn()
}));
const sha = "a".repeat(64),
    rev = "b".repeat(64);
const first = {
    locator: {
        private_asset_kind: "FACTOR" as const,
        private_asset_id: "private.factor.momentum",
        revision_fingerprint: rev,
        content_fingerprint: sha
    },
    name: "价量动量",
    summary: "1 分钟价格与成交量",
    display_version: 1
};
const second = {
    ...first,
    locator: { ...first.locator, private_asset_id: "private.factor.other" },
    name: "第二个因子"
};
const draft = {
    schema_version: 1 as const,
    strategy_id: "private.strategy.btc_momentum",
    semantic_version: "1",
    base_revision_fingerprint: null,
    definition: {},
    description: "BTC 价量多头",
    tags: []
};
const context = {
    schema_version: 1 as const,
    factor_locator: first.locator,
    factor_name: first.name,
    formula: "close",
    draft,
    release_manifest_fingerprint: sha,
    expected_active_generation: sha,
    initialize_fresh_runtime: false as const,
    existing_preparations: []
};
const authoring = {
    schema_version: 1 as const,
    strategy_id: draft.strategy_id,
    draft,
    draft_fingerprint: sha,
    current_revision_fingerprint: rev,
    revisions: []
};
beforeEach(() => {
    vi.mocked(api.pendingManualDefinition).mockReturnValue(null);
    vi.mocked(api.loadFactors).mockResolvedValue([first, second]);
    vi.mocked(api.loadManualContext).mockResolvedValue(context);
    vi.mocked(api.loadWorkflow).mockResolvedValue({
        schema_version: 1,
        strategy_id: draft.strategy_id,
        authoring,
        preparations: [],
        backtest_preparations: []
    });
});
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
    sessionStorage.clear();
});
function LocationStamp() {
    const location = useLocation();
    return <output aria-label="当前页面">{location.pathname + location.search}</output>;
}
function page(path = "/strategies/new") {
    return render(
        <StrictMode>
            <MemoryRouter initialEntries={[path]}>
                <LocationStamp />
                <ManualStrategyWorkflow />
            </MemoryRouter>
        </StrictMode>
    );
}
async function select(name: string) {
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "已保存因子" }));
    fireEvent.click(await screen.findByText(name));
}
it("StrictMode reads inventory without creating a strategy, invoking a model or starting work", async () => {
    page();
    await screen.findByRole("combobox", { name: "已保存因子" });
    expect(api.loadManualContext).not.toHaveBeenCalled();
    expect(api.saveManualDefinition).not.toHaveBeenCalled();
    expect(
        screen.queryByText(/Fingerprint|Reducer|DTO|Lease|Revision Hash/)
    ).not.toBeInTheDocument();
});
it("selects a published factor and saves the definition only on an explicit Human action", async () => {
    vi.mocked(api.saveManualDefinition).mockResolvedValue(authoring);
    page();
    await select(first.name);
    expect(await screen.findByText("空仓且因子值 ≥ 0.001 时入场")).toBeVisible();
    expect(screen.getByText(/20 分钟前收盘价.*最近 20 分钟平均成交量/)).toBeVisible();
    expect(api.loadManualContext).toHaveBeenCalledExactlyOnceWith(first.locator, undefined);
    expect(api.saveManualDefinition).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存策略定义" }));
    await waitFor(() => {
        expect(api.saveManualDefinition).toHaveBeenCalledExactlyOnceWith(
            context,
            draft.description
        );
    });
    expect(await screen.findByRole("link", { name: "配置回测" })).toHaveAttribute(
        "href",
        `/backtest/new?strategy_id=${draft.strategy_id}&strategy_revision_fingerprint=${rev}`
    );
});
it("does not let a late first Factor context overwrite the currently selected Factor", async () => {
    let resolveFirst!: (value: typeof context) => void;
    vi.mocked(api.loadManualContext).mockImplementation((locator) =>
        locator.private_asset_id === first.locator.private_asset_id
            ? new Promise((resolve) => {
                  resolveFirst = resolve;
              })
            : Promise.resolve({
                  ...context,
                  factor_locator: second.locator,
                  factor_name: second.name,
                  draft: { ...draft, description: "第二份策略" }
              })
    );
    page();
    await select(first.name);
    await select(second.name);
    await screen.findByDisplayValue("第二份策略");
    await act(() =>
        Promise.resolve().then(() => {
            resolveFirst(context);
        })
    );
    expect(screen.getByDisplayValue("第二份策略")).toBeVisible();
    expect(screen.queryByDisplayValue(draft.description)).not.toBeInTheDocument();
});
it("UNKNOWN save observes its original operation without a second Save", async () => {
    const observe = vi.fn().mockResolvedValue(authoring);
    const pending = Object.assign(new Error("controlled ambiguous save"), { observe });
    vi.mocked(api.saveManualDefinition).mockRejectedValue(pending);
    page();
    await select(first.name);
    await screen.findByDisplayValue(draft.description);
    fireEvent.click(screen.getByRole("button", { name: "保存策略定义" }));
    await screen.findByRole("button", { name: "查看保存进度" });
    expect(screen.getByRole("combobox", { name: "已保存因子" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "策略名称" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新查看" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "我的策略" })).toHaveAttribute("href", "/strategies");
    fireEvent.click(screen.getByRole("button", { name: "查看保存进度" }));
    await screen.findByRole("link", { name: "配置回测" });
    expect(observe).toHaveBeenCalledOnce();
    expect(api.saveManualDefinition).toHaveBeenCalledOnce();
});
it("history loads all durable preparation states without a model, Study or current source", async () => {
    const preparation = {
        schema_version: 2 as const,
        command_id: "00000000-0000-4000-8000-000000009405",
        profile: "BTC_SPOT_NEXT_OPEN_BACKTEST_V1" as const,
        origin: {
            kind: "MANUAL_STRATEGY" as const,
            strategy_id: draft.strategy_id,
            strategy_revision_fingerprint: rev
        },
        strategy_fingerprint: null,
        validation_fingerprint: null,
        freeze_relation_fingerprint: null,
        qualification_decision_fingerprint: null,
        promotion_fingerprint: null,
        source: {
            integration_id: "binance",
            integration_revision_fingerprint: sha,
            expected_type_id: "binance.spot.market_data" as const,
            source_id: "spot",
            environment: "GLOBAL",
            instrument_id: "BTCUSDT.BINANCE" as const
        },
        revision: "9007199254740993",
        state: "BLOCKED" as const,
        phase: "VALIDATION",
        backtest_command_id: "00000000-0000-4000-8000-000000009403",
        reserved_run_id: "00000000-0000-4000-8000-000000009402",
        preparation_fingerprint: null,
        detail: null,
        backtest_outcome: "NOT_SUBMITTED" as const,
        readiness: { state: "NOT_APPLICABLE" as const, code: null },
        run_id: null,
        accepted_at: "2026-11-02T00:00:40Z"
    };
    vi.mocked(api.loadWorkflow).mockResolvedValue({
        schema_version: 1,
        strategy_id: draft.strategy_id,
        authoring,
        preparations: [],
        backtest_preparations: [preparation]
    });
    page(`/strategies/${draft.strategy_id}`);
    expect(await screen.findByRole("link", { name: "查看准备" })).toHaveAttribute(
        "href",
        `/backtest/preparations/${preparation.command_id}`
    );
    expect(screen.getByText("准备暂时受阻")).toBeVisible();
    expect(api.loadFactors).not.toHaveBeenCalled();
    expect(api.loadManualContext).not.toHaveBeenCalled();
    expect(api.saveManualDefinition).not.toHaveBeenCalled();
});
it("discards a late save response after navigation instead of reopening the old strategy", async () => {
    let finish!: (value: typeof authoring) => void;
    vi.mocked(api.saveManualDefinition).mockReturnValue(
        new Promise((resolve) => {
            finish = resolve;
        })
    );
    vi.mocked(api.loadWorkflows).mockResolvedValue({ schema_version: 1, items: [] });
    render(
        <MemoryRouter initialEntries={["/strategies/new"]}>
            <Link to="/strategies">离开创建</Link>
            <ManualStrategyWorkflow />
        </MemoryRouter>
    );
    await select(first.name);
    await screen.findByDisplayValue(draft.description);
    fireEvent.click(screen.getByRole("button", { name: "保存策略定义" }));
    fireEvent.click(screen.getByRole("link", { name: "离开创建" }));
    await screen.findByText("还没有保存的策略");
    await act(() =>
        Promise.resolve().then(() => {
            finish(authoring);
        })
    );
    expect(screen.getByText("我的策略", { selector: "h2" })).toBeVisible();
    expect(api.loadWorkflow).not.toHaveBeenCalled();
});

it("fixes the generated strategy identity in the ordinary URL before the first Save", async () => {
    page();
    await select(first.name);
    await screen.findByDisplayValue(draft.description);
    expect(screen.getByRole("status", { name: "当前页面" })).toHaveTextContent(
        `/strategies/new?strategy_id=${draft.strategy_id}`
    );
    expect(api.saveManualDefinition).not.toHaveBeenCalled();
    expect(api.loadManualContext).toHaveBeenCalledOnce();
});
it("restores an unknown original Save after a full component reload without inventing another strategy", async () => {
    const observe = vi.fn().mockResolvedValue(authoring);
    const pending = Object.assign(new Error("controlled original Save unknown"), { observe });
    let retained = false;
    vi.mocked(api.pendingManualDefinition).mockImplementation((id) =>
        retained && id === draft.strategy_id ? { name: draft.description, observe } : null
    );
    vi.mocked(api.saveManualDefinition).mockImplementation(() => {
        retained = true;
        return Promise.reject(pending);
    });
    const original = page();
    await select(first.name);
    await screen.findByDisplayValue(draft.description);
    fireEvent.click(screen.getByRole("button", { name: "保存策略定义" }));
    await screen.findByRole("button", { name: "查看保存进度" });
    original.unmount();
    vi.mocked(api.loadFactors).mockClear();
    page(`/strategies/new?strategy_id=${draft.strategy_id}`);
    const progress = await screen.findByRole("button", { name: "查看保存进度" });
    expect(screen.getByText(draft.description)).toBeVisible();
    expect(screen.queryByRole("combobox", { name: "已保存因子" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存策略定义" })).not.toBeInTheDocument();
    expect(api.loadFactors).not.toHaveBeenCalled();
    expect(api.loadManualContext).toHaveBeenCalledOnce();
    expect(api.loadWorkflow).not.toHaveBeenCalled();
    fireEvent.click(progress);
    await screen.findByRole("link", { name: "配置回测" });
    expect(observe).toHaveBeenCalledOnce();
    expect(api.saveManualDefinition).toHaveBeenCalledOnce();
});
it("keeps the original restored Save observe-only while its outcome is still unknown", async () => {
    const observe = vi.fn();
    const pending = Object.assign(new Error("controlled receipt not yet available"), { observe });
    observe.mockRejectedValueOnce(pending).mockResolvedValueOnce(authoring);
    vi.mocked(api.pendingManualDefinition).mockReturnValue({ name: draft.description, observe });
    page(`/strategies/new?strategy_id=${draft.strategy_id}`);
    fireEvent.click(await screen.findByRole("button", { name: "查看保存进度" }));
    await waitFor(() => {
        expect(observe).toHaveBeenCalledOnce();
    });
    expect(screen.queryByRole("button", { name: "保存策略定义" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "查看保存进度" }));
    await screen.findByRole("link", { name: "配置回测" });
    expect(observe).toHaveBeenCalledTimes(2);
    expect(api.saveManualDefinition).not.toHaveBeenCalled();
    expect(api.loadManualContext).not.toHaveBeenCalled();
});
it("ignores a late restored Save observation after leaving its ordinary page", async () => {
    let finish!: (value: typeof authoring) => void;
    const observe = vi.fn(
        () =>
            new Promise<typeof authoring>((resolve) => {
                finish = resolve;
            })
    );
    vi.mocked(api.pendingManualDefinition).mockReturnValue({ name: draft.description, observe });
    vi.mocked(api.loadWorkflows).mockResolvedValue({ schema_version: 1, items: [] });
    render(
        <MemoryRouter initialEntries={[`/strategies/new?strategy_id=${draft.strategy_id}`]}>
            <ManualStrategyWorkflow />
        </MemoryRouter>
    );
    fireEvent.click(await screen.findByRole("button", { name: "查看保存进度" }));
    fireEvent.click(screen.getByRole("link", { name: "我的策略" }));
    await screen.findByText("还没有保存的策略");
    await act(() =>
        Promise.resolve().then(() => {
            finish(authoring);
        })
    );
    expect(screen.getByText("我的策略", { selector: "h2" })).toBeVisible();
    expect(api.loadWorkflow).not.toHaveBeenCalled();
});
