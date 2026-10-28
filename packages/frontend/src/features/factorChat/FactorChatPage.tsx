import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { ModelSettings } from "./ModelSettings";
import {
    ChatRequestError,
    commandSchema,
    connect,
    connectionSchema,
    modelsSchema,
    proposalSchema,
    registrationSchema,
    request,
    savedAccess,
    sessionSchema,
    sessionsSchema,
    type Access,
    type Chat,
    type Model,
    type Proposal
} from "./api";
import "./factorChat.css";
const currentKey = "onlyalpha.agent.chat.selected";
const pendingKey = "onlyalpha.agent.chat.pending";
const linksKey = "onlyalpha.agent.chat.proposals";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
const grantInput = z.strictObject({
    schema_version: z.literal(1),
    grant_id: z.uuid(),
    service_subject: z.string(),
    credential_sha256: sha,
    proposal_limit: z.number().int(),
    expires_at: z.string()
});
const pendingFields = {
    resource: z.uuid(),
    command: z.uuid(),
    fingerprint: sha.optional(),
    binding: sha.optional()
};
const pendingSchema = z.discriminatedUnion("kind", [
    z.strictObject({ ...pendingFields, kind: z.literal("grant"), body: grantInput }),
    z.strictObject({
        ...pendingFields,
        kind: z.enum(["model", "create", "message", "stage", "confirm", "withdraw"])
    })
]);
type Pending = z.infer<typeof pendingSchema>;
const linkSchema = z.record(z.string(), z.strictObject({ fingerprint: sha, head: sha }));
function pendingValue(): Pending | null {
    try {
        return pendingSchema.parse(JSON.parse(sessionStorage.getItem(pendingKey) ?? "null"));
    } catch {
        return null;
    }
}
function links() {
    try {
        return linkSchema.parse(JSON.parse(localStorage.getItem(linksKey) ?? "{}"));
    } catch {
        return {};
    }
}
const operation = z.strictObject({
    schema_version: z.literal(1),
    command_id: z.uuid(),
    operation_fingerprint: sha,
    effect: z.record(z.string(), z.unknown())
});
const messages: Record<string, string> = {
    AGENT_WORKFLOW_UNAVAILABLE:
        "原工作流版本不可用。记录和预算已保留；请恢复原版本或明确新建对话。",
    AGENT_MODEL_CONFLICT: "模型已在其他页面修改，请重新载入后核对。",
    AGENT_SESSION_BUSY: "此对话正在处理中，请核对原操作。",
    AGENT_PROPOSAL_HEAD_CONFLICT: "对话已更新，请先载入当前内容。",
    AGENT_BACKEND_NOT_CONFIGURED: "助手尚未配置 backend 连接，请检查部署配置。",
    AGENT_BACKEND_CONTEXT_UNAVAILABLE: "backend 不可用或登记权限已失效；仍可查看对话历史。",
    FACTOR_PROPOSAL_ALREADY_WITHDRAWN: "提案已撤回，请重新载入后继续讨论。",
    FACTOR_PROPOSAL_ALREADY_CONFIRMED: "因子已经确认，请重新载入当前内容。",
    FACTOR_PROPOSAL_INVALID: "方案或授权不符合当前要求，请调整后再提交。",
    AGENT_SESSION_CORRUPT: "会话的原始绑定无法验证，已暂停操作。",
    AGENT_BACKEND_PLAN_CORRUPT: "原登记记录无法验证，已暂停操作。",
    FACTOR_PROPOSAL_STALE: "这版提案已撤回或被更新，请重新载入当前预览。",
    FACTOR_PROPOSAL_AUTHORING_CONFLICT: "因子已在其他编辑入口修改，不能覆盖；请重新核对。",
    MODEL_OUTCOME_UNKNOWN: "模型结果未知；不会重复调用。",
    MODEL_RESPONSE_INVALID: "模型返回的内容不符合受支持契约，请明确调整想法。",
    AGENT_UNAUTHORIZED: "助手登录已失效，请点击“重新连接助手”后核对原操作。",
    AGENT_COMMAND_ABANDONED: "此操作已明确放弃，不会迟到执行。"
};
const readable = (e: unknown) => {
    const s = e instanceof Error ? e.message : String(e);
    return messages[s] ?? s;
};
function dependency(value: unknown): string {
    const v = z
        .object({
            input: z.string(),
            operator: z.string().optional(),
            period: z.number().optional()
        })
        .safeParse(value);
    if (!v.success) return "请查看高级详情";
    const name: Record<string, string> = {
        close: "收盘价",
        open: "开盘价",
        high: "最高价",
        low: "最低价",
        volume: "成交量"
    };
    return (
        (name[v.data.input] ?? v.data.input) +
        (v.data.period === undefined
            ? "（已收盘）"
            : `的${v.data.operator?.endsWith("delay") ? "历史延迟" : "滚动均值"}：${String(v.data.period)} 根已收盘 K 线`)
    );
}
export function FactorChatPage() {
    const [access, setAccess] = useState<Access | null>(savedAccess);
    const [items, setItems] = useState<Chat[]>([]);
    const [chat, setChat] = useState<Chat | null>(null);
    const [models, setModels] = useState<Model[]>([]);
    const [selectedModel, setSelectedModel] = useState("");
    const [editor, setEditor] = useState<string | null>(null);
    const [text, setText] = useState("");
    const [budget, setBudget] = useState(20);
    const [pending, setPending] = useState<Pending | null>(pendingValue);
    const [proposal, setProposal] = useState<Proposal | null>(null);
    const [connection, setConnection] = useState<z.infer<typeof connectionSchema> | null>(null);
    const [agentReady, setAgentReady] = useState(false);
    const [backendError, setBackendError] = useState("");
    const [agentError, setAgentError] = useState("");
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const generation = useRef(0);
    const approvalText = ["确认因子", "确认当前因子"].includes(text.trim());
    const dirty = text.trim() !== "" && !approvalText;
    function remember(input: Pending | null) {
        const p =
            input !== null && !["confirm", "withdraw", "grant"].includes(input.kind)
                ? { ...input, binding: input.binding ?? access?.binding }
                : input;
        if (p === null) sessionStorage.removeItem(pendingKey);
        else sessionStorage.setItem(pendingKey, JSON.stringify(p));
        setPending(p);
    }
    const refresh = useCallback(async (explicit?: Access) => {
        const tag = ++generation.current;
        const token = explicit ?? savedAccess();
        let current: Chat | null = null;
        const selected = localStorage.getItem(currentKey) ?? "";
        const a = (async () => {
            try {
                const auth = token ?? (await connect());
                const [m, s] = await Promise.all([
                    request("/api/v1/agent/models", modelsSchema, undefined, undefined, auth),
                    request("/api/v1/agent/sessions", sessionsSchema, undefined, undefined, auth)
                ]);
                if (tag !== generation.current) return;
                setAccess(auth);
                setModels(m.items);
                setSelectedModel((p) => (p === "" ? (m.items[0]?.id ?? "") : p));
                setItems(s.items);
                current = s.items.find((v) => v.id === selected) ?? null;
                setChat(current);
                setAgentReady(true);
                setAgentError("");
            } catch (e) {
                if (tag === generation.current) {
                    setAgentReady(false);
                    setAgentError("Agent 暂不可用：" + readable(e));
                }
            }
        })();
        const b = (async () => {
            try {
                const c = await request("/api/v2/agent-connection", connectionSchema);
                if (tag === generation.current) {
                    setConnection(c);
                    setBackendError("");
                }
            } catch (e) {
                if (tag === generation.current) {
                    setConnection(null);
                    setBackendError("backend 暂不可用：" + readable(e));
                }
            }
        })();
        await Promise.all([a, b]);
        if (tag !== generation.current) return;
        const owned = current as Chat | null;
        const ref = owned?.proposal;
        const saved = links()[selected];
        const fp = ref?.fingerprint ?? saved?.fingerprint;
        const head = ref?.head ?? saved?.head;
        if (fp === undefined || head === undefined || (owned !== null && owned.head !== head)) {
            setProposal(null);
            return;
        }
        try {
            const view = await request(`/api/v2/factor-proposals/${fp}`, proposalSchema);
            if (tag !== generation.current) return;
            if (
                view.fingerprint !== fp ||
                view.snapshot.origin.session_id !== selected ||
                view.snapshot.origin.event_fingerprint !== head
            )
                throw new Error("登记提案与当前对话不匹配，请核对原操作");
            setProposal(view);
            localStorage.setItem(
                linksKey,
                JSON.stringify({ ...links(), [selected]: { fingerprint: fp, head } })
            );
        } catch (e) {
            if (tag === generation.current) {
                setProposal(null);
                setBackendError("backend 暂不可用：登记提案无法核对，" + readable(e));
            }
        }
    }, []);
    useEffect(() => {
        const sequence = generation;
        void refresh();
        return () => {
            sequence.current++;
        };
    }, [refresh]);
    async function act(work: () => Promise<void>) {
        setBusy(true);
        setError("");
        try {
            await work();
        } catch (e) {
            setError(readable(e));
        } finally {
            setBusy(false);
        }
    }
    function auth(): Access {
        if (access === null) throw new Error("请先连接助手");
        return access;
    }
    async function stage(s: Chat) {
        if (s.head === null || s.candidate === null || s.status !== "READY") return;
        if (s.proposal?.fingerprint) return;
        const p: Pending = {
            kind: "stage",
            resource: s.id,
            command: s.proposal?.command ?? crypto.randomUUID()
        };
        remember(p);
        const r = await request(
            s.proposal === null
                ? `/api/v1/agent/sessions/${s.id}/proposals`
                : `/api/v1/agent/sessions/${s.id}/proposals/${p.command}/resume`,
            registrationSchema,
            { expected: s.head },
            p.command,
            auth()
        );
        if (r.status !== "REGISTERED" || r.receipt === null)
            throw new Error(
                r.status === "REJECTED"
                    ? "提案登记被拒绝，请核对原操作后调整。"
                    : "提案登记结果待核对，不会自动重发。"
            );
        remember(null);
    }
    async function create() {
        const id = crypto.randomUUID();
        const m = models.find((v) => v.id === selectedModel);
        if (m === undefined) throw new Error("请先配置模型");
        const p: Pending = { kind: "create", resource: id, command: crypto.randomUUID() };
        remember(p);
        localStorage.setItem(currentKey, id);
        await request(
            `/api/v1/agent/sessions/${id}`,
            sessionSchema,
            { model_revision: m.revision, model_call_limit: budget },
            p.command,
            auth(),
            "PUT"
        );
        remember(null);
        await refresh();
    }
    async function backendSubmission(p: Pending) {
        if (!["confirm", "withdraw", "grant"].includes(p.kind))
            throw new Error("原操作类型不可提交");
        let path: string;
        let body: object;
        if (p.kind === "grant") {
            path = "/api/v2/factor-proposal-grants";
            body = p.body;
        } else {
            const fp = p.fingerprint;
            if (fp === undefined) throw new Error("原提案身份不可用");
            path = `/api/v2/factor-proposals/${fp}/${p.kind === "confirm" ? "confirmation" : "withdrawal"}`;
            body = { schema_version: 1, proposal_fingerprint: fp };
        }
        let receipt;
        try {
            receipt = await request(path, operation, body, p.command);
        } catch (e) {
            // Only owning transaction refusals prove this exact attempt has no effect.
            // Network/auth/storage errors and UNKNOWN retain the original identity.
            if (
                e instanceof ChatRequestError &&
                [
                    "FACTOR_PROPOSAL_STALE",
                    "FACTOR_PROPOSAL_ALREADY_CONFIRMED",
                    "FACTOR_PROPOSAL_ALREADY_WITHDRAWN",
                    "FACTOR_PROPOSAL_AUTHORING_CONFLICT",
                    "FACTOR_PROPOSAL_GRANT_CONFLICT",
                    "FACTOR_PROPOSAL_INVALID"
                ].includes(e.message)
            )
                remember(null);
            throw e;
        }
        if (
            receipt.command_id !== p.command ||
            (p.kind === "grant"
                ? receipt.effect.grant_id !== p.resource
                : receipt.effect.proposal_fingerprint !== p.fingerprint)
        )
            throw new Error("原操作回执身份不匹配");
    }
    async function repeatBackend(p: Pending) {
        await backendSubmission(p);
        remember(null);
        if (p.kind === "confirm") setText("");
        await refresh();
    }
    async function confirm() {
        if (proposal === null) throw new Error("请先载入登记提案");
        const p: Pending = {
            kind: "confirm",
            resource: proposal.snapshot.origin.session_id,
            command: crypto.randomUUID(),
            fingerprint: proposal.fingerprint
        };
        remember(p);
        await repeatBackend(p);
    }
    async function returnToHistory() {
        // This is navigation only, never abandonment/cancellation of an accepted plan.
        // The Agent retains the exact original plan; reopening it stays blocked for reconciliation.
        localStorage.removeItem(currentKey);
        remember(null);
        setText("");
        setChat(null);
        setProposal(null);
        await refresh();
    }
    async function send() {
        if (approvalText) {
            await confirm();
            return;
        }
        if (chat === null) return;
        const s = chat;
        generation.current++;
        if (proposal !== null && !proposal.withdrawn) {
            const p: Pending = {
                kind: "withdraw",
                resource: s.id,
                command: crypto.randomUUID(),
                fingerprint: proposal.fingerprint
            };
            remember(p);
            await backendSubmission(p);
            remember(null);
        }
        setProposal(null);
        const p: Pending = { kind: "message", resource: s.id, command: crypto.randomUUID() };
        remember(p);
        const result = await request(
            `/api/v1/agent/sessions/${s.id}/messages`,
            sessionSchema,
            { expected: s.head, text },
            p.command,
            auth()
        );
        remember(null);
        setText("");
        await stage(result);
        await refresh();
    }
    async function recover() {
        let p = pendingValue();
        if (p?.binding !== undefined && p.binding !== auth().binding)
            throw new Error("原助手连接绑定不可用，请恢复原连接后核对；不会切换目标或重发。");
        if (p === null && chat?.proposal?.fingerprint === null) {
            p = { kind: "stage", resource: chat.id, command: chat.proposal.command };
            remember(p);
        }
        if (p === null) {
            await refresh();
            return;
        }
        if (["confirm", "withdraw", "grant"].includes(p.kind)) {
            const receipt = await request(
                `/api/v2/factor-proposals/commands/${p.command}`,
                operation
            );
            if (
                receipt.command_id !== p.command ||
                (p.kind === "grant"
                    ? receipt.effect.grant_id !== p.resource
                    : receipt.effect.proposal_fingerprint !== p.fingerprint)
            )
                throw new Error("原操作回执身份不匹配");
            remember(null);
            await refresh();
            return;
        }
        const o = await request(
            `/api/v1/agent/commands/${p.command}`,
            commandSchema,
            undefined,
            undefined,
            auth()
        );
        if (o.status === "UNKNOWN") {
            setError("尚未取得接受证明。可明确放弃未接受操作；不会自动重发。");
            return;
        }
        if (o.status === "ABANDONED") {
            remember(null);
            await refresh();
            return;
        }
        if (p.kind === "stage") {
            const result = await request(
                `/api/v1/agent/sessions/${p.resource}/proposals/${p.command}/resume`,
                registrationSchema,
                {},
                undefined,
                auth()
            );
            if (result.status !== "REGISTERED")
                throw new Error(
                    "原登记未取得成功证明。可保留原记录返回研究历史；原对话继续等待核对。"
                );
        }
        if (p.kind === "message") {
            const s = await request(
                `/api/v1/agent/sessions/${p.resource}/resume`,
                sessionSchema,
                {},
                undefined,
                auth()
            );
            remember(null);
            await stage(s);
        }
        remember(null);
        await refresh();
    }
    async function abandon() {
        const p = pendingValue();
        if (p?.binding !== undefined && p.binding !== auth().binding)
            throw new Error("原助手连接绑定不可用");
        if (p === null || ["confirm", "withdraw", "grant"].includes(p.kind)) return;
        const o = await request(
            `/api/v1/agent/commands/${p.command}/abandon`,
            commandSchema,
            {},
            undefined,
            auth()
        );
        if (o.status === "ACCEPTED") {
            await recover();
            return;
        }
        remember(null);
        await refresh();
    }
    async function grant() {
        if (connection === null) return;
        const c = connection.connection;
        const body: z.infer<typeof grantInput> = {
            schema_version: 1,
            grant_id: c.grant_id,
            service_subject: c.service_subject,
            credential_sha256: c.credential_sha256,
            proposal_limit: 100,
            expires_at: new Date(Date.now() + 86400000).toISOString()
        };
        const p: Pending = {
            kind: "grant",
            resource: c.grant_id,
            command: crypto.randomUUID(),
            body
        };
        remember(p);
        await backendSubmission(p);
        remember(null);
        await refresh();
    }
    const disabled = busy || pending !== null;
    const registrationPending = chat?.proposal?.fingerprint === null;
    const blocked =
        chat?.status === "OUTCOME_UNKNOWN" ||
        chat?.status === "WORKFLOW_UNAVAILABLE" ||
        registrationPending;
    const preview = proposal?.snapshot.preview;
    return (
        <section className="factor-chat-page" aria-label="聊天因子研究">
            <header>
                <h1>因子研究</h1>
                <p>先讨论并确认因子；本阶段不会运行 Research。</p>
                <p>支持 OHLCV 四则运算、历史延迟和滚动均值。模型建议不代表科学结论。</p>
            </header>
            <div className="factor-chat-actions">
                <button
                    disabled={busy}
                    onClick={() => {
                        void act(async () => {
                            const a = await connect();
                            setAccess(a);
                            await refresh(a);
                        });
                    }}
                >
                    重新连接助手
                </button>
                <button
                    disabled={busy}
                    onClick={() => {
                        void act(recover);
                    }}
                >
                    核对并重新载入
                </button>
            </div>
            {agentError !== "" && (
                <p role="status">{agentError}。已有登记提案仍由 backend 保存。</p>
            )}
            {backendError !== "" && (
                <p role="status">{backendError}。对话历史可独立查看，正式操作暂停。</p>
            )}
            {connection?.grant_state === "ABSENT" && (
                <section aria-label="提案登记权限">
                    <p>
                        启用助手仅允许登记因子提案：最多 100 次、24 小时，不允许确认、Research
                        或交易。
                    </p>
                    <button
                        disabled={disabled}
                        onClick={() => {
                            void act(grant);
                        }}
                    >
                        启用助手的提案登记
                    </button>
                </section>
            )}
            {connection !== null && ["EXPIRED", "REVOKED"].includes(connection.grant_state) && (
                <p role="status">
                    提案登记权限已到期或撤销，请管理员更新服务连接后重新授权。原对话和已登记内容保留。
                </p>
            )}
            <details className="factor-chat-models">
                <summary>模型设置</summary>
                <label>
                    新对话的模型
                    <select
                        value={selectedModel}
                        onChange={(e) => {
                            setSelectedModel(e.target.value);
                        }}
                    >
                        <option value="">请选择</option>
                        {models.map((m) => (
                            <option key={m.id} value={m.id}>
                                {m.name} · {m.model_version}
                            </option>
                        ))}
                    </select>
                </label>
                <button
                    disabled={disabled || !agentReady}
                    onClick={() => {
                        setEditor("new");
                    }}
                >
                    添加模型
                </button>
                <button
                    disabled={disabled || !agentReady || selectedModel === ""}
                    onClick={() => {
                        setEditor(selectedModel);
                    }}
                >
                    编辑模型设置
                </button>
                {access !== null && editor !== null && (
                    <ModelSettings
                        key={editor}
                        access={access}
                        blocked={pending !== null}
                        onSettled={() => {
                            setBusy(false);
                        }}
                        model={models.find((m) => m.id === editor) ?? null}
                        onPending={(resource, command) => {
                            setBusy(true);
                            remember({ kind: "model", resource, command });
                        }}
                        onSaved={async () => {
                            remember(null);
                            setEditor(null);
                            await refresh();
                        }}
                    />
                )}
            </details>
            <div className="factor-chat-actions">
                <label>
                    新对话最多模型调用次数
                    <input
                        type="number"
                        min={1}
                        max={100}
                        value={budget}
                        onChange={(e) => {
                            setBudget(Number(e.target.value));
                        }}
                    />
                </label>
                <button
                    disabled={disabled || !agentReady || selectedModel === ""}
                    onClick={() => {
                        void act(create);
                    }}
                >
                    新建对话
                </button>
                <label>
                    研究历史
                    <select
                        value={chat?.id ?? ""}
                        disabled={disabled}
                        onChange={(e) => {
                            localStorage.setItem(currentKey, e.target.value);
                            setText("");
                            setProposal(null);
                            void act(() => refresh());
                        }}
                    >
                        <option value="">选择已有对话</option>
                        {items.map((c) => (
                            <option key={c.id} value={c.id}>
                                {typeof c.candidate?.name === "string"
                                    ? c.candidate.name
                                    : (c.messages
                                          .find((m) => m.role === "user")
                                          ?.content.slice(0, 32) ?? "新对话")}
                            </option>
                        ))}
                    </select>
                </label>
            </div>
            {error !== "" && <p role="alert">{error}</p>}
            {pending !== null && (
                <>
                    <p role="status">原操作结果待核对，不会自动重发或创建新身份。</p>
                    {!["confirm", "withdraw", "grant"].includes(pending.kind) && (
                        <button
                            disabled={busy}
                            onClick={() => {
                                void act(abandon);
                            }}
                        >
                            放弃未接受的操作
                        </button>
                    )}
                    {["confirm", "withdraw", "grant"].includes(pending.kind) && (
                        <button
                            disabled={busy}
                            onClick={() => {
                                void act(() => repeatBackend(pending));
                            }}
                        >
                            {pending.kind === "confirm"
                                ? "再次提交同一确认"
                                : pending.kind === "withdraw"
                                  ? "再次提交同一撤回"
                                  : "再次提交同一授权"}
                        </button>
                    )}
                    {pending.kind === "stage" && (
                        <>
                            <p>
                                登记未完成。返回历史只结束当前页面的等待，原操作仍保留且不会自动重发。
                            </p>
                            <button
                                disabled={busy}
                                onClick={() => {
                                    void act(returnToHistory);
                                }}
                            >
                                保留记录，返回研究历史
                            </button>
                            <details>
                                <summary>原登记操作详情</summary>
                                <code>{pending.command}</code>
                            </details>
                        </>
                    )}
                </>
            )}
            <div className="factor-chat-columns">
                <section aria-label="因子讨论">
                    <h2>讨论想法</h2>
                    <div className="factor-chat-messages" aria-live="polite">
                        {chat?.messages.map((m, i) => (
                            <article key={i} className={m.role}>
                                <strong>{m.role === "user" ? "我" : "Agent"}</strong>
                                <p>{messages[m.content] ?? m.content}</p>
                            </article>
                        ))}
                    </div>
                    {chat === null ? (
                        <p>配置模型后新建对话，描述你的因子想法。</p>
                    ) : (
                        <>
                            <p>
                                模型调用：{chat.consumed} / {chat.model_call_limit}
                                。此对话保留创建时的模型和工作流绑定。
                            </p>
                            {blocked && (
                                <p role="status">
                                    {chat.status === "WORKFLOW_UNAVAILABLE"
                                        ? messages.AGENT_WORKFLOW_UNAVAILABLE
                                        : registrationPending
                                          ? "提案登记未完成，当前对话只读。请核对原操作，或保留记录返回研究历史。"
                                          : "模型仍在处理或结果未知；核对操作不会再次调用模型。"}
                                </p>
                            )}
                            {registrationPending && pending === null && (
                                <>
                                    <button
                                        disabled={busy}
                                        onClick={() => {
                                            void act(returnToHistory);
                                        }}
                                    >
                                        保留记录，返回研究历史
                                    </button>
                                    <details>
                                        <summary>原登记操作详情</summary>
                                        <code>{chat.proposal?.command}</code>
                                    </details>
                                </>
                            )}
                            {chat.status === "READY" &&
                                chat.candidate !== null &&
                                chat.proposal === null &&
                                pending === null && (
                                    <button
                                        disabled={busy || connection?.grant_state !== "ACTIVE"}
                                        onClick={() => {
                                            void act(async () => {
                                                await stage(chat);
                                                await refresh();
                                            });
                                        }}
                                    >
                                        登记当前因子预览
                                    </button>
                                )}
                            <form
                                onSubmit={(e) => {
                                    e.preventDefault();
                                    void act(send);
                                }}
                            >
                                <label>
                                    告诉 Agent 你的想法
                                    <textarea
                                        value={text}
                                        maxLength={8000}
                                        disabled={disabled || !agentReady || blocked}
                                        onChange={(e) => {
                                            setText(e.target.value);
                                        }}
                                    />
                                </label>
                                <button
                                    disabled={
                                        disabled ||
                                        !agentReady ||
                                        blocked ||
                                        text.trim() === "" ||
                                        (!approvalText && connection?.grant_state !== "ACTIVE")
                                    }
                                >
                                    {busy ? "处理中…" : "发送"}
                                </button>
                                <p>确认预览时可发送“确认因子”。修改想法后需要重新确认。</p>
                            </form>
                        </>
                    )}
                </section>
                <section aria-label="因子预览">
                    <h2>因子预览</h2>
                    {proposal === null || preview === undefined ? (
                        <p>澄清想法并登记后，预览会出现在这里。</p>
                    ) : (
                        <>
                            <h3>{preview.name}</h3>
                            <p>{preview.purpose}</p>
                            <h4>预测假设</h4>
                            <p>{preview.hypothesis}</p>
                            <h4>计算逻辑与公式</h4>
                            <pre>{preview.formula}</pre>
                            <p>仅使用已收盘数据；缺失值与除零按现有契约处理。</p>
                            <h4>所需数据</h4>
                            <ul>
                                {Object.entries(preview.dependencies).map(([key, v]) => (
                                    <li key={key}>{dependency(v)}</li>
                                ))}
                            </ul>
                            <details>
                                <summary>高级详情：代码与契约</summary>
                                <pre>{preview.draft.source_text}</pre>
                                <pre>
                                    {JSON.stringify(
                                        {
                                            dependencies: preview.dependencies,
                                            input: preview.draft.input_contract,
                                            parameter: preview.draft.parameter_contract,
                                            output: preview.draft.output_contract
                                        },
                                        null,
                                        2
                                    )}
                                </pre>
                            </details>
                            <p role="status">
                                {proposal.confirmation !== null
                                    ? "计算内容已确认并保存"
                                    : proposal.withdrawn || !proposal.is_current
                                      ? "此提案已撤回或更新，不能确认"
                                      : "待确认当前因子"}
                                {dirty ? "；正在编辑新想法，旧预览不可确认" : ""}
                            </p>
                            <button
                                disabled={
                                    disabled ||
                                    dirty ||
                                    proposal.withdrawn ||
                                    !proposal.is_current ||
                                    proposal.confirmation !== null ||
                                    backendError !== ""
                                }
                                onClick={() => {
                                    void act(() => confirm());
                                }}
                            >
                                确认当前因子
                            </button>
                        </>
                    )}
                </section>
            </div>
        </section>
    );
}
