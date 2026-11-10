import { render, screen } from "@testing-library/react";
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

/* 开启导航入口归壳（WorkstationShell），由 shell 测试覆盖。 */
