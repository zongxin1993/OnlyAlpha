import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AppProviders } from "./providers";
import { router as shippingRouter } from "./router";

vi.mock("../features/workspace/WorkspacePage", () => ({
    WorkspacePage: () => <h1>工作台</h1>
}));

vi.mock("../features/strategies/StrategyWorkflow", () => ({
    StrategyWorkflow: () => <h1>策略验证</h1>
}));
vi.mock("../features/backtest/BacktestPage", () => ({ BacktestPage: () => <h1>策略回测</h1> }));

vi.mock("../features/data/sources/DataSourcesPage", () => ({
    DataSourcesPage: () => <h1>数据画面</h1>
}));
vi.mock("../features/data/sources/NewDataSourcePage", () => ({
    NewDataSourcePage: () => <h1>数据画面</h1>
}));
vi.mock("../features/data/sources/DataSourceDetailPage", () => ({
    DataSourceDetailPage: () => <h1>数据画面</h1>
}));

it.each([
    ["/strategies/private.strategy.btc_momentum", "策略验证"],
    ["/backtest", "策略回测"]
])("%s opens its Shipping workflow", (path, label) => {
    const router = createMemoryRouter(shippingRouter.routes, { initialEntries: [path] });
    render(
        <AppProviders>
            <RouterProvider router={router} />
        </AppProviders>
    );
    expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
    expect(screen.queryByText(/未实现/)).not.toBeInTheDocument();
});

it.each([
    ["/data", "数据画面"], // 裸 /data 重定向到导航锚 /data/inputs。
    ["/data/inputs", "数据画面"],
    ["/data/sources", "数据画面"],
    ["/data/sources/new", "数据画面"],
    ["/data/sources/existing-source", "数据画面"]
])("%s 打开数据画面而非 Deferred 占位", (path, label) => {
    const router = createMemoryRouter(shippingRouter.routes, { initialEntries: [path] });
    render(
        <AppProviders>
            <RouterProvider router={router} />
        </AppProviders>
    );
    expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
    expect(screen.queryByText(/未实现/)).not.toBeInTheDocument();
});

afterEach(() => {
    vi.unstubAllGlobals();
});

const deferredDestinations = [
    ["/research/new", "研究"],
    ["/research/results/exact-result/statistics/exact-statistics", "研究"],
    ["/system/health", "系统"]
] as const;

it.each(deferredDestinations)(
    "%s shows the deferred state without issuing business requests",
    async (path, label) => {
        const fetch = vi.fn();
        vi.stubGlobal("fetch", fetch);
        const router = createMemoryRouter(shippingRouter.routes, { initialEntries: [path] });
        const user = userEvent.setup();
        render(
            <AppProviders>
                <RouterProvider router={router} />
            </AppProviders>
        );
        expect(screen.getByRole("heading", { name: `${label} · 未实现` })).toBeInTheDocument();
        expect(screen.getByRole("status")).toHaveTextContent("当前版本先提供工作台");
        expect(fetch).not.toHaveBeenCalled();
        await user.click(screen.getByRole("link", { name: "返回工作台" }));
        expect(router.state.location.pathname).toBe("/");
        expect(screen.getByRole("heading", { name: "工作台" })).toBeInTheDocument();
        expect(fetch).not.toHaveBeenCalled();
    }
);

it("keeps unknown paths distinct from deferred product pages", () => {
    const router = createMemoryRouter(shippingRouter.routes, {
        initialEntries: ["/unknown-product"]
    });
    render(<RouterProvider router={router} />);
    expect(screen.getByRole("heading", { name: "页面未找到" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回工作台" })).toHaveAttribute("href", "/");
});
