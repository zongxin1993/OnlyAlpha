// Controlled HTTP responses exercise the real fetch/request/parser boundary.
// Actual owning PG guard tests and Shipping business acceptance remain separate.
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import {
    creationSchema,
    preparationSchema,
    prepareBacktest,
    loadPreparation,
    isPreparationNotStarted
} from "./api";
import wire from "./fixtures/preparation-wire-v2.json";

const seed = preparationSchema.parse(wire.manual_progress);
const context = creationSchema.parse({
    schema_version: 2,
    strategy_name: "BTC 价量动量",
    input_defaults: {
        schema_version: 2,
        profile: seed.profile,
        origin: seed.origin,
        release_manifest_fingerprint: "f".repeat(64),
        expected_active_generation: "1".repeat(64),
        initialize_fresh_runtime: false
    },
    sample_start_at: "2025-01-03T00:00:00Z",
    sample_end_at: "2025-01-03T12:00:00Z",
    initial_cash: "10000",
    quantity: "0.01",
    fee_bps: 10,
    slippage_bps: 2,
    limitations: [],
    existing_preparations: []
});
let original: { command: string; input: object } | undefined;
let posts: string[] = [],
    gets: string[] = [];
let losePost = false;
let changeIntentOnGet = false;
let response: { status: number; value: (command: string) => unknown };
function retained() {
    return sessionStorage.getItem(Object.keys(sessionStorage)[0] ?? "");
}
beforeEach(() => {
    sessionStorage.clear();
    original = undefined;
    posts = [];
    gets = [];
    losePost = false;
    changeIntentOnGet = false;
    response = {
        status: 200,
        value: (command) => ({ schema_version: 2, command_id: command, state: "NOT_ACCEPTED" })
    };
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) => {
            if (init?.method === "POST" && path === "/api/v2/backtest/preparations") {
                const command = new Headers(init.headers).get("Idempotency-Key");
                if (command === null) throw new Error("original command header missing");
                if (typeof init.body !== "string")
                    return Promise.reject(new Error("original JSON body missing"));
                original = { command, input: JSON.parse(init.body) as object };
                posts.push(command);
                if (losePost) return Promise.reject(new TypeError("controlled transport loss"));
                return Promise.resolve(
                    new Response(
                        JSON.stringify({
                            schema_version: 2,
                            state: "NOT_ACCEPTED",
                            command_id: command,
                            input: original.input,
                            reason: "CONDITIONS_CHANGED"
                        }),
                        { status: 200, headers: { "Content-Type": "application/json" } }
                    )
                );
            }
            if (
                original === undefined ||
                path !== `/api/v2/backtest/preparations/commands/${original.command}`
            )
                throw new Error("foreign original query");
            gets.push(path);
            if (changeIntentOnGet) {
                const key = Object.keys(sessionStorage)[0];
                if (key === undefined) throw new Error("original intent missing");
                sessionStorage.setItem(key, JSON.stringify({ a_newer_intent: true }));
            }
            return Promise.resolve(
                new Response(JSON.stringify(response.value(original.command)), {
                    status: response.status,
                    headers: { "Content-Type": "application/json" }
                })
            );
        })
    );
});
afterEach(() => vi.unstubAllGlobals());

it.each([
    {
        label: "503 structured code",
        status: 503,
        value: () => ({
            schema_version: 1,
            error: {
                phase: "QUERY",
                code: "BACKTEST_PREPARATION_NOT_ACCEPTED",
                detail: "BACKTEST_PREPARATION_NOT_ACCEPTED"
            }
        })
    },
    {
        label: "404 structured code",
        status: 404,
        value: () => ({ schema_version: 1, error: { code: "BACKTEST_PREPARATION_NOT_ACCEPTED" } })
    },
    {
        label: "404 detail string",
        status: 404,
        value: () => ({ detail: "BACKTEST_PREPARATION_NOT_ACCEPTED" })
    },
    {
        label: "404 error string",
        status: 404,
        value: () => ({ error: "BACKTEST_PREPARATION_NOT_ACCEPTED" })
    },
    {
        label: "200 error envelope",
        status: 200,
        value: () => ({ schema_version: 1, error: { code: "BACKTEST_PREPARATION_NOT_ACCEPTED" } })
    },
    {
        label: "200 foreign Command",
        status: 200,
        value: () => ({
            schema_version: 2,
            command_id: "00000000-0000-4000-8000-000000008299",
            state: "NOT_ACCEPTED"
        })
    },
    {
        label: "200 extra field",
        status: 200,
        value: (command: string) => ({
            schema_version: 2,
            command_id: command,
            state: "NOT_ACCEPTED",
            error: "not evidence"
        })
    }
])("$label cannot discard an explicitly refused original intent", async (invalid) => {
    const error: unknown = await prepareBacktest(context, seed.source).catch(
        (value: unknown) => value
    );
    if (!isPreparationNotStarted(error))
        throw new Error("expected correlated original POST refusal");
    const before = retained();
    response = invalid;
    const unknown: unknown = await error.reviewConditions().catch((value: unknown) => value);
    expect(isPreparationNotStarted(unknown)).toBe(false);
    expect(unknown).toHaveProperty("observe");
    expect(retained()).toBe(before);
    expect(posts).toHaveLength(1);
    expect(gets).toHaveLength(1);
});
it("only a successful exact typed observation permits explicit auxiliary discard after original POST refusal", async () => {
    const error: unknown = await prepareBacktest(context, seed.source).catch(
        (value: unknown) => value
    );
    if (!isPreparationNotStarted(error)) throw new Error("expected correlated refusal");
    expect(sessionStorage.length).toBe(1);
    expect(gets).toHaveLength(0);
    expect(await error.reviewConditions()).toBeNull();
    expect(sessionStorage.length).toBe(0);
    expect(posts).toHaveLength(1);
    expect(gets).toHaveLength(1);
});
it("the same typed observation cannot clear a lost POST or satisfy ordinary preparation load", async () => {
    losePost = true;
    const unknown: unknown = await prepareBacktest(context, seed.source).catch(
        (value: unknown) => value
    );
    expect(isPreparationNotStarted(unknown)).toBe(false);
    expect(unknown).toHaveProperty("observe");
    if (original === undefined) throw new Error("original request missing");
    const before = retained();
    await expect(loadPreparation(original.command)).rejects.toThrow();
    expect(retained()).toBe(before);
    expect(posts).toHaveLength(1);
    expect(JSON.parse(before ?? "null") as object).not.toHaveProperty("refusal");
});

it("a typed None arriving after local intent changed cannot discard the new intent", async () => {
    const error: unknown = await prepareBacktest(context, seed.source).catch(
        (value: unknown) => value
    );
    if (!isPreparationNotStarted(error)) throw new Error("expected correlated refusal");
    changeIntentOnGet = true;
    await expect(error.reviewConditions()).rejects.toThrow();
    expect(JSON.parse(retained() ?? "null") as object).toEqual({ a_newer_intent: true });
    expect(posts).toHaveLength(1);
    expect(gets).toHaveLength(1);
});
