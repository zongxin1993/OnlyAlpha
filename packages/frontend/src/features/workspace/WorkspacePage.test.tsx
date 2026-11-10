import { requiredValue } from "../../test/requiredValue";
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
import { MemoryRouter, createMemoryRouter, RouterProvider } from "react-router-dom";
import { WorkstationShell } from "../../app/shell/WorkstationShell";
import { WorkspacePage } from "./WorkspacePage";

vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: () => <div data-testid="price-chart">chart</div>
}));

beforeEach(() => {
    // jsdom 未实现原生 dialog 模态方法；目录 dialog 按打开态语义补齐。
    Object.defineProperties(HTMLDialogElement.prototype, {
        showModal: {
            configurable: true,
            writable: true,
            value: function showModal(this: HTMLDialogElement) {
                this.setAttribute("open", "");
            }
        },
        close: {
            configurable: true,
            writable: true,
            value: function close(this: HTMLDialogElement) {
                this.removeAttribute("open");
            }
        }
    });
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string) =>
            Promise.resolve(
                new Response(
                    JSON.stringify(
                        url === "/api/v2/workspace"
                            ? {
                                  schema_version: 3,
                                  version: 0,
                                  active_workspace_id: null,
                                  workspaces: []
                              }
                            : { schema_version: 2, version: 0, lists: [] }
                    )
                )
            )
        )
    );
});
afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});
function renderWorkspace(client: IntegrationApiClient = integrationClient()) {
    return render(
        <AppProviders
            integrationClient={client}
            marketDataClient={marketDataClient({ listSources: () => Promise.resolve([]) })}
        >
            <MemoryRouter>
                <WorkspacePage />
            </MemoryRouter>
        </AppProviders>
    );
}

it("lays the primary workspace out as rail, watch column, chart and bottom panel", async () => {
    const { container } = renderWorkspace();
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(
            "尚未配置可用的行情来源"
        );
    });
    expect(screen.getByRole("toolbar", { name: "图表工具" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "主图" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "自选" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开下方面板" })).toHaveAttribute(
        "aria-expanded",
        "false"
    );
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    expect(container.querySelector(".chart-workspace")).toHaveAttribute(
        "data-tools-collapsed",
        "true"
    );
    expect(container.querySelector(".chart-workspace")).toHaveAttribute(
        "data-bottom-collapsed",
        "true"
    );
});

it("keeps both rails compact without an expansion control and retains the bottom panel", async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();
    const workspace = container.querySelector(".chart-workspace");
    expect(workspace).toHaveAttribute("data-tools-collapsed", "true");
    expect(screen.queryByRole("button", { name: /展开工具条|收起工具条/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开下方面板" }));
    expect(workspace).toHaveAttribute("data-bottom-collapsed", "false");
    await user.click(screen.getByRole("button", { name: "收起下方面板" }));
    expect(workspace).toHaveAttribute("data-bottom-collapsed", "true");
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
});

it("orders the live chart controls beside the brand icon in the top workspace bar", async () => {
    const router = createMemoryRouter([
        { element: <WorkstationShell />, children: [{ path: "/", element: <WorkspacePage /> }] }
    ]);
    render(
        <AppProviders
            integrationClient={integrationClient()}
            marketDataClient={marketDataClient({ listSources: () => Promise.resolve([]) })}
        >
            <RouterProvider router={router} />
        </AppProviders>
    );
    const toolbar = await screen.findByRole("toolbar", { name: "图表工作条" });
    expect(toolbar.closest(".workspace-topbar")).not.toBeNull();
    const brand = screen.getByRole("link", { name: "OnlyAlpha 工作台" });
    expect(brand).toHaveTextContent("OA");
    expect(brand.closest(".side-rail")).not.toBeNull();
    expect(within(toolbar).getByRole("button", { name: "图表类型" })).toBeInTheDocument();
    expect(within(toolbar).getByRole("button", { name: /工作区/ })).toBeInTheDocument();
    expect(within(toolbar).queryByRole("button", { name: "设置" })).not.toBeInTheDocument();
    expect(within(toolbar).getByRole("option", { name: "1 分钟" })).toHaveValue("1");
    expect(within(toolbar).getByRole("option", { name: "1 小时" })).toHaveValue("60");
    await userEvent.click(within(toolbar).getByRole("button", { name: "图表类型" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "收盘线" }));
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    expect(within(toolbar).getByRole("button", { name: "图表类型" })).toBeInTheDocument();
});

it("exposes honest unconnected watchlist, inspector, runs, results and backtest views", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    const watchColumn = screen.getByRole("complementary", { name: "自选" });
    expect(within(watchColumn).getByRole("region", { name: "自选行情" })).toBeInTheDocument();
    const inspectorCard = within(watchColumn).getByRole("group", { name: "行情检查器" });
    expect(inspectorCard).not.toHaveAttribute("open");
    await user.click(within(inspectorCard).getByText("行情检查器"));
    expect(within(inspectorCard).getByText("尚未选择行情上下文")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开下方面板" }));
    const bottomPanel = screen.getByRole("region", { name: "研究面板" });
    await user.click(within(bottomPanel).getByRole("button", { name: "研究结果" }));
    expect(within(bottomPanel).getByText("研究结果尚未实现")).toBeInTheDocument();
    expect(within(bottomPanel).getByRole("link", { name: "回测" })).toHaveAttribute(
        "href",
        "/backtest"
    );
    expect(within(bottomPanel).queryByText("回测尚未实现")).not.toBeInTheDocument();
    expect(
        screen.queryByText(/600519|rev-2c7d18|snap-1f0a|res-4d81|bt-2f5e18|fill-88c1/)
    ).not.toBeInTheDocument();
});

it("never presents absent API proof as synthetic business facts or success", async () => {
    renderWorkspace();
    await waitFor(() => {
        expect(screen.getByTestId("market-data-status")).toHaveTextContent(
            "尚未配置可用的行情来源，请先添加行情来源。"
        );
    });
    expect(screen.queryByTestId("market-data-observation")).not.toBeInTheDocument();
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

it("hides the source badge and exposes market settings through the gear", async () => {
    renderWorkspace(configuredClient());
    expect(screen.queryByRole("button", { name: /^数据源/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("图表设置", { selector: "summary[aria-label=设置]" }));
    await userEvent.click(screen.getByText("行情设置"));
    expect(screen.getByRole("combobox", { name: "数据源" })).toBeInTheDocument();
});

it("opens the manager modal from settings and closes it with Escape", async () => {
    const user = userEvent.setup();
    renderWorkspace(configuredClient());
    await user.click(screen.getByText("图表设置", { selector: "summary[aria-label=设置]" }));
    await user.click(
        within(requiredValue(document.querySelector<HTMLElement>(".workspace-settings"))).getByRole(
            "button",
            {
                name: "管理数据源"
            }
        )
    );
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
        <AppProviders integrationClient={configuredClient()}>
            <MemoryRouter>
                <WorkspacePage />
            </MemoryRouter>
        </AppProviders>,
        { container }
    );
    await user.click(screen.getByText("图表设置", { selector: "summary[aria-label=设置]" }));
    const trigger = within(
        requiredValue(document.querySelector<HTMLElement>(".workspace-settings"))
    ).getByRole("button", { name: "管理数据源" });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "管理数据源" })).toHaveFocus();
    expect(document.getElementById("root")).toHaveAttribute("inert");
    await user.keyboard("{Escape}");
    await waitFor(() => {
        expect(document.getElementById("root")).not.toHaveAttribute("inert");
    });
    expect(trigger).toHaveFocus();
    container.remove();
});

it("图下出现指标因子卡：已挂列表、目录入口与诚实空态", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    const studiesCard = screen.getByRole("region", { name: "指标 / 因子" });
    expect(within(studiesCard).getByText("还没有挂指标或因子，从目录添加。")).toBeInTheDocument();
    await user.click(within(studiesCard).getByRole("button", { name: "目录" }));
    expect(await screen.findByRole("dialog", { name: "指标 / 因子目录" })).toBeInTheDocument();
});

it("图下工作区卡：诚实空态与保存副本入口接既有保存流程", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    const card = screen.getByRole("region", { name: "工作区" });
    expect(
        within(card).getByText("还没有保存的工作区，“保存副本”可保存当前布局与绘图。")
    ).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "保存副本" }));
    expect(await screen.findByRole("dialog", { name: "保存工作区" })).toBeInTheDocument();
});

it("自选竖列常开，托盘面板开关已撤除", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false }));
    try {
        renderWorkspace();
        const watchColumn = screen.getByRole("complementary", { name: "自选" });
        expect(within(watchColumn).getByRole("region", { name: "自选行情" })).toBeInTheDocument();
        expect(screen.queryByRole("toolbar", { name: "工作区面板" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "收起上下文面板" })).not.toBeInTheDocument();
        expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    } finally {
        vi.unstubAllGlobals();
    }
});
