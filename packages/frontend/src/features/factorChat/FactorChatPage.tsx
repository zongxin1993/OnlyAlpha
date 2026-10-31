import { migrateModelSave } from "./modelSave";
import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { Bubble, Conversations, Sender } from "@ant-design/x";
import {
    Alert,
    Button,
    Card,
    Drawer,
    Input,
    InputNumber,
    Modal,
    Popover,
    Select,
    Spin
} from "antd";
import { settingsChangedEvent, useSettings } from "../settings/SettingsProvider";
import { ResearchStudyPanel, type ResearchStudyActions } from "./ResearchStudyPanel";
import {
    ChatRequestError,
    commandSchema,
    connect,
    connectionSchema,
    conversationSchema,
    modelsSchema,
    proposalSchema,
    registrationSchema,
    request,
    savedAccess,
    sessionSchema,
    sessionsSchema,
    studySchema,
    studyContextSchema,
    type Access,
    type Chat,
    type Conversation,
    type Model,
    type Proposal,
    type Study
} from "./api";
import { HistoricalStudyCard } from "./HistoricalStudyCard";
import "./factorChat.css";
const currentKey = "onlyalpha.agent.chat.selected";
const pendingKey = "onlyalpha.agent.chat.pending";
const linksKey = "onlyalpha.agent.chat.proposals";
const studyLinksKey = "onlyalpha.agent.chat.studies";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
const grantInput = z.strictObject({
    schema_version: z.literal(1),
    grant_id: z.uuid(),
    service_subject: z.string(),
    credential_sha256: sha,
    proposal_limit: z.number().int(),
    expires_at: z.string()
});
const studyGrantInput = z.strictObject({
    schema_version: z.literal(1),
    factor_proposal_fingerprint: sha,
    grant_id: z.uuid(),
    proposal_limit: z.literal(10)
});
const studyMessage = z.strictObject({
    resource: z.uuid(),
    command: z.uuid(),
    binding: sha,
    body: z.strictObject({
        expected: sha.nullable(),
        text: z.literal("请建议当前因子的研究条件"),
        topic: z.literal("STUDY"),
        factor_proposal_fingerprint: sha
    })
});
const pendingFields = {
    resource: z.uuid(),
    command: z.uuid(),
    fingerprint: sha.optional(),
    binding: sha.optional()
};
const pendingSchema = z.discriminatedUnion("kind", [
    z.strictObject({
        ...pendingFields,
        kind: z.literal("continue"),
        body: z.strictObject({
            model_revision: sha,
            model_call_limit: z.number().int().positive(),
            continuation: z.strictObject({
                parent_session: z.uuid(),
                parent_head: sha,
                backend_command: z.uuid()
            })
        }),
        authorization: z.strictObject({
            schema_version: z.literal(1),
            factor_proposal_fingerprint: sha,
            session_id: z.uuid(),
            workflow_fingerprint: sha,
            model_revision: sha,
            source_session_id: z.uuid(),
            source_workflow_fingerprint: sha,
            source_continuation_command_id: z.uuid().optional()
        })
    }),
    z.strictObject({ ...pendingFields, kind: z.literal("grant"), body: grantInput }),
    z.strictObject({
        ...pendingFields,
        kind: z.literal("study-grant"),
        body: studyGrantInput,
        message: studyMessage
    }),
    z.strictObject({
        ...pendingFields,
        kind: z.enum(["create", "message", "stage", "confirm", "withdraw", "study-withdraw"])
    })
]);
type Pending = z.infer<typeof pendingSchema>;
const backendKinds = ["confirm", "withdraw", "grant", "study-grant", "study-withdraw"];
const linkSchema = z.record(z.string(), z.strictObject({ fingerprint: sha, head: sha }));
function pendingValue(): Pending | null {
    try {
        migrateModelSave();
        return pendingSchema.parse(JSON.parse(sessionStorage.getItem(pendingKey) ?? "null"));
    } catch {
        return null;
    }
}
function links(key = linksKey) {
    try {
        return linkSchema.parse(JSON.parse(localStorage.getItem(key) ?? "{}"));
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
const continuationProof = z.strictObject({
    schema_version: z.literal(1),
    command_id: z.uuid(),
    operation_fingerprint: sha,
    snapshot: z.looseObject({
        actor: z.literal("HUMAN"),
        kind: z.literal("CONTINUE_FACTOR_STUDY"),
        request: z.looseObject({
            session_id: z.uuid(),
            factor_proposal_fingerprint: sha,
            workflow_fingerprint: sha,
            model_revision: sha,
            source_session_id: z.uuid()
        })
    })
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
    AGENT_COMMAND_ABANDONED: "此操作已明确放弃，不会迟到执行。",
    AGENT_STUDY_CONTEXT_UNAVAILABLE:
        "研究建议的权限或数据源上下文不可用，未消耗新的模型调用。请核对登记许可和数据源设置。",
    AGENT_FACTOR_REFERENCE_CONFLICT: "当前因子已经变化，请重新载入并确认因子。",
    AGENT_BACKEND_OUTCOME_UNKNOWN: "原提案登记结果未知，当前对话只读；请核对原操作。",
    FACTOR_STUDY_PROPOSAL_STALE: "研究方案已被更新，请重新载入后核对。",
    FACTOR_STUDY_PROPOSAL_ALREADY_WITHDRAWN: "研究方案已撤回，请继续讨论新条件。",
    FACTOR_STUDY_GRANT_REQUIRED: "请先明确允许助手登记本因子的研究条件建议。",
    FACTOR_STUDY_GRANT_CONFLICT: "研究建议许可已存在，请重新载入实际许可后继续。"
};
const readable = (e: unknown) => {
    const s = e instanceof Error ? e.message : String(e);
    return (
        messages[s] ??
        (/^[A-Z][A-Z0-9_]+$/.test(s) || !/[\u4e00-\u9fff]/.test(s)
            ? "操作未能完成，请先核对原操作的结果。"
            : s)
    );
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
    const { openSettings } = useSettings();
    const [conversation, setConversation] = useState<Conversation | null>(null);
    const [conversationError, setConversationError] = useState("");
    const [search, setSearch] = useState("");
    const [historyOpen, setHistoryOpen] = useState(false);
    const [grantOpen, setGrantOpen] = useState(false);
    const [following, setFollowing] = useState(true);
    const viewport = useRef<HTMLDivElement>(null);
    const composing = useRef(false);
    const [text, setText] = useState("");
    const [budget, setBudget] = useState(20);
    const [pending, setPending] = useState<Pending | null>(pendingValue);
    const [proposal, setProposal] = useState<Proposal | null>(null);
    const [study, setStudy] = useState<Study | null>(null);
    const [editingFactor, setEditingFactor] = useState(false);
    const [connection, setConnection] = useState<z.infer<typeof connectionSchema> | null>(null);
    const [agentReady, setAgentReady] = useState(false);
    const [backendError, setBackendError] = useState("");
    const [agentError, setAgentError] = useState("");
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const generation = useRef(0);
    const researchAction = useRef<ResearchStudyActions>(null);
    const [researchFeedback, setResearchFeedback] = useState("");
    const topic = editingFactor ? "FACTOR" : (chat?.topic ?? "FACTOR");
    const approvalText = topic === "FACTOR" && ["确认因子", "确认当前因子"].includes(text.trim());
    const researchApprovalText = !editingFactor && text.trim() === "确认本次研究";
    const dirty = text.trim() !== "" && !approvalText && !researchApprovalText;
    function remember(input: Pending | null) {
        const p =
            input !== null && !backendKinds.includes(input.kind)
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
                if (current === null) {
                    setConversation(null);
                    setConversationError("");
                } else {
                    try {
                        const detail = await request(
                            `/api/v1/agent/sessions/${current.id}/conversation`,
                            conversationSchema,
                            undefined,
                            undefined,
                            auth
                        );
                        if (tag !== generation.current) return;
                        if (
                            detail.id !== current.id ||
                            detail.head !== current.head ||
                            detail.model_revision !== current.model_revision
                        )
                            throw new Error("对话已发生变化，请重新载入后继续。");
                        setConversation(detail);
                        setConversationError("");
                    } catch {
                        if (tag === generation.current) {
                            setConversation(null);
                            setConversationError(
                                "完整对话暂时无法载入；已保存的研究内容仍可查看。请重新载入。"
                            );
                        }
                    }
                }
            } catch (e) {
                if (tag === generation.current) {
                    setAgentReady(false);
                    setAgentError("研究助手暂不可用：" + readable(e));
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
                    setBackendError("研究服务暂不可用：" + readable(e));
                }
            }
        })();
        await Promise.all([a, b]);
        if (tag !== generation.current) return;
        const owned = current as Chat | null;
        const factorRef = owned === null ? links()[selected] : owned.factor_reference;
        const studyRef = owned === null ? links(studyLinksKey)[selected] : owned.study_reference;
        if (factorRef?.fingerprint) {
            try {
                const [view, authorization] = await Promise.all([
                    request(`/api/v2/factor-proposals/${factorRef.fingerprint}`, proposalSchema),
                    owned?.continuation
                        ? request(
                              `/api/v2/factor-study-continuations/${owned.continuation.backend_command}`,
                              continuationProof
                          )
                        : Promise.resolve(null)
                ]);
                if (tag !== generation.current) return;
                if (
                    owned?.continuation &&
                    (authorization?.command_id !== owned.continuation.backend_command ||
                        authorization.snapshot.request.session_id !== selected ||
                        authorization.snapshot.request.factor_proposal_fingerprint !==
                            factorRef.fingerprint ||
                        authorization.snapshot.request.workflow_fingerprint !== owned.workflow ||
                        authorization.snapshot.request.model_revision !== owned.model_revision ||
                        authorization.snapshot.request.source_session_id !==
                            owned.continuation.parent_session)
                )
                    throw new Error("暂时无法验证原研究的接续授权，请刷新后重试。");
                if (
                    view.fingerprint !== factorRef.fingerprint ||
                    (authorization === null && view.snapshot.origin.session_id !== selected) ||
                    view.snapshot.origin.event_fingerprint !== factorRef.head
                )
                    throw new Error("登记提案与原对话不匹配，请核对原操作");
                setProposal(view);
                localStorage.setItem(
                    linksKey,
                    JSON.stringify({
                        ...links(),
                        [selected]: { fingerprint: factorRef.fingerprint, head: factorRef.head }
                    })
                );
            } catch (e) {
                if (tag === generation.current) {
                    setProposal(null);
                    setBackendError("研究服务暂不可用：因子提案无法核对，" + readable(e));
                }
            }
        } else setProposal(null);
        if (studyRef?.fingerprint) {
            try {
                const view = await request(
                    `/api/v2/factor-studies/${studyRef.fingerprint}`,
                    studySchema
                );
                if (tag !== generation.current) return;
                if (
                    view.fingerprint !== studyRef.fingerprint ||
                    view.snapshot.origin.session_id !== selected ||
                    view.snapshot.origin.event_fingerprint !== studyRef.head ||
                    view.snapshot.factor_proposal_fingerprint !== factorRef?.fingerprint
                )
                    throw new Error("研究方案与原因子/对话不匹配，请核对原操作");
                setStudy(view);
                localStorage.setItem(
                    studyLinksKey,
                    JSON.stringify({
                        ...links(studyLinksKey),
                        [selected]: { fingerprint: studyRef.fingerprint, head: studyRef.head }
                    })
                );
            } catch (e) {
                if (tag === generation.current) {
                    setStudy(null);
                    setBackendError("研究服务暂不可用：研究方案无法核对，" + readable(e));
                }
            }
        } else setStudy(null);
    }, []);
    useEffect(() => {
        const sequence = generation;
        void refresh();
        return () => {
            sequence.current++;
        };
    }, [refresh]);
    useEffect(() => {
        const update = () => {
            setPending(pendingValue());
            void refresh();
        };
        window.addEventListener(settingsChangedEvent, update);
        return () => {
            window.removeEventListener(settingsChangedEvent, update);
        };
    }, [refresh]);
    useEffect(() => {
        if (following && viewport.current !== null)
            viewport.current.scrollTop = viewport.current.scrollHeight;
    }, [conversation, busy, following]);
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
        const content = s.topic === "STUDY" ? s.study : s.candidate;
        const reference = s.topic === "STUDY" ? s.study_reference : s.factor_reference;
        if (s.head === null || content === null || s.status !== "READY") return;
        if (reference?.head === s.head && reference.fingerprint) return;
        const original = reference?.head === s.head;
        const p: Pending = {
            kind: "stage",
            resource: s.id,
            command: original ? reference.command : crypto.randomUUID()
        };
        remember(p);
        const r = await request(
            !original
                ? `/api/v1/agent/sessions/${s.id}/proposals`
                : `/api/v1/agent/sessions/${s.id}/proposals/${p.command}/resume`,
            registrationSchema,
            { expected: s.head },
            p.command,
            auth()
        );
        if (r.status === "ABANDONED") {
            remember(null);
            throw new Error("这版研究条件未保存，请修改后继续。");
        }
        if (r.status !== "REGISTERED" || r.receipt === null)
            throw new Error(
                r.status === "REJECTED"
                    ? "这版研究条件未保存，请选择“修改研究条件”继续。"
                    : "提案登记结果待核对，不会自动重发。"
            );
        remember(null);
    }
    async function create() {
        setEditingFactor(false);
        const id = crypto.randomUUID();
        const m = models.find((v) => v.id === selectedModel);
        if (m === undefined) throw new Error("请先配置模型");
        const p: Pending = { kind: "create", resource: id, command: crypto.randomUUID() };
        remember(p);
        localStorage.setItem(currentKey, id);
        const created = await request(
            `/api/v1/agent/sessions/${id}`,
            sessionSchema,
            { model_revision: m.revision, model_call_limit: budget },
            p.command,
            auth(),
            "PUT"
        );
        remember(null);
        await refresh();
        return created;
    }
    async function continueStudy(p: Extract<Pending, { kind: "continue" }>) {
        // Both operations retain their exact identities if either response is lost.
        const receipt = await request(
            "/api/v2/factor-study-continuations",
            operation,
            p.authorization,
            p.body.continuation.backend_command
        );
        if (
            receipt.command_id !== p.body.continuation.backend_command ||
            receipt.effect.continuation_command_id !== receipt.command_id
        )
            throw new Error("无法验证接续结果，请保留原操作后重试。");
        const created = await request(
            `/api/v1/agent/sessions/${p.resource}`,
            sessionSchema,
            p.body,
            p.command,
            auth(),
            "PUT"
        );
        if (
            created.id !== p.resource ||
            created.continuation?.backend_command !== receipt.command_id
        )
            throw new Error("无法验证接续对话，原记录已保留。");
        localStorage.setItem(currentKey, created.id);
        remember(null);
        setEditingFactor(false);
        setText("");
        await refresh();
    }
    async function modifyStudy() {
        const pending = pendingValue();
        if (pending?.kind === "continue") {
            await continueStudy(pending);
            return;
        }
        if (chat?.successor) {
            selectChat(chat.successor);
            return;
        }
        if (chat?.topic !== "STUDY") return;
        const original =
            pending?.kind === "stage" && pending.resource === chat.id
                ? pending.command
                : chat.study_reference?.fingerprint === null && !chat.study_reference.abandoned
                  ? chat.study_reference.command
                  : null;
        if (original !== null) {
            const result = await request(
                `/api/v1/agent/sessions/${chat.id}/proposals/${original}/resolve`,
                registrationSchema,
                {},
                undefined,
                auth()
            );
            if (!["REGISTERED", "ABANDONED"].includes(result.status) || result.receipt === null)
                throw new Error("暂时无法修改条件，请稍后重试。原研究和报告会保留。");
            remember(null);
        }
        const current = await request(
            `/api/v1/agent/sessions/${chat.id}`,
            sessionSchema,
            undefined,
            undefined,
            auth()
        );
        if (current.status !== "WORKFLOW_UNAVAILABLE") {
            setText("");
            await refresh();
            return;
        }
        const remaining = current.model_call_limit - current.consumed;
        const factor = current.factor_reference?.fingerprint;
        if (!factor || !current.head || !current.current_workflow || remaining < 1)
            throw new Error("当前研究暂时无法接续，已保存内容仍可查看。");
        const id = crypto.randomUUID();
        const backendCommand = crypto.randomUUID();
        const p: Extract<Pending, { kind: "continue" }> = {
            kind: "continue",
            resource: id,
            command: crypto.randomUUID(),
            body: {
                model_revision: current.model_revision,
                model_call_limit: remaining,
                continuation: {
                    parent_session: current.id,
                    parent_head: current.head,
                    backend_command: backendCommand
                }
            },
            authorization: {
                schema_version: 1,
                factor_proposal_fingerprint: factor,
                session_id: id,
                workflow_fingerprint: current.current_workflow,
                model_revision: current.model_revision,
                source_session_id: current.id,
                source_workflow_fingerprint: current.workflow,
                ...(current.continuation
                    ? { source_continuation_command_id: current.continuation.backend_command }
                    : {})
            }
        };
        remember(p);
        await continueStudy(p);
    }
    async function backendSubmission(p: Pending) {
        if (!backendKinds.includes(p.kind)) throw new Error("原操作类型不可提交");
        let path: string;
        let body: object;
        if (p.kind === "grant") {
            path = "/api/v2/factor-proposal-grants";
            body = p.body;
        } else if (p.kind === "study-grant") {
            path = "/api/v2/factor-study-grants";
            body = p.body;
        } else if (p.kind === "study-withdraw") {
            if (p.fingerprint === undefined) throw new Error("原研究方案身份不可用");
            path = `/api/v2/factor-studies/${p.fingerprint}/withdrawal`;
            body = { schema_version: 1, study_proposal_fingerprint: p.fingerprint };
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
                    "FACTOR_PROPOSAL_INVALID",
                    "FACTOR_STUDY_PROPOSAL_STALE",
                    "FACTOR_STUDY_PROPOSAL_ALREADY_WITHDRAWN",
                    "FACTOR_STUDY_GRANT_CONFLICT",
                    "FACTOR_STUDY_PROPOSAL_INVALID"
                ].includes(e.message)
            )
                remember(null);
            throw e;
        }
        if (
            receipt.command_id !== p.command ||
            (p.kind === "study-grant"
                ? receipt.effect.study_grant_id !== p.resource
                : p.kind === "grant"
                  ? receipt.effect.grant_id !== p.resource
                  : receipt.effect.proposal_fingerprint !== p.fingerprint)
        )
            throw new Error("原操作回执身份不匹配");
    }
    async function repeatBackend(p: Pending) {
        await backendSubmission(p);
        if (p.kind === "study-grant") {
            await sendStudyMessage(p.message);
            return;
        }
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
    async function sendStudyMessage(message: z.infer<typeof studyMessage>) {
        if (auth().binding !== message.binding)
            throw new Error("原助手连接绑定不可用，请恢复原连接后核对。");
        remember({
            kind: "message",
            resource: message.resource,
            command: message.command,
            binding: message.binding
        });
        const result = await request(
            `/api/v1/agent/sessions/${message.resource}/messages`,
            sessionSchema,
            message.body,
            message.command,
            auth()
        );
        remember(null);
        setEditingFactor(false);
        setText("");
        await stage(result);
        await refresh();
    }
    async function beginStudy() {
        if (
            chat === null ||
            proposal?.confirmation == null ||
            !proposal.is_current ||
            proposal.withdrawn
        )
            throw new Error("请先确认当前因子");
        await withdrawStudy(chat.id);
        const context = await request(
            `/api/v2/factor-study-context/${proposal.fingerprint}`,
            studyContextSchema
        );
        if (
            context.factor_proposal_fingerprint !== proposal.fingerprint ||
            context.factor.draft_fingerprint !== proposal.snapshot.preview.draft_fingerprint
        )
            throw new Error("研究上下文与已确认因子不匹配");
        if (["EXPIRED", "REVOKED"].includes(context.supported_profile.study_grant_state))
            throw new Error("原助手登记许可已到期或撤销，请核对服务连接后重新授权。");
        const message: z.infer<typeof studyMessage> = {
            resource: chat.id,
            command: crypto.randomUUID(),
            binding: auth().binding,
            body: {
                expected: chat.head,
                text: "请建议当前因子的研究条件",
                topic: "STUDY",
                factor_proposal_fingerprint: proposal.fingerprint
            }
        };
        if (context.supported_profile.study_grant_id !== null) {
            if (context.supported_profile.remaining_proposals === 0)
                throw new Error("本因子的研究条件建议额度已用完，请核对研究历史。");
            await sendStudyMessage(message);
            return;
        }
        const id = crypto.randomUUID();
        const p: Pending = {
            kind: "study-grant",
            resource: id,
            command: crypto.randomUUID(),
            message,
            body: {
                schema_version: 1,
                factor_proposal_fingerprint: proposal.fingerprint,
                grant_id: id,
                proposal_limit: 10
            }
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
        setStudy(null);
        await refresh();
    }
    async function send() {
        if (researchApprovalText) {
            setText("");
            if (researchAction.current === null) {
                setError("请先登记研究条件并准备研究环境。");
                return;
            }
            await researchAction.current.confirmResearch();
            return;
        }
        if (approvalText) {
            await confirm();
            return;
        }
        const s = chat ?? (await create());
        generation.current++;
        await withdrawStudy(s.id);
        if (topic === "FACTOR" && proposal !== null && proposal.is_current && !proposal.withdrawn) {
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
        if (topic === "FACTOR") setProposal(null);
        const p: Pending = { kind: "message", resource: s.id, command: crypto.randomUUID() };
        remember(p);
        const result = await request(
            `/api/v1/agent/sessions/${s.id}/messages`,
            sessionSchema,
            topic === "STUDY"
                ? {
                      expected: s.head,
                      text,
                      topic: "STUDY",
                      factor_proposal_fingerprint: proposal?.fingerprint
                  }
                : { expected: s.head, text },
            p.command,
            auth()
        );
        remember(null);
        setEditingFactor(false);
        setText("");
        await stage(result);
        await refresh();
    }
    async function withdrawStudy(sid: string) {
        if (study === null || !study.is_current || study.withdrawn) return;
        const p: Pending = {
            kind: "study-withdraw",
            resource: sid,
            command: crypto.randomUUID(),
            fingerprint: study.fingerprint
        };
        remember(p);
        await backendSubmission(p);
        remember(null);
        setStudy(null);
    }
    async function recover() {
        let p = pendingValue();
        if (p?.kind === "continue") {
            await continueStudy(p);
            return;
        }
        if (p?.binding !== undefined && p.binding !== auth().binding)
            throw new Error("原助手连接绑定不可用，请恢复原连接后核对；不会切换目标或重发。");
        const registration =
            chat?.factor_reference?.fingerprint === null
                ? chat.factor_reference
                : chat?.study_reference?.fingerprint === null
                  ? chat.study_reference
                  : null;
        if (p === null && registration !== null && chat !== null) {
            p = { kind: "stage", resource: chat.id, command: registration.command };
            remember(p);
        }
        if (p === null) {
            await refresh();
            return;
        }
        if (backendKinds.includes(p.kind)) {
            const receipt = await request(
                `/api/v2/${p.kind.startsWith("study-") ? "factor-studies" : "factor-proposals"}/commands/${p.command}`,
                operation
            );
            if (
                receipt.command_id !== p.command ||
                (p.kind === "study-grant"
                    ? receipt.effect.study_grant_id !== p.resource
                    : p.kind === "grant"
                      ? receipt.effect.grant_id !== p.resource
                      : receipt.effect.proposal_fingerprint !== p.fingerprint)
            )
                throw new Error("原操作回执身份不匹配");
            if (p.kind === "study-grant") {
                await sendStudyMessage(p.message);
                return;
            }
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
        if (p === null || backendKinds.includes(p.kind)) return;
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
        if (o.status !== "ABANDONED")
            throw new Error("尚未确认放弃结果，原操作仍待核对；不会重发或创建新身份。");
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
    const pendingRegistration =
        chat?.factor_reference?.fingerprint === null && !chat.factor_reference.abandoned
            ? chat.factor_reference
            : chat?.study_reference?.fingerprint === null && !chat.study_reference.abandoned
              ? chat.study_reference
              : null;
    const registrationPending = pendingRegistration !== null;
    const studyRecovery =
        chat?.topic === "STUDY" &&
        (chat.successor != null ||
            registrationPending ||
            chat.status === "WORKFLOW_UNAVAILABLE" ||
            pending?.kind === "stage" ||
            pending?.kind === "continue");
    const blocked =
        chat?.successor != null ||
        chat?.status === "OUTCOME_UNKNOWN" ||
        chat?.status === "WORKFLOW_UNAVAILABLE" ||
        registrationPending;
    const preview = proposal?.snapshot.preview;
    const title = (item: Chat) =>
        typeof item.candidate?.name === "string"
            ? item.candidate.name
            : (item.messages.find((m) => m.role === "user")?.content.slice(0, 32) ?? "新研究");
    function selectChat(id: string) {
        generation.current++;
        localStorage.setItem(currentKey, id);
        setText("");
        setEditingFactor(false);
        setProposal(null);
        setStudy(null);
        setConversation(null);
        setFollowing(true);
        setHistoryOpen(false);
        void act(() => refresh());
    }
    function newChat() {
        generation.current++;
        localStorage.removeItem(currentKey);
        setChat(null);
        setConversation(null);
        setProposal(null);
        setStudy(null);
        setText("");
        setEditingFactor(false);
        setFollowing(true);
        setHistoryOpen(false);
    }
    const factorCard = (
        <Card size="small" className="factor-preview-card">
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
                            {dirty && topic === "FACTOR" ? "；正在编辑新想法，旧预览不可确认" : ""}
                        </p>
                        <Button
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
                        </Button>
                        {proposal.confirmation !== null &&
                            proposal.is_current &&
                            !proposal.withdrawn && (
                                <>
                                    <p>允许助手提出最多10次研究条件建议，不会开始研究。</p>
                                    <Button
                                        disabled={
                                            disabled ||
                                            blocked ||
                                            !agentReady ||
                                            dirty ||
                                            backendError !== ""
                                        }
                                        onClick={() => {
                                            void act(beginStudy);
                                        }}
                                    >
                                        讨论研究条件
                                    </Button>
                                    <Button
                                        disabled={disabled || blocked || !agentReady}
                                        onClick={() => {
                                            setEditingFactor(true);
                                            setText("");
                                        }}
                                    >
                                        修改因子
                                    </Button>
                                </>
                            )}
                    </>
                )}
            </section>
        </Card>
    );
    const studyCard =
        study === null ? null : (
            <Card size="small" className="factor-preview-card">
                <section aria-label="研究方案">
                    <h2>研究方案</h2>
                    <>
                        <h3>{preview?.name ?? "当前因子"} · 研究条件</h3>
                        <dl>
                            <dt>建议商品</dt>
                            <dd>
                                {study.snapshot.advice.source.instrument_id}
                                （准备时验证实际可用性）
                            </dd>
                            <dt>数据来源</dt>
                            <dd>详见下方研究环境的数据来源</dd>
                            <dt>K线周期</dt>
                            <dd>{study.snapshot.advice.timeframe_minutes} 分钟</dd>
                            <dt>预测期限</dt>
                            <dd>未来 {study.snapshot.advice.horizon_bars} 根K线</dd>
                            <dt>开发样本（UTC）</dt>
                            <dd>
                                {study.snapshot.advice.start_at} 至{" "}
                                {study.snapshot.advice.development_end_at}
                            </dd>
                            <dt>固定样本外区间（UTC）</dt>
                            <dd>
                                {study.snapshot.advice.development_end_at} 至{" "}
                                {study.snapshot.advice.end_at}
                            </dd>
                            <dt>保留样本（UTC）</dt>
                            <dd>
                                {study.snapshot.advice.protected_start_at} 至{" "}
                                {study.snapshot.advice.protected_end_at}（本次研究不读取）
                            </dd>
                            <dt>序列依赖修正</dt>
                            <dd>
                                期望区块长度 {study.snapshot.advice.expected_block_length}{" "}
                                根；重采样 {study.snapshot.advice.replicates} 次；置信水平{" "}
                                {study.snapshot.advice.confidence_bps / 100}%
                            </dd>
                        </dl>
                        <p>{study.snapshot.advice.rationale}</p>
                        <p role="status">
                            {study.withdrawn || !study.is_current
                                ? "研究方案已撤回或更新，请重新讨论条件。"
                                : "研究条件建议已登记；请准备并启用研究环境，再单独确认本次研究。"}
                            {dirty && topic === "STUDY"
                                ? "正在修改条件，当前方案不可用于新的确认。"
                                : ""}
                        </p>
                        <ResearchStudyPanel
                            key={study.fingerprint}
                            study={study}
                            actionRef={researchAction}
                            newWorkBlocked={
                                disabled ||
                                blocked ||
                                dirty ||
                                editingFactor ||
                                proposal?.confirmation == null ||
                                !proposal.is_current ||
                                proposal.withdrawn
                            }
                            onSystemFeedback={setResearchFeedback}
                        />
                        <details>
                            <summary>研究方案高级详情</summary>
                            <pre>{JSON.stringify(study.snapshot.advice, null, 2)}</pre>
                        </details>
                    </>{" "}
                </section>
            </Card>
        );
    const history = (
        <nav className="factor-history" aria-label="研究历史">
            <div className="factor-history-heading">
                <strong>研究历史</strong>
            </div>
            <Button block type="primary" disabled={disabled} onClick={newChat}>
                ＋ 新建研究
            </Button>
            <Input
                aria-label="搜索研究历史"
                placeholder="搜索研究历史"
                value={search}
                onChange={(e) => {
                    setSearch(e.target.value);
                }}
                allowClear
            />
            <Conversations
                activeKey={chat?.id ?? ""}
                items={items
                    .filter((item) =>
                        title(item).toLocaleLowerCase().includes(search.toLocaleLowerCase())
                    )
                    .map((item) => ({ key: item.id, label: title(item), disabled }))}
                onActiveChange={selectChat}
            />
            {items.length === 0 && <p className="factor-chat-muted">你的研究会保存在这里</p>}
        </nav>
    );
    const canSend =
        !disabled &&
        (!blocked || researchApprovalText) &&
        (agentReady || researchApprovalText) &&
        text.trim() !== "" &&
        (approvalText || researchApprovalText || chat !== null || selectedModel !== "") &&
        (approvalText || researchApprovalText || connection?.grant_state === "ACTIVE") &&
        (approvalText ||
            researchApprovalText ||
            chat === null ||
            chat.consumed < chat.model_call_limit) &&
        (topic !== "STUDY" ||
            (proposal?.confirmation != null && proposal.is_current && !proposal.withdrawn));
    const hasFactorTurn =
        conversation?.turns.some(
            (turn) =>
                turn.head === proposal?.snapshot.origin.event_fingerprint &&
                turn.factor_reference?.fingerprint === proposal.fingerprint
        ) ?? false;
    const hasStudyTurn =
        conversation?.turns.some(
            (turn) =>
                turn.head === study?.snapshot.origin.event_fingerprint &&
                turn.study_reference?.fingerprint === study.fingerprint
        ) ?? false;
    return (
        <section className="factor-chat-page" aria-label="聊天因子研究">
            <aside className="factor-history-desktop">{history}</aside>
            <Drawer
                title="研究历史"
                placement="left"
                open={historyOpen}
                onClose={() => {
                    setHistoryOpen(false);
                }}
                size={280}
                destroyOnHidden
            >
                {history}
            </Drawer>
            <main className="factor-chat-main">
                <header className="factor-chat-header">
                    <div className="factor-chat-title">
                        <Button
                            className="factor-history-toggle"
                            type="text"
                            aria-label="打开研究历史"
                            onClick={() => {
                                setHistoryOpen(true);
                            }}
                        >
                            ☰
                        </Button>
                        <h1>因子研究</h1>
                        <span>{chat === null ? "新研究" : title(chat)}</span>
                    </div>
                    <div className="factor-chat-header-actions">
                        <Popover
                            trigger="click"
                            getPopupContainer={(trigger) => trigger.parentElement ?? trigger}
                            content={
                                <div className="factor-recovery-actions">
                                    <Button disabled={busy} onClick={() => void act(recover)}>
                                        核对并重新载入
                                    </Button>
                                    <Button
                                        disabled={busy}
                                        onClick={() =>
                                            void act(async () => {
                                                const a = await connect();
                                                setAccess(a);
                                                await refresh(a);
                                            })
                                        }
                                    >
                                        重新连接助手
                                    </Button>
                                </div>
                            }
                        >
                            <Button type="text" aria-label="更多研究操作">
                                •••
                            </Button>
                        </Popover>
                    </div>
                </header>
                <div className="factor-chat-notices">
                    {agentError !== "" && (
                        <Alert
                            type="warning"
                            title="研究助手暂时无法连接。已保存的研究内容仍可查看。"
                            action={
                                <Button
                                    size="small"
                                    onClick={() =>
                                        void act(async () => {
                                            const a = await connect();
                                            setAccess(a);
                                            await refresh(a);
                                        })
                                    }
                                >
                                    重新连接
                                </Button>
                            }
                        />
                    )}
                    {backendError !== "" && (
                        <Alert type="warning" title="研究服务暂时不可用，确认和提交已暂停。" />
                    )}
                    {conversationError !== "" && (
                        <Alert
                            type="warning"
                            title={conversationError}
                            action={
                                <Button
                                    size="small"
                                    disabled={busy}
                                    onClick={() => void act(recover)}
                                >
                                    重新载入
                                </Button>
                            }
                        />
                    )}
                    {error !== "" && (
                        <Alert
                            role="alert"
                            type="error"
                            title={error}
                            closable={{
                                onClose: () => {
                                    setError("");
                                }
                            }}
                        />
                    )}
                    {pending !== null &&
                        !(
                            chat?.topic === "STUDY" && ["stage", "continue"].includes(pending.kind)
                        ) && (
                            <section className="factor-chat-pending" aria-label="待核对的操作">
                                <p role="status" id="factor-chat-pending-summary">
                                    上一次操作的结果尚未确认，请先查看原操作结果。
                                </p>
                                <Button
                                    size="small"
                                    disabled={busy}
                                    onClick={() => {
                                        void act(recover);
                                    }}
                                >
                                    核对原操作
                                </Button>
                                {!backendKinds.includes(pending.kind) && (
                                    <Button
                                        size="small"
                                        disabled={busy}
                                        onClick={() => void act(abandon)}
                                    >
                                        放弃未接受的操作
                                    </Button>
                                )}
                                {backendKinds.includes(pending.kind) && (
                                    <Button
                                        size="small"
                                        disabled={busy}
                                        onClick={() => void act(() => repeatBackend(pending))}
                                    >
                                        {pending.kind === "confirm"
                                            ? "再次提交同一确认"
                                            : pending.kind === "withdraw" ||
                                                pending.kind === "study-withdraw"
                                              ? "再次提交同一撤回"
                                              : "再次提交同一授权"}
                                    </Button>
                                )}
                                {pending.kind === "stage" && (
                                    <>
                                        <Button
                                            size="small"
                                            disabled={busy}
                                            onClick={() => void act(returnToHistory)}
                                        >
                                            保留记录，返回研究历史
                                        </Button>
                                        <details>
                                            <summary>原登记操作详情</summary>
                                            <code>{pending.command}</code>
                                        </details>
                                    </>
                                )}
                            </section>
                        )}
                    {chat !== null && studyRecovery && (
                        <Alert
                            type="warning"
                            title="可以修改研究条件后继续。已有研究和报告会保留。"
                            action={
                                <Button disabled={busy} onClick={() => void act(modifyStudy)}>
                                    {chat.successor ? "继续接续研究" : "修改研究条件"}
                                </Button>
                            }
                        />
                    )}
                    {chat?.continuation && (
                        <p className="factor-chat-muted">
                            已接续原研究，沿用原因子和模型。
                            <Button
                                type="link"
                                onClick={() => {
                                    if (chat.continuation)
                                        selectChat(chat.continuation.parent_session);
                                }}
                            >
                                查看先前讨论和报告
                            </Button>
                        </p>
                    )}
                    {connection?.grant_state === "ABSENT" && (
                        <Alert
                            type="info"
                            title="启用助手后，即可讨论因子想法。"
                            action={
                                <Button
                                    size="small"
                                    disabled={disabled}
                                    onClick={() => {
                                        setGrantOpen(true);
                                    }}
                                >
                                    启用助手
                                </Button>
                            }
                        />
                    )}
                    {connection !== null &&
                        ["EXPIRED", "REVOKED"].includes(connection.grant_state) && (
                            <Alert
                                type="warning"
                                title="助手的使用许可已到期或撤销，请更新连接设置后重新授权。研究记录已保留。"
                            />
                        )}
                </div>
                <div
                    className="factor-chat-transcript"
                    ref={viewport}
                    onScroll={() => {
                        const node = viewport.current;
                        if (node)
                            setFollowing(
                                node.scrollHeight - node.scrollTop - node.clientHeight < 48
                            );
                    }}
                >
                    <div className="factor-chat-reading">
                        {chat === null && (
                            <div className="factor-chat-welcome">
                                <div className="factor-chat-welcome-symbol">α</div>
                                <h2>从一个因子想法开始</h2>
                                <p>描述你观察到的市场现象，一起梳理它的计算方法。</p>
                                {models.length === 0 && agentReady && (
                                    <Button
                                        type="primary"
                                        onClick={() => {
                                            openSettings("models");
                                        }}
                                    >
                                        添加模型
                                    </Button>
                                )}
                            </div>
                        )}
                        {conversation?.turns.map((turn, index) => (
                            <div className="factor-chat-turn" key={turn.head}>
                                <Bubble
                                    placement="end"
                                    content={turn.user}
                                    variant="filled"
                                    className="factor-user-message"
                                />
                                <article aria-label={`助手回复 ${String(index + 1)}`}>
                                    {turn.assistant !== null && (
                                        <Bubble
                                            content={messages[turn.assistant] ?? turn.assistant}
                                            variant="borderless"
                                        />
                                    )}
                                    {turn.status !== "READY" && (
                                        <Alert
                                            type="warning"
                                            title={
                                                turn.status === "OUTCOME_UNKNOWN"
                                                    ? "模型连接中断，未收到完整回复。系统不会自动重复请求；已保存的内容仍可查看，可新建研究继续。"
                                                    : "这次回复未能完成。请调整想法后继续。"
                                            }
                                        />
                                    )}
                                    {turn.head === proposal?.snapshot.origin.event_fingerprint &&
                                    turn.factor_reference?.fingerprint === proposal.fingerprint
                                        ? factorCard
                                        : turn.candidate !== null && (
                                              <Card
                                                  size="small"
                                                  className="factor-preview-card factor-preview-history"
                                              >
                                                  <section aria-label="历史因子建议">
                                                      <span className="factor-chat-muted">
                                                          {turn.head === chat?.head
                                                              ? "待核对的因子建议"
                                                              : "历史建议"}
                                                      </span>
                                                      <h3>
                                                          {typeof turn.candidate.name === "string"
                                                              ? turn.candidate.name
                                                              : "因子建议"}
                                                      </h3>
                                                      <p>
                                                          {typeof turn.candidate.purpose ===
                                                          "string"
                                                              ? turn.candidate.purpose
                                                              : ""}
                                                      </p>
                                                      <p>
                                                          {typeof turn.candidate.hypothesis ===
                                                          "string"
                                                              ? turn.candidate.hypothesis
                                                              : ""}
                                                      </p>
                                                      <details>
                                                          <summary>当时的计算内容</summary>
                                                          <pre>
                                                              {JSON.stringify(
                                                                  turn.candidate.expression,
                                                                  null,
                                                                  2
                                                              )}
                                                          </pre>
                                                      </details>
                                                  </section>
                                              </Card>
                                          )}
                                    {turn.head === study?.snapshot.origin.event_fingerprint &&
                                    turn.study_reference?.fingerprint === study.fingerprint
                                        ? studyCard
                                        : turn.study !== null && (
                                              <HistoricalStudyCard
                                                  sessionId={conversation.id}
                                                  head={turn.head}
                                                  reference={turn.study_reference}
                                                  advice={turn.study}
                                              />
                                          )}
                                </article>
                            </div>
                        ))}
                        {conversation === null &&
                            chat?.messages.map((message, index) => (
                                <Bubble
                                    key={index}
                                    placement={message.role === "user" ? "end" : "start"}
                                    variant={message.role === "user" ? "filled" : "borderless"}
                                    content={messages[message.content] ?? message.content}
                                />
                            ))}
                        {proposal !== null && !hasFactorTurn && (
                            <div className="factor-chat-saved">
                                <p className="factor-chat-muted">已保存的因子</p>
                                {factorCard}
                            </div>
                        )}
                        {study !== null && !hasStudyTurn && (
                            <div className="factor-chat-saved">{studyCard}</div>
                        )}
                        {busy && (
                            <div role="status" className="factor-chat-working">
                                <Spin size="small" /> 正在处理…
                            </div>
                        )}
                        {researchFeedback !== "" && <p role="status">{researchFeedback}</p>}
                        {blocked &&
                            !studyRecovery &&
                            (registrationPending ||
                                chat?.status === "WORKFLOW_UNAVAILABLE" ||
                                !conversation?.turns.some(
                                    (turn) =>
                                        turn.head === chat?.head &&
                                        turn.status === "OUTCOME_UNKNOWN"
                                )) && (
                                <Alert
                                    type="warning"
                                    title={
                                        chat?.status === "WORKFLOW_UNAVAILABLE"
                                            ? "这项研究使用的助手版本暂不可用，记录已保留。"
                                            : registrationPending
                                              ? "研究内容的保存结果尚未确认，请先核对原操作。"
                                              : "模型连接中断，未收到完整回复。系统不会自动重复请求；已保存的内容仍可查看，可新建研究继续。"
                                    }
                                />
                            )}
                        {registrationPending && pending === null && (
                            <div className="factor-recovery-actions">
                                <Button disabled={busy} onClick={() => void act(returnToHistory)}>
                                    保留记录，返回研究历史
                                </Button>
                                <details>
                                    <summary>原登记操作详情</summary>
                                    <code>{pendingRegistration.command}</code>
                                </details>
                            </div>
                        )}
                        {chat?.status === "READY" &&
                            (chat.topic === "STUDY"
                                ? chat.study !== null
                                : chat.candidate !== null) &&
                            (chat.topic === "STUDY"
                                ? chat.study_reference?.head
                                : chat.factor_reference?.head) !== chat.head &&
                            pending === null && (
                                <Button
                                    disabled={busy || connection?.grant_state !== "ACTIVE"}
                                    onClick={() =>
                                        void act(async () => {
                                            await stage(chat);
                                            await refresh();
                                        })
                                    }
                                >
                                    {chat.topic === "STUDY"
                                        ? "保存当前研究建议"
                                        : "保存当前因子建议"}
                                </Button>
                            )}
                    </div>
                </div>
                {!following && (
                    <Button
                        className="factor-jump-latest"
                        size="small"
                        onClick={() => {
                            setFollowing(true);
                        }}
                    >
                        查看最新回复 ↓
                    </Button>
                )}
                <div className="factor-chat-composer">
                    <div
                        className="factor-chat-composer-inner"
                        onCompositionStartCapture={() => {
                            composing.current = true;
                        }}
                        onCompositionEndCapture={() => {
                            composing.current = false;
                        }}
                    >
                        <Sender
                            value={text}
                            onChange={setText}
                            placeholder="描述你的因子想法，或继续讨论研究条件…"
                            aria-label="告诉助手你的想法"
                            autoSize={{ minRows: 2, maxRows: 7 }}
                            disabled={disabled || blocked}
                            onKeyDown={(event) => {
                                if (composing.current || event.nativeEvent.isComposing)
                                    return false;
                            }}
                            onSubmit={() => {
                                if (canSend && !composing.current) void act(send);
                            }}
                            suffix={(_node, { components: { SendButton } }) => (
                                <SendButton aria-label="发送" disabled={!canSend} loading={busy} />
                            )}
                            footer={
                                <div className="factor-composer-footer">
                                    <Select
                                        aria-label={
                                            chat === null ? "新对话的模型" : "当前研究的模型"
                                        }
                                        placeholder="选择模型"
                                        size="small"
                                        variant="borderless"
                                        disabled={chat !== null || disabled}
                                        value={
                                            chat !== null
                                                ? chat.model_revision
                                                : selectedModel || null
                                        }
                                        onChange={(value: string) => {
                                            setSelectedModel(value);
                                        }}
                                        options={
                                            chat !== null
                                                ? [
                                                      {
                                                          value: chat.model_revision,
                                                          label:
                                                              conversation?.model.name ??
                                                              "原研究模型"
                                                      }
                                                  ]
                                                : models.map((model) => ({
                                                      value: model.id,
                                                      label: model.name
                                                  }))
                                        }
                                    />
                                    <div className="factor-composer-options">
                                        {chat === null ? (
                                            <Popover
                                                trigger="click"
                                                content={
                                                    <label>
                                                        最多调用模型的次数
                                                        <InputNumber
                                                            aria-label="新对话最多模型调用次数"
                                                            min={1}
                                                            max={100}
                                                            value={budget}
                                                            onChange={(value) => {
                                                                setBudget(value ?? 20);
                                                            }}
                                                        />
                                                    </label>
                                                }
                                            >
                                                <Button type="text" size="small">
                                                    研究选项
                                                </Button>
                                            </Popover>
                                        ) : (
                                            <span>
                                                {chat.consumed} / {chat.model_call_limit} 次
                                            </span>
                                        )}
                                        <Button
                                            type="text"
                                            size="small"
                                            onClick={() => {
                                                openSettings("models");
                                            }}
                                        >
                                            管理模型
                                        </Button>
                                    </div>
                                </div>
                            }
                        />
                        <p className="factor-composer-hint">
                            {chat === null
                                ? `本次研究最多调用模型 ${String(budget)} 次`
                                : topic === "STUDY"
                                  ? "讨论研究条件 · 准备完成后，单独确认本次研究"
                                  : "讨论因子 · 确认计算内容后再讨论研究条件"}
                        </p>
                    </div>
                </div>
            </main>
            <Modal
                title="启用研究助手"
                open={grantOpen}
                okText="允许并启用"
                cancelText="暂不启用"
                confirmLoading={busy}
                onCancel={() => {
                    setGrantOpen(false);
                }}
                onOk={() =>
                    void act(async () => {
                        await grant();
                        setGrantOpen(false);
                    })
                }
            >
                <p>允许助手保存最多100次因子建议，有效期24小时。</p>
                <p>这不会确认因子、开始研究或授权交易。每项研究仍由你单独确认。</p>
            </Modal>
        </section>
    );
}
