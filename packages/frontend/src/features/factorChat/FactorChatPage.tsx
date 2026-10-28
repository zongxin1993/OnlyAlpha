import { useCallback, useEffect, useState } from "react";
import { z } from "zod";
import { useIntegrationApi } from "../../app/providers";
import { DataSourceConfigurationView } from "../data/sources/DataSourceConfigurationView";
import {
    ChatRequestError,
    observationSchema,
    commandSchema,
    request,
    chatSchema,
    chatsSchema,
    providersSchema,
    type Chat
} from "./api";
import "./factorChat.css";
const currentKey = "onlyalpha.factor-chat.selected";
const pendingKey = "onlyalpha.factor-chat.pending";
const pendingSchema = z.strictObject({
    conversation: z.uuid(),
    command: z.uuid(),
    body: commandSchema
});
const explanations: Record<string, string> = {
    FACTOR_CHAT_MODEL_OUTCOME_UNKNOWN: "模型调用结果未知。请核对原对话；不会自动重复调用。",
    FACTOR_CHAT_MODEL_BINDING_UNAVAILABLE:
        "模型配置已改变或不可用，请检查设置。原对话的模型绑定不会自动替换。",
    FACTOR_CHAT_MODEL_RESPONSE_INVALID: "模型返回的候选超出受支持范围，请通过聊天说明或修改想法。",
    FACTOR_CHAT_CAPACITY_REACHED: "当前对话已达到容量限制，请新建对话继续讨论。",
    FACTOR_CHAT_MODEL_CREDENTIAL_UNAVAILABLE: "模型凭据不可用，请检查模型设置。",
    FACTOR_CHAT_MODEL_FAILED: "模型服务拒绝了本次请求。你可以检查配置后明确发起新消息。",
    FACTOR_CHAT_PREVIEW_CONFLICT: "预览已改变，请先核对当前版本。",
    FACTOR_CHAT_CONFLICT: "另一页面已更新此对话，请重新载入。",
    FACTOR_CHAT_AUTHORING_CONFLICT: "因子已在其他编辑入口修改，请先核对草稿，不能覆盖该修改。"
};
function dataLabel(key: string, value: unknown): string {
    const binding = z
        .object({
            input: z.string(),
            operator: z.string().optional(),
            period: z.number().optional()
        })
        .safeParse(value);
    if (!binding.success) return "数据依赖不可展示，请查看高级详情";
    const names: Record<string, string> = {
        open: "开盘价",
        high: "最高价",
        low: "最低价",
        close: "收盘价",
        volume: "成交量"
    };
    const name = names[binding.data.input] ?? key;
    if (binding.data.period === undefined) return `${name}（已收盘）`;
    return `${name}的${binding.data.operator?.endsWith("delay") ? "历史延迟" : "滚动均值"}：${String(binding.data.period)} 根已收盘 K 线`;
}
function readable(value: string): string {
    return explanations[value] ?? value;
}
function load() {
    return Promise.all([
        request("/api/v2/factor-chats", chatsSchema),
        request("/api/v2/factor-chat/providers", providersSchema)
    ]);
}
export function FactorChatPage() {
    const integrations = useIntegrationApi();
    const [chat, setChat] = useState<Chat | null>(null);
    const [items, setItems] = useState<Chat[]>([]);
    const [providers, setProviders] = useState<z.infer<typeof providersSchema>["items"]>([]);
    const [provider, setProvider] = useState("");
    const [configuration, setConfiguration] = useState("");
    const [text, setText] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [unknown, setUnknown] = useState(sessionStorage.getItem(pendingKey) !== null);
    const applyLoaded = useCallback(
        ([list, p]: [z.infer<typeof chatsSchema>, z.infer<typeof providersSchema>]) => {
            setItems(list.items);
            setProviders(p.items);
            const selected = localStorage.getItem(currentKey);
            setChat(list.items.find((c) => c.conversation_id === selected) ?? null);
            setProvider((previous) =>
                previous === ""
                    ? (p.items.find(
                          (v) => v.lifecycle === "ACTIVE" && v.revision_fingerprint !== null
                      )?.integration_id ?? "")
                    : previous
            );
        },
        []
    );
    const refresh = useCallback(async () => {
        applyLoaded(await load());
    }, [applyLoaded]);
    useEffect(() => {
        let active = true;
        void load()
            .then((result) => {
                if (active) applyLoaded(result);
            })
            .catch((e: unknown) => {
                if (active) setError(String(e));
            });
        return () => {
            active = false;
        };
    }, [applyLoaded]);
    async function act(work: () => Promise<void>) {
        setBusy(true);
        setError("");
        try {
            await work();
        } catch (e) {
            setError(readable(e instanceof Error ? e.message : String(e)));
        } finally {
            setBusy(false);
        }
    }
    async function send(operation: "CREATE" | "MESSAGE" | "CONFIRM") {
        const id = operation === "CREATE" ? crypto.randomUUID() : chat?.conversation_id;
        if (id === undefined) return;
        const p = providers.find((v) => v.integration_id === provider);
        if (operation === "CREATE" && p?.revision_fingerprint == null)
            throw new Error("请先配置并发布模型设置");
        const body = {
            schema_version: 1,
            operation,
            expected: operation === "CREATE" ? null : chat?.head,
            provider:
                operation === "CREATE"
                    ? { integration_id: provider, revision_fingerprint: p?.revision_fingerprint }
                    : null,
            text: operation === "MESSAGE" ? text : null,
            preview_fingerprint: operation === "CONFIRM" ? chat?.preview_fingerprint : null
        };
        const command = crypto.randomUUID();
        sessionStorage.setItem(pendingKey, JSON.stringify({ conversation: id, command, body }));
        localStorage.setItem(currentKey, id);
        setUnknown(true);
        let next: Chat;
        try {
            next = await request(`/api/v2/factor-chats/${id}/commands`, chatSchema, body, command);
        } catch (e) {
            if (e instanceof ChatRequestError && e.definitive) {
                sessionStorage.removeItem(pendingKey);
                setUnknown(false);
            }
            throw e;
        }
        if (next.conversation_id !== id) throw new Error("响应身份不一致，请核对原操作");
        setChat(next);
        sessionStorage.removeItem(pendingKey);
        setUnknown(false);
        setText("");
        await refresh();
    }
    async function recover() {
        const raw = sessionStorage.getItem(pendingKey);
        if (raw === null) {
            await refresh();
            return;
        }
        const pending = pendingSchema.parse(JSON.parse(raw));
        const outcome = await request(
            `/api/v2/factor-chats/${pending.conversation}/commands/${pending.command}`,
            observationSchema
        );
        if (!outcome.accepted && !outcome.abandoned) {
            setError("原操作尚未接受或仍未取得接受证明。可以明确放弃未接受的操作，然后重新开始。");
            return;
        }
        sessionStorage.removeItem(pendingKey);
        setUnknown(false);
        await refresh();
    }
    async function abandonPending() {
        const raw = sessionStorage.getItem(pendingKey);
        if (raw === null) return;
        const pending = pendingSchema.parse(JSON.parse(raw));
        const outcome = await request(
            `/api/v2/factor-chats/${pending.conversation}/commands`,
            observationSchema,
            { ...pending.body, abandon: true },
            pending.command
        );
        if (!outcome.accepted && !outcome.abandoned) throw new Error("尚未取得终态证明");
        sessionStorage.removeItem(pendingKey);
        setUnknown(false);
        await refresh();
    }
    return (
        <section className="factor-chat-page" aria-label="聊天因子研究">
            <header>
                <h1>因子研究</h1>
                <p>先讨论并确认因子；本阶段不会运行 Research。</p>
                <p>当前支持 OHLCV 四则运算、历史延迟和滚动均值。其他想法需要先明确能力缺口。</p>
            </header>
            <details className="factor-chat-models">
                <summary>模型设置</summary>
                <label>
                    模型配置
                    <select
                        value={provider}
                        onChange={(e) => {
                            setProvider(e.target.value);
                        }}
                    >
                        <option value="">请选择</option>
                        {providers.map((p) => (
                            <option key={p.integration_id} value={p.integration_id}>
                                {p.name}
                                {p.revision_fingerprint === null ? " · 未发布" : ""}
                            </option>
                        ))}
                    </select>
                </label>
                <button
                    disabled={busy || provider === ""}
                    onClick={() => {
                        setConfiguration(provider);
                    }}
                >
                    编辑模型设置
                </button>
                <button
                    disabled={busy}
                    onClick={() => {
                        void act(async () => {
                            const id = crypto.randomUUID();
                            localStorage.setItem("onlyalpha.factor-chat.model-setup", id);
                            await integrations.createIntegration(
                                {
                                    integration_id: id,
                                    type_id: "openai.compatible.agent_provider",
                                    display_name: "聊天模型"
                                },
                                crypto.randomUUID()
                            );
                            setProvider(id);
                            setConfiguration(id);
                            await refresh();
                        });
                    }}
                >
                    添加模型
                </button>
                <button
                    disabled={
                        busy || localStorage.getItem("onlyalpha.factor-chat.model-setup") === null
                    }
                    onClick={() => {
                        void act(async () => {
                            const id = localStorage.getItem("onlyalpha.factor-chat.model-setup");
                            if (id === null) return;
                            await integrations.getIntegration(id);
                            setConfiguration(id);
                            setProvider(id);
                        });
                    }}
                >
                    恢复上次模型设置
                </button>
                {configuration !== "" && (
                    <DataSourceConfigurationView
                        integrationId={configuration}
                        onBack={() => {
                            setConfiguration("");
                            void act(refresh);
                        }}
                    />
                )}
            </details>
            <div className="factor-chat-actions">
                <button
                    disabled={busy || unknown || provider === ""}
                    onClick={() => {
                        void act(() => send("CREATE"));
                    }}
                >
                    新建对话
                </button>
                <label>
                    研究历史
                    <select
                        value={chat?.conversation_id ?? ""}
                        disabled={busy || unknown}
                        onChange={(e) => {
                            localStorage.setItem(currentKey, e.target.value);
                            setChat(
                                items.find((c) => c.conversation_id === e.target.value) ?? null
                            );
                        }}
                    >
                        <option value="">选择已有对话</option>
                        {items.map((c) => (
                            <option key={c.conversation_id} value={c.conversation_id}>
                                {c.preview?.name ??
                                    c.messages
                                        .find((m) => m.role === "user")
                                        ?.content.slice(0, 32) ??
                                    "新对话"}
                            </option>
                        ))}
                    </select>
                </label>
                <button
                    disabled={busy}
                    onClick={() => {
                        void act(recover);
                    }}
                >
                    核对并重新载入
                </button>
            </div>
            {error !== "" && <p role="alert">{error}</p>}
            {unknown && !busy && (
                <button
                    disabled={busy}
                    onClick={() => {
                        void act(abandonPending);
                    }}
                >
                    放弃未接受的操作
                </button>
            )}
            {unknown && (
                <p role="status">原操作结果待核对。请使用“核对并重新载入”，不会自动重发。</p>
            )}
            <div className="factor-chat-columns">
                <section aria-label="因子讨论">
                    <h2>讨论想法</h2>
                    <div className="factor-chat-messages" aria-live="polite">
                        {chat?.messages.map((m, i) => (
                            <article key={i} className={m.role}>
                                <strong>{m.role === "user" ? "我" : "Agent"}</strong>
                                <p>{readable(m.content)}</p>
                            </article>
                        ))}
                    </div>
                    {chat === null ? (
                        <p>配置模型后新建对话，描述你想研究的价格、成交量或其他关系。</p>
                    ) : (
                        <form
                            onSubmit={(e) => {
                                e.preventDefault();
                                void act(() =>
                                    send(
                                        ["确认因子", "确认当前因子"].includes(text.trim())
                                            ? "CONFIRM"
                                            : "MESSAGE"
                                    )
                                );
                            }}
                        >
                            <label>
                                告诉 Agent 你的想法
                                <textarea
                                    value={text}
                                    onChange={(e) => {
                                        setText(e.target.value);
                                    }}
                                    maxLength={2000}
                                    disabled={busy || unknown}
                                />
                            </label>
                            <button disabled={busy || unknown || text.trim() === ""}>
                                {busy ? "处理中…" : "发送"}
                            </button>
                            <p>确认当前预览时，可发送“确认因子”。修改想法不会启动研究。</p>
                        </form>
                    )}
                </section>
                <section aria-label="因子预览">
                    <h2>因子预览</h2>
                    {chat?.preview == null ? (
                        <p>澄清想法后，因子预览会出现在这里。</p>
                    ) : (
                        <>
                            <h3>{chat.preview.name}</h3>
                            <p>{chat.preview.purpose}</p>
                            <h4>预测假设</h4>
                            <p>{chat.preview.hypothesis}</p>
                            <h4>计算逻辑与公式</h4>
                            <pre>{chat.preview.formula}</pre>
                            <p>仅使用已收盘数据；缺失值与除零按现有契约处理。</p>
                            <h4>所需数据</h4>
                            <ul>
                                {Object.entries(chat.preview.dependencies).map(([key, binding]) => (
                                    <li key={key}>{dataLabel(key, binding)}</li>
                                ))}
                            </ul>
                            <details>
                                <summary>高级详情：代码与契约</summary>
                                <pre>{chat.preview.draft.source_text}</pre>
                                <pre>{JSON.stringify(chat.preview.dependencies, null, 2)}</pre>
                                <pre>
                                    {JSON.stringify(
                                        {
                                            input: chat.preview.draft.input_contract,
                                            parameter: chat.preview.draft.parameter_contract,
                                            output: chat.preview.draft.output_contract
                                        },
                                        null,
                                        2
                                    )}
                                </pre>
                            </details>
                            <p role="status">
                                {chat.confirmed ? "计算内容已确认并保存" : "待确认当前因子"}
                                {chat.confirmed && !chat.display_confirmed
                                    ? "；名称和用途修改待保存"
                                    : ""}
                            </p>
                            <button
                                disabled={
                                    busy || unknown || (chat.confirmed && chat.display_confirmed)
                                }
                                onClick={() => {
                                    void act(() => send("CONFIRM"));
                                }}
                            >
                                {chat.confirmed ? "保存名称和用途" : "确认当前因子"}
                            </button>
                        </>
                    )}
                    {chat?.status === "OUTCOME_UNKNOWN" && (
                        <p role="status">
                            模型正在处理或结果未知。请核对原对话；不会重复调用模型。
                        </p>
                    )}
                </section>
            </div>
        </section>
    );
}
