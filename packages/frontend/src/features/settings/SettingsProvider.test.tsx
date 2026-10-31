/* eslint-disable @typescript-eslint/require-await */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SettingsProvider, useSettings } from "./SettingsProvider";
import { accessKey, request } from "../factorChat/api";
vi.mock(import("../factorChat/api"), async (original) => ({
    ...(await original()),
    request: vi.fn()
}));
vi.mock(import("../data/sources/DataSourceManager"), () => ({
    DataSourceManager: () => <p>数据源管理</p>
}));
const key = "onlyalpha.agent.model-save";
const legacyKey = "onlyalpha.agent.chat.pending";
const id = "00000000-0000-4000-8000-000000000001";
const command = "00000000-0000-4000-8000-000000000002";
const access = {
    schema_version: 1,
    token: "token",
    expires_at: 4000000000,
    subject: "owner",
    agent_url: "https://agent.example",
    binding: "a".repeat(64)
};
const pending = { kind: "model", resource: id, command, binding: access.binding };
const model = {
    id,
    owner: "owner",
    name: "研究模型",
    base_url: "https://model.example/v1",
    model_id: "model",
    model_version: "v1",
    credential_generation: command,
    parent: null,
    revision: "b".repeat(64)
};
function Entry() {
    const { openSettings } = useSettings();
    return (
        <button
            onClick={() => {
                openSettings("models");
            }}
        >
            设置模型
        </button>
    );
}
function show() {
    render(
        <SettingsProvider>
            <Entry />
        </SettingsProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: "设置模型" }));
}
async function editAndTest() {
    fireEvent.click(await screen.findByRole("button", { name: "添加模型" }));
    for (const [label, value] of [
        ["服务地址", "https://model.example/v1"],
        ["模型名称", "model"],
        ["模型版本说明", "v1"],
        ["API 密钥", "never-store-me"]
    ] as const)
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    await screen.findByText("连接成功。");
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "保存模型设置" })).toBeEnabled();
    });
}
beforeEach(() => {
    const computedStyle = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) => computedStyle(element));
    sessionStorage.setItem(accessKey, JSON.stringify(access));
    vi.mocked(request).mockImplementation(async (path) => {
        if (path === "/api/v1/agent/models") return { items: [] };
        if (path === "/api/v1/agent/models/test") return { reply: "连接成功。" };
        return { status: "ABANDONED", outcome: { abandoned: true } };
    });
});
afterEach(() => {
    cleanup();
    sessionStorage.clear();
    vi.restoreAllMocks();
    vi.resetAllMocks();
});
it("automatically clears an old rejected save so testing enables Save without recovery steps", async () => {
    sessionStorage.setItem(legacyKey, JSON.stringify(pending));
    show();
    await editAndTest();
    expect(sessionStorage.getItem(legacyKey)).toBeNull();
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(screen.queryByText(/核对保存结果|放弃未接受的保存|上一次操作/)).not.toBeInTheDocument();
    expect(screen.getAllByText("连接成功。")).toHaveLength(1);
    expect(screen.queryByText("测试成功，可以保存")).not.toBeInTheDocument();
    expect(
        vi
            .mocked(request)
            .mock.calls.some(
                (call) =>
                    call[0] === `/api/v1/agent/commands/${command}/abandon` && call[2] !== undefined
            )
    ).toBe(true);
});
it("automatically restores a saved model on opening settings without a duplicate save", async () => {
    sessionStorage.setItem(legacyKey, JSON.stringify(pending));
    vi.mocked(request).mockImplementation(async (path) =>
        path === "/api/v1/agent/models"
            ? { items: [model] }
            : { status: "ACCEPTED", outcome: model }
    );
    show();
    expect(await screen.findByText("研究模型")).toBeVisible();
    expect(await screen.findByText("模型设置已保存")).toBeVisible();
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(vi.mocked(request).mock.calls.filter((call) => call[5] === "PUT")).toHaveLength(0);
});
it.each(["id", "owner", "credential_generation"])(
    "never accepts a mismatched %s receipt or erases its record",
    async (field) => {
        sessionStorage.setItem(legacyKey, JSON.stringify(pending));
        vi.mocked(request).mockResolvedValue({
            status: "ACCEPTED",
            outcome: { ...model, [field]: field === "id" ? command : "wrong" }
        });
        show();
        expect(await screen.findByText("模型设置暂时无法完成，请检查连接后重试。")).toBeVisible();
        expect(sessionStorage.getItem(key)).not.toBeNull();
    }
);
it("does not send an old command to a different Agent binding", async () => {
    sessionStorage.setItem(legacyKey, JSON.stringify({ ...pending, binding: "c".repeat(64) }));
    show();
    expect(await screen.findByText("模型设置暂时无法完成，请检查连接后重试。")).toBeVisible();
    expect(vi.mocked(request).mock.calls.some((call) => call[0].includes("/commands/"))).toBe(
        false
    );
    expect(sessionStorage.getItem(key)).not.toBeNull();
});
it("automatically resolves a lost save reply and shows success without user reconciliation", async () => {
    let saved: unknown;
    vi.mocked(request).mockImplementation(async (path, _schema, _body, cmd, _access, method) => {
        if (path === "/api/v1/agent/models") return { items: [] };
        if (path === "/api/v1/agent/models/test") return { reply: "连接成功。" };
        if (method === "PUT") {
            saved = { ...model, id: path.split("/").at(-1), credential_generation: cmd };
            throw new Error("lost acknowledgement");
        }
        return { status: "ACCEPTED", outcome: saved };
    });
    show();
    await editAndTest();
    fireEvent.click(screen.getByRole("button", { name: "保存模型设置" }));
    expect(await screen.findByText("模型设置已保存")).toBeVisible();
    expect(screen.queryByRole("form", { name: "模型配置" })).not.toBeInTheDocument();
    expect(vi.mocked(request).mock.calls.filter((call) => call[5] === "PUT")).toHaveLength(1);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(JSON.stringify(sessionStorage)).not.toContain("never-store-me");
});
it("retains an unreachable save internally without showing manual recovery actions or overwriting chat work", async () => {
    const chat = JSON.stringify({ ...pending, kind: "message" });
    sessionStorage.setItem(legacyKey, chat);
    vi.mocked(request).mockImplementation(async (path, _schema, _body, _cmd, _access, method) => {
        if (path === "/api/v1/agent/models") return { items: [] };
        if (path === "/api/v1/agent/models/test") return { reply: "连接成功。" };
        if (method === "PUT" || path.includes("/commands/")) throw new Error("offline");
        throw new Error("unexpected");
    });
    show();
    await editAndTest();
    fireEvent.click(screen.getByRole("button", { name: "保存模型设置" }));
    expect(await screen.findByText("模型设置暂时无法完成，请检查连接后重试。")).toBeVisible();
    expect(sessionStorage.getItem(key)).not.toBeNull();
    expect(sessionStorage.getItem(legacyKey)).toBe(chat);
    expect(screen.getByLabelText("API 密钥")).toHaveValue("");
    expect(screen.queryByText(/核对保存结果|放弃未接受的保存/)).not.toBeInTheDocument();
});

it("ends a save that never committed and allows a normal fresh Save without recovery buttons", async () => {
    let writes = 0;
    vi.mocked(request).mockImplementation(
        async (path, _schema, _body, command, _access, method) => {
            if (path === "/api/v1/agent/models") return { items: [] };
            if (path === "/api/v1/agent/models/test") return { reply: "连接成功。" };
            if (method === "PUT") {
                writes++;
                if (writes === 1) throw new Error("request never arrived");
                return { ...model, id: path.split("/").at(-1), credential_generation: command };
            }
            return { status: "ABANDONED", outcome: { abandoned: true } };
        }
    );
    show();
    await editAndTest();
    fireEvent.click(screen.getByRole("button", { name: "保存模型设置" }));
    expect(await screen.findByText("模型设置暂时无法完成，请检查连接后重试。")).toBeVisible();
    expect(sessionStorage.getItem(key)).toBeNull();
    fireEvent.change(screen.getByLabelText("API 密钥"), { target: { value: "new-private-key" } });
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    await screen.findByText("连接成功。");
    fireEvent.click(screen.getByRole("button", { name: "保存模型设置" }));
    expect(await screen.findByText("模型设置已保存")).toBeVisible();
    expect(writes).toBe(2);
    const commands = vi
        .mocked(request)
        .mock.calls.filter((call) => call[5] === "PUT")
        .map((call) => call[3]);
    expect(new Set(commands).size).toBe(2);
    expect(JSON.stringify(sessionStorage)).not.toContain("new-private-key");
});

it.each(["ACCEPTED", "ABANDONED"])(
    "keeps the original model identity after reopening an unreachable %s save",
    async (status) => {
        sessionStorage.setItem(legacyKey, JSON.stringify(pending));
        let online = false;
        vi.mocked(request).mockImplementation(
            async (path, _schema, body, nextCommand, _access, method) => {
                if (path === "/api/v1/agent/models/test") {
                    online = true;
                    return { reply: "连接成功。" };
                }
                if (path.includes("/commands/")) {
                    if (!online) throw new Error("offline");
                    return { status, outcome: status === "ACCEPTED" ? model : { abandoned: true } };
                }
                if (method === "PUT") {
                    expect(path).toBe(`/api/v1/agent/models/${id}`);
                    expect(body).toMatchObject({
                        expected: status === "ACCEPTED" ? model.revision : null
                    });
                    return {
                        ...model,
                        credential_generation: nextCommand,
                        revision: "d".repeat(64)
                    };
                }
                return { items: [] };
            }
        );
        show();
        await screen.findByText("模型设置暂时无法完成，请检查连接后重试。");
        await editAndTest();
        fireEvent.click(screen.getByRole("button", { name: "保存模型设置" }));
        expect(await screen.findByText("模型设置已保存")).toBeVisible();
        const writes = vi.mocked(request).mock.calls.filter((call) => call[5] === "PUT");
        expect(writes.map((call) => call[0])).toEqual([`/api/v1/agent/models/${id}`]);
    }
);
