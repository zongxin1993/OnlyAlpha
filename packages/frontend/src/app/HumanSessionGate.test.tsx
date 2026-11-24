import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HumanSessionControls, HumanSessionGate } from "./HumanSessionGate";
import { bindHumanSession, humanSessionStorage, humanSessionPath } from "./humanSession";

function mount() {
    return render(
        <StrictMode>
            <HumanSessionGate>
                <h1>工作台</h1>
                <HumanSessionControls />
            </HumanSessionGate>
        </StrictMode>
    );
}

afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
    bindHumanSession({ subject_id: "local-developer", can_logout: false });
});

it("通过会话检查后才挂载单人工作台", async () => {
    const fetch = vi
        .fn()
        .mockResolvedValue(Response.json({ subject_id: "local-developer", can_logout: false }));
    vi.stubGlobal("fetch", fetch);
    mount();
    expect(screen.queryByRole("heading", { name: "工作台" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "工作台" })).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "退出登录" })).toBeNull();
});

it("服务不可用时保留查询入口", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    mount();
    expect(await screen.findByRole("button", { name: "重新查看登录状态" })).toBeVisible();
    expect(screen.queryByLabelText("登录凭据")).toBeNull();
});

it("凭据只在正式登录请求头发送，拒绝后清空输入框", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetch);
    mount();
    const field = await screen.findByLabelText("登录凭据");
    const credential = "a".repeat(64);
    const user = userEvent.setup();
    await user.type(field, credential + "{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("登录凭据无效");
    expect(field).toHaveValue("");
    expect(fetch).toHaveBeenLastCalledWith(humanSessionPath, {
        method: "POST",
        mode: "same-origin",
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: { Authorization: `Bearer ${credential}` }
    });
    expect(sessionStorage.length).toBe(0);
});

it("原用户重新登录后可取回待确认命令，其他用户使用独立记录", () => {
    const a = { subject_id: "a", can_logout: true };
    bindHumanSession(a);
    humanSessionStorage.setItem("original", "command-a");
    bindHumanSession({ subject_id: "b", can_logout: true });
    expect(humanSessionStorage.getItem("original")).toBeNull();
    humanSessionStorage.setItem("original", "command-b");
    humanSessionStorage.removeItem("original");
    bindHumanSession(a);
    expect(humanSessionStorage.getItem("original")).toBe("command-a");
});
