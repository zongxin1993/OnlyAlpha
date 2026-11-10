import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { OverviewPlaceholder } from "./OverviewPlaceholder";

function renderPlaceholder() {
    render(
        <MemoryRouter initialEntries={["/overview"]}>
            <OverviewPlaceholder />
        </MemoryRouter>
    );
}

it("总览占位以页内标题开场并诚实标注交付阶段", () => {
    renderPlaceholder();
    const head = document.querySelector(".view-head");
    expect(head).not.toBeNull();
    expect(screen.getByRole("heading", { name: "总览" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("P3");
});

it("总览占位不发明数据组件", () => {
    renderPlaceholder();
    expect(document.querySelector("canvas")).toBeNull();
    expect(document.querySelector("[role='table']")).toBeNull();
    expect(screen.queryByText(/上证指数|恒生|BTC/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往工作台" })).toHaveAttribute("href", "/");
});

it("页内标题条提供窄屏导航开关并同步 aria-expanded", async () => {
    renderPlaceholder();
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "开启导航" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
});
