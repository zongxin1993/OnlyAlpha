import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { WorkstationShell } from "./WorkstationShell";

const destinations = [
    { path: "/", label: "工作台" },
    { path: "/research/new", label: "研究" },
    { path: "/data/inputs", label: "数据" },
    { path: "/strategies", label: "策略" },
    { path: "/backtest/runs", label: "回测" },
    { path: "/system/health", label: "系统" }
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
        const link = within(navigation).getByRole("link", { name: destination.label });
        expect(link).toHaveAttribute("href", destination.path);
        await user.click(link);
        expect(router.state.location.pathname).toBe(destination.path);
        expect(
            screen.getByRole("heading", { name: `${destination.label} 页面` })
        ).toBeInTheDocument();
        expect(link).toHaveAttribute("aria-current", "page");
    }
});

it("states the browser authority boundary and reaches the workspace by keyboard", () => {
    renderShell();
    expect(screen.getByText("OnlyAlpha · 浏览器只做控制与呈现")).toBeInTheDocument();
    expect(screen.getByText("服务端 Authority 必需")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "跳到工作区" })).toHaveAttribute(
        "href",
        "#workspace-content"
    );
    expect(document.getElementById("workspace-content")).toHaveAttribute("tabindex", "-1");
});

it("offers the formal research destination from the persistent toolbar", () => {
    renderShell();
    expect(screen.getByRole("link", { name: "新建研究" })).toHaveAttribute("href", "/research/new");
    expect(screen.getByText("Control + Presentation")).toBeInTheDocument();
});
