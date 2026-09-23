import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { buildPlaceholderBars } from "../../charts/lightweight/placeholderBars";
import { WorkspacePage } from "./WorkspacePage";

vi.mock("../../charts/lightweight/PriceChart", () => ({
    PriceChart: () => <div data-testid="price-chart">chart</div>
}));

it("lays the primary workspace out as rail, chart, context panel and bottom panel", () => {
    const { container } = render(<WorkspacePage />);
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
    const { container } = render(<WorkspacePage />);
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

it("exposes watchlist, inspector, runs, results and backtest views", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />);
    const contextPanel = screen.getByRole("complementary", { name: "上下文面板" });
    expect(within(contextPanel).getByText("600519.SH")).toBeInTheDocument();
    await user.click(within(contextPanel).getByRole("button", { name: "检查器" }));
    expect(within(contextPanel).getByText("Strategy Revision")).toBeInTheDocument();
    const bottomPanel = screen.getByRole("region", { name: "研究面板" });
    await user.click(within(bottomPanel).getByRole("button", { name: "研究结果" }));
    expect(within(bottomPanel).getByText("res-4d81…a7c2")).toBeInTheDocument();
    await user.click(within(bottomPanel).getByRole("button", { name: "回测" }));
    expect(within(bottomPanel).getByText("bt-2f5e18")).toBeInTheDocument();
});

it("keeps UNKNOWN visible instead of dressing it as success", () => {
    render(<WorkspacePage />);
    expect(screen.getAllByText("UNKNOWN").length).toBeGreaterThan(0);
    expect(screen.getAllByText("未知").length).toBeGreaterThan(0);
    expect(screen.getAllByText("synthetic").length).toBeGreaterThanOrEqual(2);
});

it("builds the same placeholder series for the same timeframe", () => {
    const daily = buildPlaceholderBars("1D");
    expect(daily).toEqual(buildPlaceholderBars("1D"));
    const second = daily[1];
    expect(second).toBeDefined();
    expect(second?.time ?? 0).toBeGreaterThan(daily[0]?.time ?? 0);
    expect(buildPlaceholderBars("1W").length).toBe(daily.length);
});
