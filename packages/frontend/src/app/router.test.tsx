import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AppProviders } from "./providers";
import { router as shippingRouter } from "./router";

vi.mock("../features/workspace/WorkspacePage", () => ({
    WorkspacePage: () => <h1>工作台</h1>
}));

afterEach(() => {
    vi.unstubAllGlobals();
});

const deferredDestinations = [
    ["/research/new", "研究"],
    ["/research/results/exact-result/statistics/exact-statistics", "研究"],
    ["/data/inputs", "数据"],
    ["/data/sources/existing-source", "数据"],
    ["/strategies/exact-strategy", "策略"],
    ["/backtest/runs/existing-run", "回测"],
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
