import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { WorkstationShell } from "./WorkstationShell";

function renderShell(entry = "/") {
    const router = createMemoryRouter(
        [
            {
                element: <WorkstationShell />,
                children: [
                    {
                        path: "*",
                        element: (
                            <main>
                                <h1>页面</h1>
                            </main>
                        )
                    }
                ]
            }
        ],
        { initialEntries: [entry] }
    );
    render(<RouterProvider router={router} />);
    return router;
}

beforeEach(() => {
    document.body.classList.remove("rail-open", "quiet", "no-ctx");
});

it("点开启导航钮打开抽屉并同步 aria-expanded", async () => {
    renderShell("/");
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "开启导航" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(document.body.classList.contains("rail-open")).toBe(true);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
});

it("点遮罩关闭抽屉", async () => {
    renderShell("/");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "开启导航" }));
    const mask = document.getElementById("rail-mask");
    expect(mask).not.toBeNull();
    if (mask === null) {
        throw new Error("rail-mask 缺失");
    }
    await user.click(mask);
    expect(document.body.classList.contains("rail-open")).toBe(false);
});

it("Esc 关闭抽屉", async () => {
    renderShell("/");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "开启导航" }));
    expect(document.body.classList.contains("rail-open")).toBe(true);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.body.classList.contains("rail-open")).toBe(false);
});

it("点击导航项后抽屉关闭并进入目标画面", async () => {
    const router = renderShell("/");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "开启导航" }));
    const rail = document.querySelector<HTMLElement>(".side-rail");
    if (rail === null) {
        throw new Error("side-rail 缺失");
    }
    await user.click(within(rail).getByRole("link", { name: "数据" }));
    expect(router.state.location.pathname).toBe("/data/inputs");
    expect(document.body.classList.contains("rail-open")).toBe(false);
});

it("抽屉关闭后再次打开不残留 aria-expanded", async () => {
    renderShell("/");
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "开启导航" });
    await user.click(toggle);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(document.body.classList.contains("rail-open")).toBe(true);
});
