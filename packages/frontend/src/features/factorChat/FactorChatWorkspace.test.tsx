import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FactorChatPage } from "./FactorChatPage";
import { accessKey, request, type Chat } from "./api";

vi.mock(import("./api"), async (original) => ({ ...(await original()), request: vi.fn() }));
const sid = "00000000-0000-4000-8000-000000000001";
const mid = "00000000-0000-4000-8000-000000000002";
const oldHead = "a".repeat(64),
    head = "b".repeat(64),
    fingerprint = "c".repeat(64);
const modelRevision = "d".repeat(64);
const access = {
    schema_version: 1,
    token: "test",
    expires_at: 4_000_000_000,
    subject: "owner",
    agent_url: "https://agent.example",
    binding: "e".repeat(64)
};
const candidate = {
    name: "20日动量",
    purpose: "观察价格延续",
    hypothesis: "上涨可能延续",
    expression: { input: "close", lag: 20 }
};
const proposal = {
    schema_version: 1,
    fingerprint,
    is_current: true,
    withdrawn: false,
    snapshot: {
        schema_version: 1,
        owner: "owner",
        factor_id: "private.momentum",
        origin: { session_id: sid, event_fingerprint: head },
        preview: {
            ...candidate,
            formula: "close / lag(close,20) - 1",
            dependencies: {},
            draft: {
                source_text: "code",
                input_contract: {},
                parameter_contract: {},
                output_contract: {}
            },
            draft_fingerprint: fingerprint,
            execution_admitted: false
        }
    },
    confirmation: null
};
const reference = { command: mid, head, fingerprint };
const chat = {
    id: sid,
    workflow: oldHead,
    model_revision: modelRevision,
    head,
    consumed: 2,
    model_call_limit: 20,
    messages: [
        { role: "user", content: "研究动量" },
        { role: "assistant", content: "这是最新建议" }
    ],
    status: "READY",
    candidate,
    factor_reference: reference,
    study_reference: null,
    topic: "FACTOR",
    study: null,
    execution_admitted: false
};
function requests(selected = true) {
    vi.mocked(request).mockImplementation((path) =>
        Promise.resolve().then(() => {
            if (path === "/api/v1/agent/models") return { items: [] };
            if (path === "/api/v1/agent/sessions") return { items: selected ? [chat] : [] };
            if (path.endsWith("/conversation"))
                return {
                    id: sid,
                    head,
                    model_revision: modelRevision,
                    model: { name: "原研究模型", model_id: "research", model_version: "v1" },
                    turns: [
                        {
                            head: oldHead,
                            topic: "FACTOR",
                            user: "先研究短期动量",
                            assistant: "这是第一版建议",
                            status: "READY",
                            candidate: { ...candidate, name: "5日动量" },
                            study: null,
                            factor_reference: null,
                            study_reference: null
                        },
                        {
                            head,
                            topic: "FACTOR",
                            user: "改为20日",
                            assistant: "这是最新建议",
                            status: "READY",
                            candidate,
                            study: null,
                            factor_reference: reference,
                            study_reference: null
                        }
                    ]
                };
            if (path === `/api/v2/factor-proposals/${fingerprint}`) return proposal;
            if (path === "/api/v2/agent-connection")
                return {
                    schema_version: 1,
                    connection: {
                        schema_version: 1,
                        agent_url: access.agent_url,
                        grant_id: mid,
                        service_subject: "agent",
                        credential_sha256: oldHead
                    },
                    grant_state: "ACTIVE"
                };
            throw new Error(`unexpected request ${path}`);
        })
    );
}
beforeEach(() => {
    sessionStorage.setItem(accessKey, JSON.stringify(access));
    localStorage.setItem("onlyalpha.agent.chat.selected", sid);
});
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
    sessionStorage.clear();
    localStorage.clear();
});

it("keeps each historical factor inside its own reply and only offers the current exact confirmation", async () => {
    requests();
    render(<FactorChatPage />);
    const history = await screen.findByRole("navigation", { name: "研究历史" });
    expect(history).toHaveTextContent("20日动量");
    const first = await screen.findByRole("article", { name: "助手回复 1" });
    const latest = screen.getByRole("article", { name: "助手回复 2" });
    expect(first).toHaveTextContent("5日动量");
    expect(first).not.toHaveTextContent("20日动量");
    expect(within(first).queryByRole("button", { name: "确认当前因子" })).toBeNull();
    expect(within(latest).getByRole("button", { name: "确认当前因子" })).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "当前研究的模型" })).toBeDisabled();
    expect(screen.getByText("原研究模型")).toBeVisible();
    expect(screen.queryByText("模型设置", { selector: "summary" })).toBeNull();
});

it("keeps a composer discoverable before a study exists and filters history without changing selection", async () => {
    requests();
    render(<FactorChatPage />);
    const search = await screen.findByRole("textbox", { name: "搜索研究历史" });
    fireEvent.change(search, { target: { value: "不存在" } });
    await waitFor(() => {
        expect(
            within(screen.getByRole("navigation", { name: "研究历史" })).queryByText("20日动量")
        ).toBeNull();
    });
    expect(screen.getByRole("textbox", { name: "告诉助手你的想法" })).toBeVisible();
    expect(localStorage.getItem("onlyalpha.agent.chat.selected")).toBe(sid);
});

it("shows an actionable empty state instead of model configuration and engineering instructions", async () => {
    requests(false);
    localStorage.clear();
    render(<FactorChatPage />);
    expect(await screen.findByRole("button", { name: "添加模型" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "告诉助手你的想法" })).toBeVisible();
    expect(screen.queryByText(/Fingerprint|Reducer|DTO|Lease|Revision Hash|Authority/)).toBeNull();
});

it("does not submit a Chinese composition until it ends", async () => {
    requests();
    render(<FactorChatPage />);
    const input = await screen.findByRole("textbox", { name: "告诉助手你的想法" });
    await screen.findByRole("article", { name: "助手回复 2" });
    fireEvent.change(input, { target: { value: "把观察周期改成30日" } });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", isComposing: true });
    expect(vi.mocked(request).mock.calls.every((call) => call[2] === undefined)).toBe(true);
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => {
        expect(vi.mocked(request).mock.calls.some((call) => call[2] !== undefined)).toBe(true);
    });
});

it("keeps the original unresolved save identity available only in diagnostic details", async () => {
    requests();
    sessionStorage.setItem(
        "onlyalpha.agent.chat.pending",
        JSON.stringify({ kind: "stage", resource: sid, command: mid, binding: access.binding })
    );
    render(<FactorChatPage />);
    const pending = await screen.findByRole("region", { name: "待核对的操作" });
    expect(within(pending).getByText("原登记操作详情")).toBeVisible();
    expect(within(pending).getByText(mid)).not.toBeVisible();
});

it("explains an interrupted model reply once without duplicating internal confirmation warnings", async () => {
    requests();
    const original = vi.mocked(request).getMockImplementation();
    if (!original) throw new Error("request fixture unavailable");
    vi.mocked(request).mockImplementation(async (...args) => {
        if (args[0] === "/api/v1/agent/sessions")
            return { items: [{ ...chat, status: "OUTCOME_UNKNOWN" }] };
        if (args[0].endsWith("/conversation"))
            return {
                id: sid,
                head,
                model_revision: modelRevision,
                model: { name: "原研究模型", model_id: "research", model_version: "v1" },
                turns: [
                    {
                        head,
                        topic: "STUDY",
                        user: "请建议当前因子的研究条件",
                        assistant: null,
                        status: "OUTCOME_UNKNOWN",
                        candidate: null,
                        study: null,
                        factor_reference: null,
                        study_reference: null
                    }
                ]
            };
        return original(...args);
    });
    render(<FactorChatPage />);
    expect(
        await screen.findByText(
            "模型连接中断，未收到完整回复。系统不会自动重复请求；已保存的内容仍可查看，可新建研究继续。"
        )
    ).toBeVisible();
    expect(screen.queryByText("回复结果尚未确认，请先核对原操作。")).not.toBeInTheDocument();
    expect(
        screen.queryByText("这次回复的结果尚未确认，不会重复调用模型。")
    ).not.toBeInTheDocument();
});

it.each(["ABANDONED", "OUTCOME_UNKNOWN"] as const)(
    "lets the user modify a refused study only after its owning resolution: %s",
    async (outcome) => {
        requests();
        const fallback = vi.mocked(request).getMockImplementation();
        if (fallback === undefined) throw new Error("Missing request mock");
        let abandoned = false;
        const studyChat = () => ({
            ...chat,
            topic: "STUDY",
            candidate: null,
            study: null,
            study_reference: { command: mid, head, fingerprint: null, abandoned }
        });
        vi.mocked(request).mockImplementation(async (...args) => {
            const [path] = args;
            if (path === "/api/v1/agent/sessions") return { items: [studyChat()] };
            if (path === `/api/v1/agent/sessions/${sid}`) return studyChat();
            if (path.endsWith("/resolve")) {
                abandoned = outcome === "ABANDONED";
                return {
                    status: outcome,
                    backend_command: mid,
                    receipt: abandoned
                        ? {
                              schema_version: 1,
                              command_id: mid,
                              operation_fingerprint: head,
                              effect: { registration_abandoned: true }
                          }
                        : null
                };
            }
            return fallback(...args);
        });
        sessionStorage.setItem(
            "onlyalpha.agent.chat.pending",
            JSON.stringify({ kind: "stage", resource: sid, command: mid, binding: access.binding })
        );
        render(<FactorChatPage />);
        fireEvent.click(await screen.findByRole("button", { name: "修改研究条件" }));
        const input = screen.getByRole("textbox", { name: "告诉助手你的想法" });
        if (outcome === "ABANDONED")
            await waitFor(() => {
                expect(input).toBeEnabled();
            });
        else {
            await screen.findByText("暂时无法修改条件，请稍后重试。原研究和报告会保留。");
            expect(input).toBeDisabled();
        }
        expect(
            vi.mocked(request).mock.calls.filter(([path]) => path.endsWith("/resolve"))
        ).toHaveLength(1);
        expect(
            vi
                .mocked(request)
                .mock.calls.some(
                    ([path]) => path.endsWith("/messages") || path.endsWith("/confirmation")
                )
        ).toBe(false);
    }
);

it("continues the same Factor on the current assistant without resetting its model budget", async () => {
    requests();
    const fallback = vi.mocked(request).getMockImplementation();
    if (fallback === undefined) throw new Error("Missing request mock");
    let abandoned = false;
    let child: Chat | null = null;
    const parent = () => ({
        ...chat,
        status: "WORKFLOW_UNAVAILABLE",
        current_workflow: "9".repeat(64),
        topic: "STUDY",
        candidate: null,
        study: null,
        study_reference: { command: mid, head, fingerprint: null, abandoned }
    });
    vi.mocked(request).mockImplementation(async (...args) => {
        const [path, , body, command] = args;
        if (path === "/api/v1/agent/sessions")
            return { items: [parent(), ...(child ? [child] : [])] };
        if (path === `/api/v1/agent/sessions/${sid}`) return parent();
        if (path.endsWith("/resolve")) {
            abandoned = true;
            return {
                status: "ABANDONED",
                backend_command: mid,
                receipt: {
                    schema_version: 1,
                    command_id: mid,
                    operation_fingerprint: head,
                    effect: { registration_abandoned: true }
                }
            };
        }
        if (path === "/api/v2/factor-study-continuations") {
            expect(body).toMatchObject({
                factor_proposal_fingerprint: fingerprint,
                source_session_id: sid,
                source_workflow_fingerprint: oldHead,
                workflow_fingerprint: "9".repeat(64),
                model_revision: modelRevision
            });
            return {
                schema_version: 1,
                command_id: command,
                operation_fingerprint: head,
                effect: { continuation_command_id: command }
            };
        }
        if (path.startsWith("/api/v1/agent/sessions/") && args[5] === "PUT") {
            const input = body as {
                model_revision: string;
                model_call_limit: number;
                continuation: {
                    parent_session: string;
                    parent_head: string;
                    backend_command: string;
                };
            };
            expect(input.model_call_limit).toBe(18);
            expect(input.model_revision).toBe(modelRevision);
            const childId = path.split("/").at(-1);
            if (childId === undefined) throw new Error("Missing session ID");
            child = {
                ...chat,
                execution_admitted: false,
                id: childId,
                workflow: "9".repeat(64),
                current_workflow: "9".repeat(64),
                head: null,
                status: "READY",
                consumed: 0,
                model_call_limit: 18,
                messages: [],
                topic: "STUDY",
                candidate: null,
                study: null,
                study_reference: null,
                continuation: input.continuation
            };
            return child;
        }
        if (child && path === `/api/v1/agent/sessions/${child.id}`) return child;
        if (child && path.startsWith("/api/v2/factor-study-continuations/"))
            return {
                schema_version: 1,
                command_id: path.split("/").at(-1),
                operation_fingerprint: head,
                snapshot: {
                    actor: "HUMAN",
                    kind: "CONTINUE_FACTOR_STUDY",
                    request: {
                        session_id: child.id,
                        factor_proposal_fingerprint: fingerprint,
                        workflow_fingerprint: child.workflow,
                        model_revision: modelRevision,
                        source_session_id: sid
                    }
                }
            };
        if (child && path === `/api/v1/agent/sessions/${child.id}/conversation`)
            return {
                id: child.id,
                head: null,
                model_revision: modelRevision,
                model: { name: "原研究模型", model_id: "research", model_version: "v1" },
                turns: []
            };
        return fallback(...args);
    });
    render(<FactorChatPage />);
    fireEvent.click(await screen.findByRole("button", { name: "修改研究条件" }));
    await screen.findByRole("button", { name: "查看先前讨论和报告" });
    expect(screen.getByRole("textbox", { name: "告诉助手你的想法" })).toBeEnabled();
    expect(
        vi.mocked(request).mock.calls.filter(([path]) => path.endsWith("/resolve"))
    ).toHaveLength(1);
    expect(
        vi
            .mocked(request)
            .mock.calls.some(
                ([path]) => path.endsWith("/messages") || path.endsWith("/confirmation")
            )
    ).toBe(false);
});
