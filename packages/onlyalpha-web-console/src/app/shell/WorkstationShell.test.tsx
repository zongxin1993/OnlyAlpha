import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { WorkstationShell } from "./WorkstationShell";

const destinations = [
    { path: "/research/new", label: "New Research" },
    { path: "/research/runs", label: "Runs" },
    { path: "/research/results", label: "Results" },
    { path: "/research/analysis", label: "AI Analysis" },
    { path: "/research/library", label: "Research Library" },
    { path: "/research/factors", label: "Factor Explorer" },
    { path: "/data/inputs", label: "Research Inputs" },
    { path: "/strategies", label: "Strategies" },
    { path: "/backtest/runs", label: "Backtests" },
    { path: "/system/health", label: "System Health" }
] as const;

function renderShell(entry = "/research/new") {
    const router = createMemoryRouter(
        [
            {
                element: <WorkstationShell />,
                children: destinations.map((destination) => ({
                    path: destination.path,
                    element: (
                        <main>
                            <h1>{destination.label} workspace</h1>
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

it("preserves OnlyAlpha branding, primary Research workflow and subordinate analysis/library tools", () => {
    renderShell();
    expect(screen.getByRole("link", { name: "OnlyAlpha Research" })).toHaveAttribute(
        "href",
        "/research/new"
    );
    const navigation = screen.getByRole("navigation", { name: "Workspace" });
    for (const label of ["New Research", "Runs", "Results"]) {
        expect(within(navigation).getByRole("link", { name: label })).not.toHaveClass(
            "research-nav-secondary"
        );
    }
    for (const label of ["AI Analysis", "Research Library"]) {
        expect(within(navigation).getByRole("link", { name: label })).toHaveClass(
            "research-nav-secondary"
        );
    }
    expect(screen.getByText("Server authority required")).toBeInTheDocument();
    expect(
        screen.getByText("OnlyAlpha · Browser is control and presentation only")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip to workspace" })).toHaveAttribute(
        "href",
        "#workspace-content"
    );
    expect(document.getElementById("workspace-content")).toHaveAttribute("tabindex", "-1");
});

it("navigates every existing Research destination and both additional read-only pages", async () => {
    const router = renderShell();
    const user = userEvent.setup();
    const navigation = screen.getByRole("navigation", { name: "Workspace" });
    for (const destination of destinations) {
        const link = within(navigation).getByRole("link", { name: destination.label });
        expect(link).toHaveAttribute("href", destination.path);
        await user.click(link);
        expect(router.state.location.pathname).toBe(destination.path);
        expect(
            screen.getByRole("heading", { name: `${destination.label} workspace` })
        ).toBeInTheDocument();
        expect(link).toHaveAttribute("aria-current", "page");
    }
});

it("opens the compact menu and closes it when a destination is chosen", async () => {
    const router = renderShell();
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    const aside = screen.getByRole("complementary", { name: "Workspace navigation" });
    expect(toggle).toHaveAttribute("aria-controls", "workstation-navigation");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(aside).toHaveClass("navigation-open");
    await user.click(within(aside).getByRole("link", { name: "AI Analysis" }));
    expect(router.state.location.pathname).toBe("/research/analysis");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(aside).not.toHaveClass("navigation-open");
});

it("closes the compact navigation with Escape from a focused menu link", async () => {
    renderShell("/data/inputs");
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    const aside = screen.getByRole("complementary", { name: "Workspace navigation" });
    await user.click(toggle);
    within(aside).getByRole("link", { name: "Research Inputs" }).focus();
    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(aside).not.toHaveClass("navigation-open");
    expect(screen.getByRole("heading", { name: "Research Inputs workspace" })).toBeInTheDocument();
});
