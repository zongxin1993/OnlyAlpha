// Read-only interpretation of exact backend data. Browser identifiers are only
// locators; the original Agent occurrence and model remain the source of history.
import { z } from "zod";
import {
    connect,
    request,
    modelsSchema,
    sessionSchema,
    sessionsSchema,
    conversationSchema,
    commandSchema,
    type Access,
    type Chat,
    type Model
} from "../factorChat/api";
import type { BacktestResult } from "./api";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
const pins = z.object({
    run_id: z.uuid(),
    strategy_fingerprint: sha,
    evidence_fingerprint: sha,
    result_fingerprint: sha,
    determinism_fingerprint: sha
});
const reference = pins.extend({ specification_fingerprint: sha });
const contextSchema = z.strictObject({
    schema_version: z.literal(1),
    run_id: z.uuid(),
    assertion: z.string().min(1).max(12288),
    expires_at: z.number().int()
});
const linkSchema = z.strictObject({
    schema_version: z.literal(1),
    binding: sha,
    session_id: z.uuid(),
    model_revision: sha,
    workflow: sha.optional(),
    create_command: z.uuid().optional(),
    message_command: z.uuid().optional(),
    reference: pins
});
type Pins = z.infer<typeof pins>;
type Link = z.infer<typeof linkSchema>;
export interface Interpretation {
    message: string;
    provenance?: {
        session_id: string;
        model_revision: string;
        head: string;
        model: { name: string; model_id: string; model_version: string };
        backtest_reference: z.infer<typeof reference>;
    };
}
const pending = () => new Error("结果尚未确认，请核对原操作。不会重复调用模型。");
const mismatch = () => new Error("解读记录与本次回测结果不一致，已停止显示。");
const key = (run: string, a: Access) => `onlyalpha.backtest.analysis.v1.${a.binding}.${run}`;
function remember(value: Link, a: Access) {
    sessionStorage.setItem(key(value.reference.run_id, a), JSON.stringify(value));
}
function saved(run: string, a: Access): Link | null {
    const raw = sessionStorage.getItem(key(run, a));
    if (raw === null) return null;
    const value = linkSchema.safeParse(JSON.parse(raw));
    if (!value.success || value.data.binding !== a.binding || value.data.reference.run_id !== run)
        throw mismatch();
    return value.data;
}
function same(a: Pins, b: Pins) {
    return Object.keys(pins.shape).every((k) => a[k as keyof Pins] === b[k as keyof Pins]);
}
function bound(chat: Chat, link: Link) {
    if (
        chat.id !== link.session_id ||
        chat.model_revision !== link.model_revision ||
        (link.workflow !== undefined && chat.workflow !== link.workflow)
    )
        throw mismatch();
}
async function locate(run: string, a: Access): Promise<Link | null> {
    const original = saved(run, a);
    if (original !== null) return original;
    const all = await request("/api/v1/agent/sessions", sessionsSchema, undefined, undefined, a);
    const matches = all.items.filter(
        (s) => s.topic === "BACKTEST_ANALYSIS" && s.backtest_reference?.run_id === run
    );
    if (matches.length === 0) return null;
    if (matches.length !== 1)
        throw new Error("存在多份原解读记录，请从研究历史选择需要查看的一份。");
    const chat = matches[0];
    if (chat?.backtest_reference === undefined) throw mismatch();
    const value: Link = {
        schema_version: 1,
        binding: a.binding,
        session_id: chat.id,
        model_revision: chat.model_revision,
        workflow: chat.workflow,
        reference: pins.parse(chat.backtest_reference)
    };
    remember(value, a);
    return value;
}
async function observe(link: Link, a: Access, expected: Pins): Promise<Interpretation> {
    if (!same(link.reference, expected)) throw mismatch();
    let event: string | undefined;
    for (const [kind, id] of [
        ["create", link.create_command],
        ["message", link.message_command]
    ] as const) {
        if (id === undefined) continue;
        const original = await request(
            `/api/v1/agent/commands/${id}`,
            commandSchema,
            undefined,
            undefined,
            a
        );
        if (original.status === "UNKNOWN") throw pending();
        if (original.status === "ABANDONED") throw new Error("原解读操作已放弃，记录仍然保留。");
        if (kind === "create") {
            if (
                original.outcome?.id !== link.session_id ||
                (link.workflow !== undefined && original.outcome.workflow !== link.workflow)
            )
                throw mismatch();
        } else {
            if (typeof original.outcome?.event !== "string") throw mismatch();
            event = original.outcome.event;
        }
    }
    const chat = await request(
        `/api/v1/agent/sessions/${link.session_id}`,
        sessionSchema,
        undefined,
        undefined,
        a
    );
    bound(chat, link);
    if (chat.status === "OUTCOME_UNKNOWN" || chat.head === null || chat.consumed === 0)
        throw pending();
    if (chat.status !== "READY" && chat.status !== "WORKFLOW_UNAVAILABLE")
        throw new Error("原模型没有返回可用解读，已保留该次记录。");
    if (
        (event !== undefined && event !== chat.head) ||
        chat.topic !== "BACKTEST_ANALYSIS" ||
        chat.backtest_reference === undefined ||
        !same(pins.parse(chat.backtest_reference), expected)
    )
        throw mismatch();
    const detail = await request(
        `/api/v1/agent/sessions/${chat.id}/conversation`,
        conversationSchema,
        undefined,
        undefined,
        a
    );
    if (
        detail.id !== chat.id ||
        detail.head !== chat.head ||
        detail.model_revision !== link.model_revision ||
        detail.turns.length !== 1
    )
        throw mismatch();
    const turn = detail.turns[0];
    if (
        turn?.head !== chat.head ||
        turn.topic !== "BACKTEST_ANALYSIS" ||
        turn.backtest_reference === undefined ||
        !same(pins.parse(turn.backtest_reference), expected)
    )
        throw mismatch();
    if (turn.status === "OUTCOME_UNKNOWN") throw pending();
    if (
        turn.status !== "READY" ||
        turn.assistant === null ||
        turn.assistant.length === 0 ||
        turn.candidate !== null ||
        turn.study !== null ||
        turn.factor_reference !== null ||
        turn.study_reference !== null
    )
        throw mismatch();
    return {
        message: turn.assistant,
        provenance: {
            session_id: chat.id,
            model_revision: link.model_revision,
            head: turn.head,
            model: detail.model,
            backtest_reference: turn.backtest_reference
        }
    };
}
// Parsing these fields is only an early display-binding check. The browser has
// no HMAC key and never treats this as signature verification or an execution grant.
function assertionPins(assertion: string, a: Access): Pins {
    try {
        const parts = assertion.split(".");
        if (parts.length !== 3 || assertion.length > 12288 || parts[1] === undefined)
            throw mismatch();
        const encoded = parts[1].replaceAll("-", "+").replaceAll("_", "/");
        const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
        const value = z
            .object({
                v: z.literal(1),
                iss: z.literal("onlyalpha-backend-backtest-analysis-v1"),
                aud: z.literal("onlyalpha-agent-backtest-analysis"),
                sub: z.literal(a.subject),
                kind: z.literal("BACKTEST_ANALYSIS_DATA"),
                data: reference
            })
            .parse(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)));
        return pins.parse(value.data);
    } catch {
        throw new Error("结果上下文不可用，请重新载入本次结果。");
    }
}
export async function loadModels(): Promise<{ items: Model[] }> {
    const access = await connect();
    return request("/api/v1/agent/models", modelsSchema, undefined, undefined, access);
}
export async function loadInterpretation(runId: string): Promise<Interpretation | null> {
    z.uuid().parse(runId);
    const access = await connect();
    const link = await locate(runId, access);
    if (link === null) return null;
    const actual = await request(`/api/v2/backtest/runs/${runId}/result`, pins);
    return observe(link, access, actual);
}
const running = new Map<string, { revision: string; promise: Promise<Interpretation> }>();
export function interpretResult(
    result: BacktestResult,
    modelRevision: string
): Promise<Interpretation> {
    const active = running.get(result.run_id);
    if (active !== undefined)
        return active.revision === modelRevision
            ? active.promise
            : Promise.reject(new Error("本次解读已绑定原模型，请先核对原操作。"));
    const promise = interpret(result, modelRevision).finally(() => running.delete(result.run_id));
    running.set(result.run_id, { revision: modelRevision, promise });
    return promise;
}
async function interpret(result: BacktestResult, modelRevision: string): Promise<Interpretation> {
    const expected = pins.parse(result);
    sha.parse(modelRevision);
    if (result.state !== "COMPLETED") throw new Error("请等待回测完成并取得完整结果后再解读。");
    const access = await connect();
    const original = await locate(result.run_id, access);
    if (original !== null) {
        if (original.model_revision !== modelRevision)
            throw new Error("已有解读绑定原模型，请查看原记录。");
        return observe(original, access, expected);
    }
    const context = await request(
        `/api/v2/backtest/runs/${result.run_id}/analysis-context`,
        contextSchema,
        {}
    );
    if (
        context.run_id !== result.run_id ||
        !same(assertionPins(context.assertion, access), expected)
    )
        throw mismatch();
    // Recheck the auxiliary locator after reads so a concurrent explicit action
    // cannot create a second local occurrence while the first is in flight.
    const concurrent = saved(result.run_id, access);
    if (concurrent !== null) return observe(concurrent, access, expected);
    const link: Link = {
        schema_version: 1,
        binding: access.binding,
        session_id: crypto.randomUUID(),
        model_revision: modelRevision,
        create_command: crypto.randomUUID(),
        message_command: crypto.randomUUID(),
        reference: expected
    };
    remember(link, access);
    try {
        const chat = await request(
            `/api/v1/agent/sessions/${link.session_id}`,
            sessionSchema,
            { model_revision: modelRevision, model_call_limit: 1 },
            link.create_command,
            access,
            "PUT"
        );
        bound(chat, link);
        if (
            chat.current_workflow === undefined ||
            chat.workflow !== chat.current_workflow ||
            chat.status !== "READY" ||
            chat.head !== null ||
            chat.consumed !== 0
        )
            throw new Error("原解读使用的流程暂不可用，已保留原记录。");
        link.workflow = chat.workflow;
        remember(link, access);
        await request(
            `/api/v1/agent/sessions/${chat.id}/messages`,
            sessionSchema,
            {
                expected: chat.head,
                text: "请解读本次回测的收益、费用、交易与短样本局限。仅作结果分析，不提出策略或执行操作。",
                topic: "BACKTEST_ANALYSIS",
                backtest_run_id: result.run_id,
                analysis_assertion: context.assertion
            },
            link.message_command,
            access
        );
    } catch {
        throw pending();
    }
    return observe(link, access, expected);
}
