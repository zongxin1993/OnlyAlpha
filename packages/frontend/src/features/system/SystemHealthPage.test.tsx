import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SystemHealthPage } from "./SystemHealthPage";

function respond(status: number, body: unknown) {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" }
    });
}

const fetchMock = vi.fn();

beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
});

afterEach(() => {
    vi.unstubAllGlobals();
});

it("系统画面诚实页头：h1 系统 + 运行时状态副标题，缺省卡不造假", async () => {
    // 组件只会以字符串路径调用 fetch，mock 直接按字符串参数分流。
    fetchMock.mockImplementation((input: string) =>
        Promise.resolve(respond(200, { status: input.endsWith("/live") ? "LIVE" : "READY" }))
    );
    render(<SystemHealthPage />);
    expect(await screen.findByRole("heading", { level: 1, name: "系统" })).toBeInTheDocument();
    expect(screen.getByText("运行时状态")).toBeInTheDocument();
    expect(
        screen.getByText(/后端版本与迁移号暂无正式查询端点（QUERY_GAP），此处宁缺毋假/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/\d+\.\d+\.\d+/)).not.toBeInTheDocument();
});

it("探针确认后展示真实状态词", async () => {
    // 组件只会以字符串路径调用 fetch，mock 直接按字符串参数分流。
    fetchMock.mockImplementation((input: string) =>
        Promise.resolve(respond(200, { status: input.endsWith("/live") ? "LIVE" : "READY" }))
    );
    render(<SystemHealthPage />);
    expect(await screen.findByText("LIVE")).toBeVisible();
    expect(await screen.findByText("READY")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith("/health/live", expect.anything());
    expect(fetchMock).toHaveBeenCalledWith("/health/ready", expect.anything());
});

it("就绪探针 503 时说明未生效并可重新查看", async () => {
    fetchMock.mockImplementation((input: string) =>
        Promise.resolve(
            input.endsWith("/live")
                ? respond(200, { status: "LIVE" })
                : respond(503, { error: { code: "NOT_READY" } })
        )
    );
    render(<SystemHealthPage />);
    expect(await screen.findByText(/未确认/)).toBeVisible();
    expect(await screen.findByText(/本次查看未生效/)).toBeVisible();
    fetchMock.mockImplementation(() => Promise.resolve(respond(200, { status: "READY" })));
    await userEvent.click(screen.getByRole("button", { name: "重新查看" }));
    await waitFor(() => {
        expect(screen.getAllByText("READY").length).toBeGreaterThan(0);
    });
});

it("网络失败同样走未确认路径，不猜测状态", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    render(<SystemHealthPage />);
    // 两个探针各自独立走未确认路径，恰好两行。
    expect(await screen.findAllByText(/未确认/)).toHaveLength(2);
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
    expect(screen.queryByText("READY")).not.toBeInTheDocument();
});
