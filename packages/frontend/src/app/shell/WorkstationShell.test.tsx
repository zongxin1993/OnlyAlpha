import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { WorkstationShell } from "./WorkstationShell";
import { setRail } from "./rail";

const destinations = [
    { path: "/overview", nav: "总览", label: "总览 · 未实现" },
    { path: "/", nav: "工作台", label: "工作台" },
    { path: "/research/new", nav: "研究", label: "研究 · 未实现" },
    { path: "/data/inputs", nav: "数据", label: "数据 · 未实现" },
    { path: "/strategies", nav: "策略", label: "策略" },
    { path: "/backtest", nav: "回测", label: "回测" },
    { path: "/system/health", nav: "系统", label: "系统 · 未实现" }
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

beforeEach(() => {
    document.body.classList.remove("rail-open", "no-ctx");
    setRail(false); // rail store 是模块单例：逐用例复位，避免开抽屉的用例串染。
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.body.classList.remove("quiet");
});

it("左侧栏展示分组标题与全部导航项文字", () => {
    renderShell();
    const navigation = screen.getByRole("navigation", { name: "产品导航" });
    expect(navigation.closest(".side-rail")).not.toBeNull();
    expect(within(navigation).getByText("投研")).toBeVisible();
    expect(within(navigation).getByText("基础设施")).toBeVisible();
    for (const label of ["总览", "工作台", "研究", "策略", "回测", "数据", "系统"]) {
        expect(within(navigation).getByRole("link", { name: label })).toBeVisible();
    }
});

it("当前路由项标记 aria-current", () => {
    renderShell("/strategies");
    const navigation = screen.getByRole("navigation", { name: "产品导航" });
    expect(within(navigation).getByRole("link", { name: "策略" })).toHaveAttribute(
        "aria-current",
        "page"
    );
    expect(within(navigation).getByRole("link", { name: "工作台" })).not.toHaveAttribute(
        "aria-current"
    );
});

it("每项导航都可达对应画面", async () => {
    const router = renderShell();
    const user = userEvent.setup();
    const navigation = screen.getByRole("navigation", { name: "产品导航" });
    for (const destination of destinations) {
        await user.click(within(navigation).getByRole("link", { name: destination.nav }));
        expect(router.state.location.pathname).toBe(destination.path);
        expect(
            screen.getByRole("heading", { name: `${destination.label} 页面` })
        ).toBeInTheDocument();
    }
});

it("rail-foot 主题钮翻转 data-theme 并持久化", async () => {
    renderShell();
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "切换主题" });
    await user.click(button);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("oa-theme")).toBe("light");
    await user.click(button);
    expect(document.documentElement.dataset.theme).toBe("dark");
});

it("密度钮切换 body.quiet 类", async () => {
    renderShell();
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "紧凑模式" });
    await user.click(button);
    expect(document.body.classList.contains("quiet")).toBe(true);
    await user.click(button);
    expect(document.body.classList.contains("quiet")).toBe(false);
});

it("footer 使用产品语言并保留键盘直达工作区", () => {
    renderShell();
    expect(screen.getByText("OnlyAlpha · 个人量化工作台")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).not.toHaveTextContent("Authority");
    expect(screen.getByRole("link", { name: "跳到工作区" })).toHaveAttribute(
        "href",
        "#workspace-content"
    );
    expect(document.getElementById("workspace-content")).toHaveAttribute("tabindex", "-1");
});

it("不夸大未实现画面的能力", () => {
    renderShell();
    expect(screen.queryByRole("link", { name: "新建研究" })).not.toBeInTheDocument();
    expect(screen.queryByText("Control + Presentation")).not.toBeInTheDocument();
});

it("工作台路由渲染上下文条与工具条挂载点", () => {
    renderShell("/");
    const host = document.getElementById("workspace-toolbar-host");
    expect(host).not.toBeNull();
    expect(host?.closest(".context-bar")).not.toBeNull();
    expect(document.querySelector(".view-head")).toBeNull();
    expect(document.body.classList.contains("no-ctx")).toBe(false);
});

it("非工作台路由不渲染上下文条并标记 no-ctx", () => {
    renderShell("/strategies");
    expect(document.getElementById("workspace-toolbar-host")).toBeNull();
    expect(document.body.classList.contains("no-ctx")).toBe(true);
});

it("footer 快捷导航只含既有画面链接与产品文案", () => {
    renderShell("/");
    const footer = screen.getByRole("contentinfo");
    for (const label of ["总览", "工作台", "数据", "系统"]) {
        expect(within(footer).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(within(footer).getByText("OnlyAlpha · 个人量化工作台")).toBeInTheDocument();
    expect(within(footer).queryByText(/版本|健康|延迟/)).not.toBeInTheDocument();
});

it("设置入口唯一且带图标", () => {
    renderShell();
    const settings = screen.getByRole("button", { name: "全局设置" });
    expect(settings.querySelector("svg")).not.toBeNull();
    expect(settings.closest(".workspace-settings-anchor")).not.toBeNull();
    expect(screen.getAllByRole("button", { name: "全局设置" })).toHaveLength(1);
});

it("壳在无 PageHeader 的画面也提供开启导航入口", async () => {
    renderShell("/strategies");
    const toggle = screen.getByRole("button", { name: "开启导航" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
});

it("开抽屉焦点移入侧栏，Esc 关闭后焦点回到开启导航钮", async () => {
    renderShell("/");
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "开启导航" });
    toggle.focus();
    await user.click(toggle);
    const inRail = document.querySelector<HTMLElement>(".side-rail a, .side-rail button");
    if (!inRail) throw new Error("rail focusable missing");
    expect(inRail).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(toggle).toHaveFocus();
});
