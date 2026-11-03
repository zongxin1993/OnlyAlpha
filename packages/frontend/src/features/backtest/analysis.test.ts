// Technical client recovery with controlled service responses, not real model/UI acceptance.
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import type { z } from "zod";
import type * as FactorChatApi from "../factorChat/api";
import { connect, request, type Access } from "../factorChat/api";
import { loadModels, interpretResult, loadInterpretation } from "./analysis";
import type { BacktestResult } from "./api";
vi.mock("../factorChat/api", async (original) => ({
    ...(await original<typeof FactorChatApi>()),
    connect: vi.fn(),
    request: vi.fn()
}));
const run = "00000000-0000-4000-8000-000000009301";
const ownerModel = "00000000-0000-4000-8000-000000009302";
const revision = "a".repeat(64),
    workflow = "b".repeat(64);
const reference = {
    run_id: run,
    specification_fingerprint: "c".repeat(64),
    strategy_fingerprint: "d".repeat(64),
    evidence_fingerprint: "e".repeat(64),
    result_fingerprint: "f".repeat(64),
    determinism_fingerprint: "1".repeat(64)
};
const access: Access = {
    schema_version: 1,
    token: "agent-browser-access",
    expires_at: 4000000000,
    subject: "owner",
    agent_url: "https://agent.example/",
    binding: "2".repeat(64)
};
const model = {
    id: ownerModel,
    owner: "owner",
    name: "已配置模型",
    base_url: "https://model.example/v1",
    model_id: "configured",
    model_version: "recorded-v1",
    credential_generation: "00000000-0000-4000-8000-000000009303",
    parent: null,
    revision
};
const result = {
    schema_version: 1,
    run_id: run,
    strategy_fingerprint: reference.strategy_fingerprint,
    evidence_fingerprint: reference.evidence_fingerprint,
    result_fingerprint: reference.result_fingerprint,
    determinism_fingerprint: reference.determinism_fingerprint,
    state: "COMPLETED",
    sample: {
        instrument: "BTCUSDT.BINANCE",
        start_at: "2025-01-03T00:00:00Z",
        end_at: "2025-01-03T12:00:00Z",
        quantity: "0.01",
        rule_observed_at: "2026-11-02T00:00:00Z"
    },
    metrics: {
        initial_equity: "10000.00",
        final_equity: "10000.02",
        return_since_start: "0.000002",
        net_pnl: "0.02",
        realized_pnl: "0.02",
        unrealized_pnl: "0.00",
        fees: "0.001",
        maximum_drawdown: "-0.000001",
        fill_count: 0,
        roundtrip_count: 0
    },
    curve: [],
    baseline: null,
    trades: [],
    positions: [],
    limitations: ["受控测试；短样本不代表未来表现。"]
} satisfies BacktestResult;
const issuedAt = Math.floor(Date.now() / 1000);
const encoded = (value: unknown) =>
    btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(value))))
        .replaceAll("+", "-")
        .replaceAll("/", "_")
        .replace(/=+$/, "");
// This is a controlled wire example. The browser never possesses a signing key;
// actual signature verification belongs to the Agent's PyJWT boundary tests.
const assertion = `${encoded({ alg: "HS256", typ: "JWT" })}.${encoded({
    v: 1,
    iss: "onlyalpha-backend-backtest-analysis-v1",
    aud: "onlyalpha-agent-backtest-analysis",
    sub: "owner",
    kind: "BACKTEST_ANALYSIS_DATA",
    jti: "controlled",
    iat: issuedAt,
    exp: issuedAt + 300,
    data: {
        ...reference,
        schema_version: 1,
        profile: "ONLYALPHA_BACKTEST_ANALYSIS_DATA_V1",
        state: "COMPLETED",
        sample: result.sample,
        metrics: result.metrics,
        baseline: null,
        trades: [],
        trade_count: 0,
        trades_truncated: false,
        limitations: result.limitations
    }
})}.controlled-signature`;
interface Call {
    path: string;
    body: object | undefined;
    command: string | undefined;
    access: Access | undefined;
    method: "PUT" | "POST" | undefined;
}
const calls: Call[] = [];
let sid: string | undefined;
let current: Record<string, unknown> | undefined;
let createCommand: string | undefined;
let messageCommand: string | undefined;
let modelCalls = 0;
let loseReply = false;
let unknown = false;
let createdWorkflowUnavailable = false;
let referenceMutation: Record<string, unknown> | undefined;
const turn = () => ({
    head: "3".repeat(64),
    topic: "BACKTEST_ANALYSIS",
    user: "解释回测",
    assistant: unknown ? null : "费用已计入结果；短样本不能证明可持续盈利。",
    status: unknown ? "OUTCOME_UNKNOWN" : "READY",
    candidate: null,
    study: null,
    factor_reference: null,
    study_reference: null,
    backtest_reference: referenceMutation ?? reference
});
function server(call: Call): unknown {
    calls.push(call);
    if (call.path === `/api/v2/backtest/runs/${run}/analysis-context`) {
        expect(call.access).toBeUndefined();
        expect(call.command).toBeUndefined();
        return { schema_version: 1, run_id: run, assertion, expires_at: issuedAt + 300 };
    }
    if (call.path === `/api/v2/backtest/runs/${run}/result`) {
        expect(call.access).toBeUndefined();
        return result;
    }
    expect(call.access?.binding).toBe(access.binding);
    if (call.path === "/api/v1/agent/models") {
        expect(call.body).toBeUndefined();
        return { items: [model] };
    }
    if (call.path === "/api/v1/agent/sessions" && call.body === undefined)
        return { items: current ? [current] : [] };
    if (call.path.startsWith("/api/v1/agent/commands/")) {
        const id = call.path.split("/").at(-1);
        if (id === createCommand) return { status: "ACCEPTED", outcome: { id: sid, workflow } };
        if (id === messageCommand)
            return { status: "ACCEPTED", outcome: { event: "3".repeat(64) } };
        return { status: "UNKNOWN", outcome: null };
    }
    if (call.method === "PUT" && call.path.startsWith("/api/v1/agent/sessions/")) {
        expect(sid).toBeUndefined();
        sid = call.path.split("/").at(-1);
        createCommand = call.command;
        expect(call.body).toMatchObject({ model_revision: revision });
        current = {
            id: sid,
            workflow,
            current_workflow: createdWorkflowUnavailable ? "9".repeat(64) : workflow,
            model_revision: revision,
            head: null,
            consumed: 0,
            model_call_limit: 1,
            messages: [],
            status: createdWorkflowUnavailable ? "WORKFLOW_UNAVAILABLE" : "READY",
            topic: "FACTOR",
            candidate: null,
            study: null,
            factor_reference: null,
            study_reference: null,
            execution_admitted: false,
            continuation: null,
            successor: null
        };
        return current;
    }
    if (call.path === `/api/v1/agent/sessions/${sid ?? ""}/messages` && call.body !== undefined) {
        modelCalls++;
        expect(modelCalls).toBe(1);
        messageCommand = call.command;
        expect(call.body).toMatchObject({
            expected: null,
            topic: "BACKTEST_ANALYSIS",
            backtest_run_id: run,
            analysis_assertion: assertion
        });
        expect(call.body).not.toHaveProperty("factor_proposal_fingerprint");
        current = {
            ...current,
            head: "3".repeat(64),
            consumed: 1,
            status: unknown ? "OUTCOME_UNKNOWN" : "READY",
            topic: "BACKTEST_ANALYSIS",
            backtest_reference: reference,
            messages: [
                { role: "user", content: "解释回测" },
                ...(unknown ? [] : [{ role: "assistant", content: turn().assistant }])
            ]
        };
        if (loseReply) throw new Error("controlled response lost after acceptance");
        return current;
    }
    if (call.path === `/api/v1/agent/sessions/${sid ?? ""}/conversation`)
        return {
            id: sid,
            head: current?.head,
            model_revision: current?.model_revision,
            model: {
                name: model.name,
                model_id: model.model_id,
                model_version: model.model_version
            },
            turns: current?.head ? [turn()] : []
        };
    if (call.path === `/api/v1/agent/sessions/${sid ?? ""}` && call.body === undefined)
        return current;
    throw new Error(`Unexpected operation ${call.path}`);
}
beforeEach(() => {
    sessionStorage.clear();
    calls.length = 0;
    sid = undefined;
    current = undefined;
    createCommand = undefined;
    messageCommand = undefined;
    modelCalls = 0;
    loseReply = false;
    unknown = false;
    createdWorkflowUnavailable = false;
    referenceMutation = undefined;
    vi.mocked(connect).mockResolvedValue(access);
    vi.mocked(request).mockImplementation(
        <T>(
            path: string,
            schema: z.ZodType<T>,
            body?: object,
            command?: string,
            chosen?: Access,
            method?: "PUT" | "POST"
        ) =>
            Promise.resolve().then(() =>
                schema.parse(server({ path, body, command, access: chosen, method }))
            )
    );
});
afterEach(() => {
    vi.clearAllMocks();
});
it("reads the already configured model metadata and sends signed data through the original Agent turn", async () => {
    expect(await loadModels()).toEqual({ items: [model] });
    const interpreted = await interpretResult(result, revision);
    expect(interpreted.message).toContain("短样本");
    expect(modelCalls).toBe(1);
    const posts = calls.filter((c) => c.body !== undefined);
    expect(posts.some((c) => c.path.includes("/models"))).toBe(false);
    expect(
        posts.some(
            (c) =>
                c.path.includes("/proposals") ||
                c.path.includes("/research") ||
                c.path.includes("/live")
        )
    ).toBe(false);
    expect(posts.filter((c) => c.path.endsWith("/messages"))).toHaveLength(1);
    expect(calls.find((c) => c.path.endsWith("/analysis-context"))?.body).toEqual({});
    expect(JSON.stringify(sessionStorage)).not.toContain("model-only-secret");
});
it("reloads the original server event after browser auxiliary identifiers are lost", async () => {
    const first = await interpretResult(result, revision);
    sessionStorage.clear();
    const restored = await loadInterpretation(run);
    expect(restored?.message).toBe(first.message);
    expect(modelCalls).toBe(1);
    expect(calls.some((c) => c.path === "/api/v1/agent/sessions" && c.body === undefined)).toBe(
        true
    );
    expect(calls.filter((c) => c.path.endsWith("/messages") && c.body !== undefined)).toHaveLength(
        1
    );
});
it("lost model reply observes the original command/session instead of making a second call", async () => {
    loseReply = true;
    await interpretResult(result, revision).catch(() => null);
    const original = messageCommand;
    const restored = await loadInterpretation(run);
    expect(restored?.message).toContain("费用");
    expect(messageCommand).toBe(original);
    expect(modelCalls).toBe(1);
    expect(
        calls.some(
            (c) => c.path === `/api/v1/agent/commands/${original ?? ""}` && c.body === undefined
        )
    ).toBe(true);
});
it("unknown original model outcome permits reads and refuses a fresh session or turn", async () => {
    unknown = true;
    await interpretResult(result, revision).catch(() => null);
    const originalMessage = messageCommand,
        originalSession = sid;
    await loadInterpretation(run).catch(() => null);
    await interpretResult(result, revision).catch(() => null);
    expect(sid).toBe(originalSession);
    expect(messageCommand).toBe(originalMessage);
    expect(modelCalls).toBe(1);
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
    expect(calls.filter((c) => c.path.endsWith("/messages") && c.body !== undefined)).toHaveLength(
        1
    );
});
it.each(["run_id", "strategy_fingerprint", "evidence_fingerprint", "result_fingerprint"])(
    "refuses a different server event %s even with retained browser identifiers",
    async (key) => {
        await interpretResult(result, revision);
        referenceMutation = {
            ...reference,
            [key]: key === "run_id" ? "00000000-0000-4000-8000-000000009399" : "9".repeat(64)
        };
        await expect(loadInterpretation(run)).rejects.toThrow();
        expect(modelCalls).toBe(1);
    }
);
it.each(["model_revision", "workflow"])(
    "does not select a replacement when the original %s differs",
    async (key) => {
        await interpretResult(result, revision);
        current = { ...current, [key]: "9".repeat(64) };
        await expect(loadInterpretation(run)).rejects.toThrow();
        expect(modelCalls).toBe(1);
    }
);
it("returns no interpretation when the exact Run has no owning Agent occurrence", async () => {
    expect(await loadInterpretation(run)).toBeNull();
    expect(modelCalls).toBe(0);
    expect(calls.some((c) => c.method === "PUT" || c.path.endsWith("/messages"))).toBe(false);
});

// Current workflow availability is an execution gate. A verified original
// occurrence remains readable under its own immutable model/workflow identity.
it.each(["retained", "rediscovered"])(
    "reads the original completed interpretation with unavailable workflow (%s)",
    async (mode) => {
        const first = await interpretResult(result, revision);
        current = { ...current, current_workflow: "9".repeat(64), status: "WORKFLOW_UNAVAILABLE" };
        if (mode === "rediscovered") sessionStorage.clear();
        const before = calls.length;
        const restored = await loadInterpretation(run);
        expect(restored?.message).toBe(first.message);
        expect(restored?.provenance?.model_revision).toBe(revision);
        expect(restored?.provenance?.session_id).toBe(sid);
        expect((await interpretResult(result, revision)).message).toBe(first.message);
        expect(calls.slice(before).every((c) => c.body === undefined)).toBe(true);
        expect(modelCalls).toBe(1);
    }
);
it("refuses a new model occurrence when its newly created workflow is unavailable", async () => {
    createdWorkflowUnavailable = true;
    await expect(interpretResult(result, revision)).rejects.toThrow();
    expect(modelCalls).toBe(0);
    expect(calls.filter((c) => c.path.endsWith("/messages") && c.body !== undefined)).toHaveLength(
        0
    );
    await loadInterpretation(run).catch(() => null);
    expect(modelCalls).toBe(0);
});
