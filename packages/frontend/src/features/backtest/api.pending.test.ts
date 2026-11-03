// Controlled actual fetch/parser recovery. This is not Shipping business acceptance.
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import * as api from "./api";
import wire from "./fixtures/preparation-wire-v2.json";
const seed = api.preparationSchema.parse(wire.manual_ready);
const command = "00000000-0000-4000-8000-000000007201",
    future = "00000000-0000-4000-8000-000000007202";
const input = {
    schema_version: 2 as const,
    profile: seed.profile,
    origin: seed.origin,
    release_manifest_fingerprint: "f".repeat(64),
    expected_active_generation: "1".repeat(64),
    initialize_fresh_runtime: false as const,
    source: seed.source,
    backtest_command_id: future
};
const key = `onlyalpha.backtest.preparation.v2.${JSON.stringify(seed.origin)}`;
const intent = { schema_version: 2, command, input };
const original = { ...seed, command_id: command, backtest_command_id: future };
let retained: string, response: unknown, status: number, changeOnRead: boolean;
let reads: string[];
function recovery() {
    const value = api.pendingPreparation(seed.origin);
    if (value === null) throw new Error("original pending request missing");
    return value;
}
beforeEach(() => {
    sessionStorage.clear();
    retained = JSON.stringify(intent);
    sessionStorage.setItem(key, retained);
    response = original;
    status = 200;
    changeOnRead = false;
    reads = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) => {
            expect(init?.method).toBe("GET");
            expect(init?.body).toBeUndefined();
            expect(new Headers(init?.headers).has("Authorization")).toBe(false);
            expect(path).toBe(`/api/v2/backtest/preparations/commands/${command}`);
            reads.push(path);
            if (changeOnRead) sessionStorage.setItem(key, JSON.stringify({ a_newer_intent: true }));
            return Promise.resolve(
                new Response(JSON.stringify(response), {
                    status,
                    headers: { "Content-Type": "application/json" }
                })
            );
        })
    );
});
afterEach(() => vi.unstubAllGlobals());
it.each([false, true])(
    "discovers only auxiliary original intent without requests and observes its exact positive preparation (run=%s)",
    async (withRun) => {
        const pending = recovery();
        expect(reads).toHaveLength(0);
        response = {
            ...original,
            run_id: withRun ? original.reserved_run_id : null,
            backtest_outcome: withRun ? "ACCEPTED" : "NOT_SUBMITTED"
        };
        expect(await pending.observe()).toEqual(response);
        expect(sessionStorage.getItem(key)).toBeNull();
        expect(reads).toHaveLength(1);
    }
);
it("typed None alone leaves the lost original pending and never turns observation into another effect", async () => {
    response = { schema_version: 2, command_id: command, state: "NOT_ACCEPTED" };
    const error: unknown = await recovery()
        .observe()
        .catch((value: unknown) => value);
    expect(error).toHaveProperty("observe");
    expect(api.isPreparationNotStarted(error)).toBe(false);
    expect(sessionStorage.getItem(key)).toBe(retained);
    await recovery()
        .observe()
        .catch(() => null);
    expect(sessionStorage.getItem(key)).toBe(retained);
    expect(reads).toHaveLength(2);
});
it.each([
    [503, { error: { code: "BACKTEST_PREPARATION_NOT_ACCEPTED" } }],
    [404, { detail: "BACKTEST_PREPARATION_NOT_ACCEPTED" }],
    [200, { schema_version: 2, command_id: future, state: "NOT_ACCEPTED" }],
    [200, { ...original, source: { ...original.source, environment: "FOREIGN" } }],
    [200, { ...original, backtest_command_id: command }],
    [200, { schema_version: 2, command_id: command, state: "NOT_ACCEPTED", extra: true }],
    [200, { ...original, validation_fingerprint: null }]
])("response %s never clears or unlocks the original unknown request", async (code, value) => {
    status = code;
    response = value;
    const error: unknown = await recovery()
        .observe()
        .catch((caught: unknown) => caught);
    expect(error).toHaveProperty("observe");
    expect(api.isPreparationNotStarted(error)).toBe(false);
    expect(sessionStorage.getItem(key)).toBe(retained);
    expect(recovery()).not.toBeNull();
    expect(reads).toHaveLength(1);
});
it.each([
    "not JSON",
    JSON.stringify({
        ...intent,
        input: { ...input, origin: { ...seed.origin, kind: "FROZEN_STRATEGY" } }
    })
])("malformed auxiliary data stays blocked without a request", async (raw) => {
    sessionStorage.setItem(key, raw);
    const error: unknown = await recovery()
        .observe()
        .catch((value: unknown) => value);
    expect(error).toHaveProperty("observe");
    expect(sessionStorage.getItem(key)).toBe(raw);
    expect(reads).toHaveLength(0);
});
it("a positive old response cannot consume a changed local intent", async () => {
    const pending = recovery();
    changeOnRead = true;
    const error: unknown = await pending.observe().catch((value: unknown) => value);
    expect(error).toHaveProperty("observe");
    expect(JSON.parse(sessionStorage.getItem(key) ?? "null") as unknown).toEqual({
        a_newer_intent: true
    });
    expect(reads).toHaveLength(1);
});
it("a retained correlated refusal still requires an explicit condition-review click after exact typed None", async () => {
    retained = JSON.stringify({ ...intent, refusal: "CONDITIONS_CHANGED" });
    sessionStorage.setItem(key, retained);
    response = { schema_version: 2, command_id: command, state: "NOT_ACCEPTED" };
    const error: unknown = await recovery()
        .observe()
        .catch((value: unknown) => value);
    if (!api.isPreparationNotStarted(error))
        throw new Error("the original refusal should offer its existing explicit condition review");
    expect(sessionStorage.getItem(key)).toBe(retained);
    expect(await error.reviewConditions()).toBeNull();
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(reads).toHaveLength(2);
});
it("empty auxiliary state has no recovery entry and makes no request", () => {
    sessionStorage.removeItem(key);
    expect(api.pendingPreparation(seed.origin)).toBeNull();
    expect(reads).toHaveLength(0);
});
