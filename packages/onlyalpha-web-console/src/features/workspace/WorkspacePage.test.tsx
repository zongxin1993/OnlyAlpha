import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { IntegrationApiClient } from "../../api/integrations/client";
import { AppProviders } from "../../app/providers";
import {
    dataSourceSummary,
    dataSourceType,
    integrationClient,
    operationalStatus
} from "../../test/integrationClient";
import { marketDataClient } from "../../test/marketDataClient";
import { researchClient } from "../../test/researchClient";
import { WorkspacePage } from "./WorkspacePage";

vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: () => <div data-testid="price-chart">chart</div>
}));

function renderWorkspace(client: IntegrationApiClient = integrationClient()) {
    return render(
        <AppProviders
            client={researchClient()}
            integrationClient={client}
            marketDataClient={marketDataClient({ listSources: () => Promise.resolve([]) })}
        >
            <WorkspacePage />
        </AppProviders>
    );
}

it("lays the primary workspace out as rail, chart, context panel and bottom panel", () => {
    const { container } = renderWorkspace();
    expect(screen.getByRole("toolbar", { name: "图表工具" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "主图" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "上下文面板" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "研究面板" })).toBeInTheDocument();
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    expect(container.querySelector(".chart-workspace")).toHaveAttribute(
        "data-tools-collapsed",
        "false"
    );
});

it("collapses the tool rail and the bottom panel without losing the chart", async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();
    const workspace = container.querySelector(".chart-workspace");
    await user.click(screen.getByRole("button", { name: "收起工具条" }));
    expect(workspace).toHaveAttribute("data-tools-collapsed", "true");
    expect(screen.getByRole("button", { name: "展开工具条" })).toHaveAttribute(
        "aria-expanded",
        "false"
    );
    await user.click(screen.getByRole("button", { name: "收起下方面板" }));
    expect(workspace).toHaveAttribute("data-bottom-collapsed", "true");
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
});

it("exposes honest unconnected watchlist, inspector, runs, results and backtest views", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    const contextPanel = screen.getByRole("complementary", { name: "上下文面板" });
    expect(within(contextPanel).getByText("选择真实标的后显示当前行情")).toBeInTheDocument();
    await user.click(within(contextPanel).getByRole("button", { name: "检查器" }));
    expect(within(contextPanel).getByText("尚未选择行情上下文")).toBeInTheDocument();
    const bottomPanel = screen.getByRole("region", { name: "研究面板" });
    await user.click(within(bottomPanel).getByRole("button", { name: "研究结果" }));
    expect(within(bottomPanel).getByText("研究结果尚未接入工作区")).toBeInTheDocument();
    await user.click(within(bottomPanel).getByRole("button", { name: "回测" }));
    expect(within(bottomPanel).getByText("回测尚未接入工作区")).toBeInTheDocument();
    expect(
        screen.queryByText(/600519|rev-2c7d18|snap-1f0a|res-4d81|bt-2f5e18|fill-88c1/)
    ).not.toBeInTheDocument();
});

it("never presents absent API proof as synthetic business facts or success", async () => {
    renderWorkspace();
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(
            "未配置可用的 Binance Spot 公共行情数据源（GLOBAL）"
        );
    });
    expect(screen.getByTestId("market-data-observation")).toHaveAttribute(
        "data-observation-mode",
        "unavailable"
    );
    expect(
        screen.queryByText(/synthetic|1486\.20|run-0f3a91|MA 20|20 日动量/)
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "指标" })).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.getByRole("button", { name: "因子" })).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.queryByTestId("calculation-handoff")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "时间周期" })).toHaveValue("15");
});

const configuredClient = () =>
    integrationClient({
        listTypes: () =>
            Promise.resolve([
                dataSourceType({ capabilities: ["HISTORICAL_BARS", "LIVE_TICKS", "INSTRUMENTS"] })
            ]),
        listDataSources: () => Promise.resolve([dataSourceSummary()]),
        getOperationalStatus: () => Promise.resolve(operationalStatus({ status: "UNKNOWN" }))
    });

it("shows the data source entry with an unverified count that is not an error", async () => {
    renderWorkspace(configuredClient());
    const trigger = await screen.findByRole("button", { name: /^数据源/ });
    expect(await within(trigger).findByText("1 未验证")).toBeInTheDocument();
    expect(trigger.querySelector(".state-mark--unverified")).not.toBeNull();
    expect(trigger.querySelector(".state-mark--degraded")).toBeNull();
    expect(trigger.querySelector(".state-mark--failed")).toBeNull();
});

it("opens a quick status Popover that never claims a workspace source", async () => {
    const user = userEvent.setup();
    renderWorkspace(configuredClient());
    await user.click(await screen.findByRole("button", { name: /^数据源/ }));
    const popover = screen.getByRole("dialog", { name: "数据源状态" });
    expect(within(popover).getByText("Fixture Source")).toBeInTheDocument();
    expect(within(popover).getByText("未验证")).toBeInTheDocument();
    expect(within(popover).getByText(/尚未有 canonical 来源绑定/)).toBeInTheDocument();
    expect(within(popover).queryByText(/历史：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/synthetic/)).not.toBeInTheDocument();
});

it("opens the manager modal from the Popover and closes it with Escape", async () => {
    const user = userEvent.setup();
    renderWorkspace(configuredClient());
    await user.click(await screen.findByRole("button", { name: /^数据源/ }));
    await user.click(screen.getByRole("button", { name: "管理数据源…" }));
    const modal = screen.getByRole("dialog", { name: "管理数据源" });
    expect(within(modal).getByRole("tab", { name: /已配置/ })).toHaveAttribute(
        "aria-selected",
        "true"
    );
    await user.click(within(modal).getByRole("tab", { name: /数据源绑定/ }));
    expect(within(modal).getByText(/此 Tab 目前没有 canonical 事实/)).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => {
        expect(screen.queryByRole("dialog", { name: "管理数据源" })).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
});

it("traps the manager dialog, marks the app inert and restores focus on close", async () => {
    const user = userEvent.setup();
    const container = document.createElement("div");
    container.id = "root";
    document.body.append(container);
    render(
        <AppProviders client={researchClient()} integrationClient={configuredClient()}>
            <WorkspacePage />
        </AppProviders>,
        { container }
    );
    const trigger = await screen.findByRole("button", { name: /^数据源/ });
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "管理数据源…" }));
    expect(screen.getByRole("dialog", { name: "管理数据源" })).toHaveFocus();
    expect(document.getElementById("root")).toHaveAttribute("inert");
    await user.keyboard("{Escape}");
    await waitFor(() => {
        expect(document.getElementById("root")).not.toHaveAttribute("inert");
    });
    expect(trigger).toHaveFocus();
    container.remove();
});
