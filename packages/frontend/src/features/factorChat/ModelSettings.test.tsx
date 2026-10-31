import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ModelSettings } from "./ModelSettings";
import { request, ChatRequestError } from "./api";
vi.mock(import("./api"), async (original) => ({ ...(await original()), request: vi.fn() }));
afterEach(() => {
    cleanup();
    sessionStorage.clear();
    vi.resetAllMocks();
});
const access = {
    schema_version: 1 as const,
    token: "token",
    expires_at: 4000000000,
    subject: "owner",
    agent_url: "https://agent.example",
    binding: "a".repeat(64)
};
function show() {
    render(<ModelSettings access={access} model={null} blocked={false} onSaved={vi.fn()} />);
    for (const [label, value] of [
        ["服务地址", "https://model.example/v1"],
        ["模型名称", "model"],
        ["模型版本说明", "v1"],
        ["API 密钥", "private-key"]
    ] as const)
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
it("requires a successful test of the current configuration before saving", async () => {
    vi.mocked(request).mockResolvedValue({ reply: "连接成功。" });
    show();
    expect(screen.getByRole("button", { name: "保存模型设置" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText("连接成功。")).toBeVisible();
    expect(sessionStorage.getItem("onlyalpha.agent.model-save")).toBeNull();
    expect(vi.mocked(request).mock.calls[0]?.[0]).toBe("/api/v1/agent/models/test");
    expect(screen.getByRole("button", { name: "保存模型设置" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "changed" } });
    expect(screen.getByRole("button", { name: "保存模型设置" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "模型配置" }));
    await waitFor(() => {
        expect(sessionStorage.getItem("onlyalpha.agent.model-save")).toBeNull();
    });
    expect(request).toHaveBeenCalledTimes(1);
});
it("explains rejected addresses without creating a pending save", async () => {
    vi.mocked(request).mockRejectedValue(new ChatRequestError("AGENT_MODEL_ENDPOINT_INVALID"));
    show();
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText(/公网地址请使用 HTTPS/)).toBeVisible();
    expect(screen.getByRole("button", { name: "保存模型设置" })).toBeDisabled();
    expect(sessionStorage.getItem("onlyalpha.agent.model-save")).toBeNull();
});
