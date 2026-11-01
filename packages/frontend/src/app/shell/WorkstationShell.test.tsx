import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { WorkstationShell } from "./WorkstationShell";

const destinations = [
    { path: "/", label: "工作台" },
    { path: "/research/new", label: "研究 · 未实现" },
    { path: "/data/inputs", label: "数据 · 未实现" },
    { path: "/strategies", label: "策略 · 未实现" },
    { path: "/backtest/runs", label: "回测 · 未实现" },
    { path: "/system/health", label: "系统 · 未实现" }
] as const;

function renderShell(entry = "/") {
    const router = createMemoryRouter(
        [
            {
                element: <WorkstationShell />,
                children: destinations.map((destination) => ({
                    path: destination.path,
                    element: (
                        <main>
                            <h1>{destination.label} 页面</h1>
                        </main>
                    )
                }))
            }
        ],
        { initialEntries: [entry] }
    );
    render(<RouterProvider router={router} />);
    return router;
}

it("keeps one persistent workspace shell around every product destination", async () => {
    const router = renderShell();
    const user = userEvent.setup();
    const navigation = screen.getByRole("navigation", { name: "产品导航" });
    for (const destination of destinations) {
        if (destination.path === "/") {
            await user.click(within(navigation).getByRole("link", { name: destination.label }));
        } else {
            await user.click(within(navigation).getByRole("button", { name: "更多功能" }));
            await user.click(await screen.findByRole("menuitem", { name: destination.label }));
        }
        expect(router.state.location.pathname).toBe(destination.path);
        expect(
            screen.getByRole("heading", { name: `${destination.label} 页面` })
        ).toBeInTheDocument();
    }
});

it("shows product language in the footer and reaches the workspace by keyboard", () => {
    renderShell();
    expect(screen.getByText("OnlyAlpha · 个人量化工作台")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).not.toHaveTextContent("Authority");
    expect(screen.getByRole("link", { name: "跳到工作区" })).toHaveAttribute(
        "href",
        "#workspace-content"
    );
    expect(document.getElementById("workspace-content")).toHaveAttribute("tabindex", "-1");
});

it("does not advertise a deferred research command as available", () => {
    renderShell();
    expect(screen.queryByRole("link", { name: "新建研究" })).not.toBeInTheDocument();
    expect(screen.queryByText("Control + Presentation")).not.toBeInTheDocument();
    expect(
        screen.getByRole("navigation", { name: "产品导航" }).closest(".global-workspace-rail")
    ).not.toBeNull();
});

it("keeps one settings entry with an SVG icon and separates persistent navigation from panels", () => {
    renderShell();
    const settings = screen.getByRole("button", { name: "全局设置" });
    expect(settings.querySelector("svg")).not.toBeNull();
    expect(settings.closest(".workspace-settings-anchor")).not.toBeNull();
    expect(screen.getAllByRole("button", { name: "全局设置" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "因子研究" })).toHaveAttribute(
        "href",
        "/factor-research"
    );
    expect(screen.queryByRole("link", { name: "回测 · 未实现" })).not.toBeInTheDocument();
});
