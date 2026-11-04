// Controlled HTTP projections verify wire/recovery only. Actual business
// acceptance uses the Shipping Web UI against the canonical backend.
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import type { z } from "zod";
import type * as FactorChatApi from "../factorChat/api";
import { request, ChatRequestError, type Access } from "../factorChat/api";
import {
    loadSources,
    loadCreationContext,
    preparationSchema,
    loadRuns,
    loadRun,
    loadResult,
    prepareBacktest,
    loadPreparation,
    confirmBacktest,
    cancelBacktest,
    cancelPreparation,
    resumePreparation,
    isPreparationNotStarted
} from "./api";
vi.mock("../factorChat/api", async (original) => ({
    ...(await original<typeof FactorChatApi>()),
    request: vi.fn()
}));
const run = "00000000-0000-4000-8000-000000009402",
    future = "00000000-0000-4000-8000-000000009403",
    integration = "00000000-0000-4000-8000-000000009404";
const strategy = "a".repeat(64),
    freeze = "b".repeat(64),
    decision = "c".repeat(64),
    promotion = "d".repeat(64),
    preparationFP = "2".repeat(64);
const origin = {
    kind: "MANUAL_STRATEGY" as const,
    strategy_id: "private.strategy.btc_momentum",
    strategy_revision_fingerprint: "e".repeat(64)
};
const source = {
    integration_id: integration,
    integration_revision_fingerprint: "3".repeat(64),
    expected_type_id: "binance.spot.market_data" as const,
    source_id: "binance.spot.market_data.live",
    environment: "GLOBAL",
    instrument_id: "BTCUSDT.BINANCE" as const
};
const defaults = {
    schema_version: 2 as const,
    profile: "BTC_SPOT_NEXT_OPEN_BACKTEST_V1" as const,
    origin,
    release_manifest_fingerprint: "8".repeat(64),
    expected_active_generation: "9".repeat(64),
    initialize_fresh_runtime: false as const
};
const creation = {
    schema_version: 2 as const,
    strategy_name: "BTC 价量动量",
    input_defaults: defaults,
    sample_start_at: "2025-01-03T00:00:00Z" as const,
    sample_end_at: "2025-01-03T12:00:00Z" as const,
    initial_cash: "10000" as const,
    quantity: "0.01" as const,
    fee_bps: 10 as const,
    slippage_bps: 2 as const,
    limitations: ["短样本仅供探索"],
    existing_preparations: []
};
const resultValue = {
    schema_version: 1,
    run_id: run,
    strategy_fingerprint: strategy,
    evidence_fingerprint: "1".repeat(64),
    result_fingerprint: "2".repeat(64),
    determinism_fingerprint: "3".repeat(64),
    state: "COMPLETED",
    sample: {
        instrument: "BTCUSDT",
        start_at: "2025-01-03T00:00:00Z",
        end_at: "2025-01-03T12:00:00Z",
        quantity: "0.01",
        rule_observed_at: "2026-11-02T00:00:00Z"
    },
    metrics: {
        initial_equity: "10000.00",
        final_equity: "9998.00",
        return_since_start: "-0.0002",
        net_pnl: "-2.00",
        realized_pnl: "-1.00",
        unrealized_pnl: "-1.00",
        fees: "1.00",
        maximum_drawdown: "-0.0002",
        fill_count: 1,
        roundtrip_count: 0
    },
    curve: [{ at_ns: "1735862460000000000", nav: "9998.00", drawdown: "-0.0002" }],
    baseline: null,
    trades: [
        {
            ordinal: 1,
            time_ns: "1735862460000000000",
            side: "BUY",
            quantity: "0.01",
            price: "100000.00",
            fee: "1.00",
            signal_time_ns: "1735862400000000000",
            signal: "满足开仓条件",
            order_id: "controlled-order",
            trade_id: "controlled-trade"
        }
    ],
    positions: [
        {
            instrument: "BTCUSDT",
            quantity: "0.01",
            average_price: "100000.00",
            state: "OPEN"
        }
    ],
    limitations: ["短样本仅供探索；当前规则不代表历史交易所审核。"]
};

interface Call {
    path: string;
    body: object | undefined;
    command: string | undefined;
}
const calls: Call[] = [];
let prepId: string | undefined,
    futureId = future,
    accepted = false,
    submitted = false,
    prepState = "READY",
    revision = "4",
    runState = "RUNNING";
let unknownPrepare = false,
    lostSubmit = false,
    lostCancel = false,
    wrongRun = false,
    missingPositions = false;
let workerObservation: Record<string, unknown> | undefined;
let submitFailure: "unavailable" | "transport" | undefined;
let prepMutation: Record<string, unknown> = {};
let prepareGeneration: string | null = defaults.expected_active_generation;
let prepareRelease = defaults.release_manifest_fingerprint;
let refusedPrepare: "CONDITIONS_CHANGED" | "SOURCE_UNAVAILABLE" | undefined;
let refusalMutation: Record<string, unknown> = {};
let replaceIntentBeforeRefusal = false;
let preparationQueryFailure: Error | undefined;
function prep() {
    return {
        schema_version: 2,
        command_id: prepId ?? "00000000-0000-4000-8000-000000009405",
        profile: "BTC_SPOT_NEXT_OPEN_BACKTEST_V1",
        origin,
        strategy_fingerprint: prepState === "READY" ? strategy : null,
        validation_fingerprint: prepState === "READY" ? "8".repeat(64) : null,
        freeze_relation_fingerprint: prepState === "READY" ? freeze : null,
        qualification_decision_fingerprint: prepState === "READY" ? decision : null,
        promotion_fingerprint: prepState === "READY" ? promotion : null,
        source,
        revision,
        state: prepState,
        phase: prepState === "READY" ? "READY_FOR_HUMAN_CONFIRMATION" : "VALIDATION",
        backtest_command_id: futureId,
        reserved_run_id: run,
        preparation_fingerprint: prepState === "READY" ? preparationFP : null,
        detail: null,
        backtest_outcome: submitted ? "ACCEPTED" : "NOT_SUBMITTED",
        readiness: {
            state: prepState === "READY" ? "VERIFIED" : "NOT_APPLICABLE",
            code: null
        },
        run_id: submitted ? run : null,
        accepted_at: "2026-11-02T00:00:40Z",
        ...prepMutation
    };
}
function runView() {
    return {
        schema_version: 1,
        run_id: wrongRun ? future : run,
        strategy_fingerprint: strategy,
        state: runState,
        revision: "9007199254740993",
        accepted_at: "2026-11-02T00:00:50Z",
        preparation_command_id: prepId ?? null,
        report_status: {
            state: runState === "COMPLETED" ? "VERIFIED" : "PENDING",
            code: null
        },
        ...(workerObservation === undefined ? {} : { worker_observation: workerObservation })
    };
}
function server(call: Call): unknown {
    calls.push(call);
    if (call.path.startsWith("/api/v2/backtest/creation-context?")) {
        expect(
            Object.fromEntries(new URL(call.path, "https://workstation.invalid").searchParams)
        ).toEqual({
            strategy_id: origin.strategy_id,
            strategy_revision_fingerprint: origin.strategy_revision_fingerprint
        });
        return creation;
    }
    if (call.path === "/api/v2/backtest/runs" && call.body === undefined)
        return { schema_version: 1, items: [runView()] };
    if (call.path === `/api/v2/backtest/runs/${run}/result`) {
        const value = { ...resultValue } as Record<string, unknown>;
        if (missingPositions) delete value.positions;
        return value;
    }
    if (call.path === `/api/v2/backtest/runs/${run}` && call.body === undefined) return runView();
    if (call.path === `/api/v2/backtest/runs/${run}/cancellation`) {
        expect(call.body).toEqual({ schema_version: 1, run_id: run });
        runState = "CANCEL_REQUESTED";
        return runView();
    }
    if (call.path === "/api/v2/backtest/preparations") {
        const body = call.body as { backtest_command_id: string };
        expect(body).toEqual({
            ...defaults,
            release_manifest_fingerprint: prepareRelease,
            expected_active_generation: prepareGeneration,
            source,
            backtest_command_id: expect.any(String) as unknown
        });
        prepId = call.command;
        futureId = body.backtest_command_id;
        if (unknownPrepare) throw new Error("controlled outcome unknown");
        if (refusedPrepare !== undefined) {
            if (replaceIntentBeforeRefusal) {
                const key = Object.keys(sessionStorage)[0];
                if (key === undefined) throw new Error("original intent missing");
                const retained = JSON.parse(sessionStorage.getItem(key) ?? "null") as Record<
                    string,
                    unknown
                >;
                sessionStorage.setItem(key, JSON.stringify({ ...retained, command: future }));
            }
            return {
                schema_version: 2,
                state: "NOT_ACCEPTED",
                command_id: call.command,
                input: body,
                reason: refusedPrepare,
                ...refusalMutation
            };
        }
        accepted = true;
        return prep();
    }
    if (call.path.startsWith("/api/v2/backtest/preparations/commands/")) {
        if (preparationQueryFailure !== undefined) throw preparationQueryFailure;
        if (!accepted) return { schema_version: 2, command_id: prepId, state: "NOT_ACCEPTED" };
        return prep();
    }
    if (call.path.endsWith("/submit")) {
        if (submitFailure === "unavailable")
            throw new ChatRequestError("BACKTEST_SERVICE_UNAVAILABLE");
        if (submitFailure === "transport") throw new Error("controlled transport loss");
        expect(call.command).toBe(futureId);
        expect(call.body).toEqual({
            schema_version: 1,
            preparation_command_id: prepId,
            preparation_fingerprint: preparationFP
        });
        submitted = true;
        if (lostSubmit) throw new Error("controlled lost reply");
        return {
            schema_version: 1,
            backtest_command_id: futureId,
            state: "ACCEPTED",
            run_id: run
        };
    }
    if (call.path.endsWith("/cancellation")) {
        expect(call.body).toEqual({
            schema_version: 1,
            preparation_command_id: prepId,
            expected_revision: revision
        });
        prepState = "CANCEL_REQUESTED";
        revision = "9007199254740994";
        if (lostCancel) throw new Error("controlled lost cancellation reply");
        return prep();
    }
    if (call.path.endsWith("/resume")) {
        expect(call.command).toBe(prepId);
        expect(call.body).toEqual({
            schema_version: 1,
            preparation_command_id: prepId,
            expected_revision: revision
        });
        prepState = "RUNNING";
        return prep();
    }
    throw new Error("unexpected client operation " + call.path);
}
beforeEach(() => {
    sessionStorage.clear();
    calls.length = 0;
    prepId = undefined;
    futureId = future;
    accepted = false;
    submitted = false;
    prepState = "READY";
    revision = "4";
    runState = "RUNNING";
    unknownPrepare = false;
    lostSubmit = false;
    lostCancel = false;
    wrongRun = false;
    missingPositions = false;
    workerObservation = undefined;
    submitFailure = undefined;
    prepMutation = {};
    prepareGeneration = defaults.expected_active_generation;
    prepareRelease = defaults.release_manifest_fingerprint;
    refusedPrepare = undefined;
    refusalMutation = {};
    replaceIntentBeforeRefusal = false;
    preparationQueryFailure = undefined;
    vi.mocked(request).mockImplementation(
        <T>(path: string, schema: z.ZodType<T>, body?: object, command?: string, access?: Access) =>
            Promise.resolve().then(() => {
                expect(access).toBeUndefined();
                return schema.parse(server({ path, body, command }));
            })
    );
});
afterEach(() => vi.clearAllMocks());
function posts(fragment: string) {
    return calls.filter((value) => value.body !== undefined && value.path.includes(fragment));
}
function recovery(value: unknown): { observe: () => Promise<unknown> } {
    expect(value).toBeInstanceOf(Error);
    expect(value).toHaveProperty("observe");
    return value as never;
}
it("loads exact manual defaults without a Research, Study, Qualification or Agent call", async () => {
    expect(await loadCreationContext(origin)).toEqual(creation);
    expect(calls).toHaveLength(1);
    expect(calls.every((value) => value.body === undefined)).toBe(true);
});
it("prepares the manual strategy through one backend command and never starts a Run", async () => {
    const value = await prepareBacktest(creation, source);
    expect(value.state).toBe("READY");
    expect(value.origin).toEqual(origin);
    expect(posts("/backtest/preparations")).toHaveLength(1);
    expect(posts("/submit")).toHaveLength(0);
    expect(calls.some((value) => /qualification|promotion|research|agent/.test(value.path))).toBe(
        false
    );
    expect(await loadPreparation(value.command_id)).toEqual(value);
});
it("reuses an existing unfinished preparation with its original future command", async () => {
    accepted = true;
    prepId = "00000000-0000-4000-8000-000000009405";
    const original = preparationSchema.parse(prep());
    expect(
        await prepareBacktest({ ...creation, existing_preparations: [original] }, source)
    ).toEqual(original);
    expect(calls.every((value) => value.body === undefined)).toBe(true);
});
it("does not reuse a completed Run as a new Human preparation", async () => {
    accepted = true;
    submitted = true;
    const original = preparationSchema.parse(prep());
    submitted = false;
    await prepareBacktest({ ...creation, existing_preparations: [original] }, source);
    expect(posts("/backtest/preparations")).toHaveLength(1);
});
it("keeps unknown preparation outcome observe-only across repeat clicks and GET missing", async () => {
    unknownPrepare = true;
    const error = recovery(
        await prepareBacktest(creation, source).catch((value: unknown) => value)
    );
    await error.observe().catch(() => null);
    await prepareBacktest(creation, source).catch(() => null);
    expect(posts("/backtest/preparations")).toHaveLength(1);
    expect(posts("/submit")).toHaveLength(0);
    accepted = true;
    expect(await error.observe()).toMatchObject({
        command_id: prepId,
        origin,
        backtest_command_id: futureId
    });
});
it("does not replace an unresolved original when selected source or strategy content changes", async () => {
    unknownPrepare = true;
    await prepareBacktest(creation, source).catch(() => null);
    unknownPrepare = false;
    await prepareBacktest(creation, { ...source, environment: "OTHER" }).catch(() => null);
    expect(posts("/backtest/preparations")).toHaveLength(1);
    expect(
        calls
            .filter((value) => value.body === undefined)
            .every(
                (value) => value.path === `/api/v2/backtest/preparations/commands/${prepId ?? ""}`
            )
    ).toBe(true);
});
it("allows derived proof pins to appear while preserving immutable preparation origin and future identity", async () => {
    prepState = "RUNNING";
    const original = await prepareBacktest(creation, source);
    expect(original.strategy_fingerprint).toBeNull();
    prepState = "READY";
    const current = await loadPreparation(original.command_id);
    expect(current.strategy_fingerprint).toBe(strategy);
    expect(current.command_id).toBe(original.command_id);
    expect(current.backtest_command_id).toBe(original.backtest_command_id);
    expect((await confirmBacktest(current)).run_id).toBe(run);
    expect(posts("/submit")).toHaveLength(1);
});
it("READY cannot omit any derived pins", () => {
    expect(preparationSchema.safeParse({ ...prep(), strategy_fingerprint: null }).success).toBe(
        false
    );
});
it("submits the first Manual preparation with an explicit empty generation CAS", async () => {
    prepareGeneration = null;
    const first = {
        ...creation,
        input_defaults: { ...defaults, expected_active_generation: null }
    };
    const value = await prepareBacktest(first, source);
    expect(value.origin).toEqual(origin);
    expect(posts("/backtest/preparations")).toHaveLength(1);
    expect(posts("/backtest/preparations")[0]?.body).toMatchObject({
        origin,
        expected_active_generation: null,
        initialize_fresh_runtime: false,
        source
    });
    expect(posts("/submit")).toHaveLength(0);
    expect(calls.some((value) => /qualification|promotion|research|agent/.test(value.path))).toBe(
        false
    );
});
it("still rejects Frozen preparation without an active generation before any request", async () => {
    const frozen = {
        kind: "FROZEN_STRATEGY" as const,
        strategy_fingerprint: strategy,
        freeze_relation_fingerprint: freeze,
        qualification_decision_fingerprint: decision,
        promotion_fingerprint: promotion
    };
    await expect(
        prepareBacktest(
            {
                ...creation,
                input_defaults: {
                    ...defaults,
                    origin: frozen,
                    expected_active_generation: null
                }
            },
            source
        )
    ).rejects.toThrow();
    expect(calls).toHaveLength(0);
});
it("observes the original empty-generation Manual intent after a lost reply and later activation", async () => {
    prepareGeneration = null;
    unknownPrepare = true;
    const first = {
        ...creation,
        input_defaults: { ...defaults, expected_active_generation: null }
    };
    const pending = recovery(await prepareBacktest(first, source).catch((value: unknown) => value));
    await prepareBacktest(creation, source).catch(() => null);
    expect(posts("/backtest/preparations")).toHaveLength(1);
    accepted = true;
    expect(await pending.observe()).toMatchObject({
        command_id: prepId,
        backtest_command_id: futureId,
        origin
    });
    expect(posts("/backtest/preparations")).toHaveLength(1);
    expect(posts("/submit")).toHaveLength(0);
});
it.each(["origin", "source", "future", "reserved", "ready-proof"])(
    "rejects a changed %s before explicit Start",
    async (mutation) => {
        const original = await prepareBacktest(creation, source);
        prepMutation =
            mutation === "origin"
                ? {
                      origin: {
                          ...origin,
                          strategy_revision_fingerprint: "0".repeat(64)
                      }
                  }
                : mutation === "source"
                  ? { source: { ...source, environment: "OTHER" } }
                  : mutation === "future"
                    ? { backtest_command_id: future }
                    : mutation === "reserved"
                      ? { reserved_run_id: future }
                      : { preparation_fingerprint: "0".repeat(64) };
        await expect(confirmBacktest(original)).rejects.toThrow();
        expect(posts("/submit")).toHaveLength(0);
    }
);
it("a failed Start precheck sends nothing and explicit review preserves the original future command", async () => {
    const original = await prepareBacktest(creation, source);
    preparationQueryFailure = new ChatRequestError("BACKTEST_READINESS_UNAVAILABLE");
    await expect(confirmBacktest(original)).rejects.toThrow();
    expect(posts("/submit")).toHaveLength(0);
    expect(
        sessionStorage.getItem(`onlyalpha.backtest.submit.v2.${original.command_id}`)
    ).toBeNull();
    preparationQueryFailure = undefined;
    const reviewed = await loadPreparation(original.command_id);
    expect(reviewed).toEqual(original);
    expect((await confirmBacktest(reviewed)).run_id).toBe(run);
    expect(posts("/submit")).toHaveLength(1);
    expect(posts("/submit")[0]?.command).toBe(original.backtest_command_id);
    expect(
        calls.filter(
            (value) => value.body !== undefined && value.path === "/api/v2/backtest/preparations"
        )
    ).toHaveLength(1);
});
it("uses the original future command after a lost Start response and never submits twice", async () => {
    const prepared = await prepareBacktest(creation, source);
    lostSubmit = true;
    expect((await confirmBacktest(prepared)).run_id).toBe(run);
    lostSubmit = false;
    expect((await confirmBacktest(prepared)).run_id).toBe(run);
    expect(posts("/submit")).toHaveLength(1);
    expect(posts("/submit")[0]?.command).toBe(prepared.backtest_command_id);
});
it("cancel retains exact revision strings and its separate command after a lost response", async () => {
    const prepared = await prepareBacktest(creation, source);
    revision = "9007199254740993";
    lostCancel = true;
    await cancelPreparation({ ...prepared, revision });
    lostCancel = false;
    await cancelPreparation({ ...prepared, revision });
    expect(posts("/cancellation")).toHaveLength(1);
    expect(posts("/cancellation")[0]?.command).not.toBe(prepared.command_id);
});
it("resumes an existing blocked preparation only on an explicit original action", async () => {
    prepState = "BLOCKED";
    revision = "9007199254740993";
    const prepared = await prepareBacktest(creation, source);
    expect((await resumePreparation(prepared)).state).toBe("RUNNING");
    expect(posts("/resume")[0]?.command).toBe(prepared.command_id);
});
it("cancel Run remains separate and an accepted cancellation does not resubmit", async () => {
    const original = await loadRun(run);
    expect((await cancelBacktest(original)).state).toBe("CANCEL_REQUESTED");
    await cancelBacktest(original);
    expect(posts(`/api/v2/backtest/runs/${run}/cancellation`)).toHaveLength(1);
});
it("reads actual typed result projections including positions without a command", async () => {
    expect((await loadRuns()).items[0]?.run_id).toBe(run);
    expect((await loadRun(run)).revision).toBe("9007199254740993");
    expect(await loadResult(run)).toEqual(resultValue);
    expect(calls.every((value) => value.body === undefined)).toBe(true);
    wrongRun = true;
    await expect(loadRun(run)).rejects.toThrow();
    wrongRun = false;
    missingPositions = true;
    await expect(loadResult(run)).rejects.toThrow();
});
it.each(["STARTING", "IDLE", "RUNNING", "UNKNOWN", "UNAVAILABLE", "STOPPED"] as const)(
    "reads an optional strict worker %s observation without changing the original Run state",
    async (state) => {
        workerObservation = {
            state,
            run_id: run,
            code: "CONTROLLED_WORKER_DIAGNOSTIC"
        };
        expect(await loadRun(run)).toMatchObject({
            run_id: run,
            state: "RUNNING",
            worker_observation: workerObservation
        });
        expect((await loadRuns()).items[0]).toMatchObject({
            run_id: run,
            state: "RUNNING",
            worker_observation: workerObservation
        });
        expect(calls.every((c) => c.body === undefined)).toBe(true);
    }
);
it.each([
    { state: "FAILED" },
    { state: "UNKNOWN", command_id: future },
    { state: "RUNNING", run_id: "not-a-uuid" },
    { state: "UNKNOWN", code: 3 }
])(
    "refuses malformed worker observation %j instead of silently dropping its fields",
    async (invalid) => {
        workerObservation = invalid;
        await expect(loadRun(run)).rejects.toThrow();
        expect(calls.every((c) => c.body === undefined)).toBe(true);
    }
);
it("keeps completed result reads independent of current worker availability", async () => {
    runState = "COMPLETED";
    workerObservation = {
        state: "UNAVAILABLE",
        code: "CONTROLLED_WORKER_DIAGNOSTIC"
    };
    expect(await loadRun(run)).toMatchObject({
        run_id: run,
        state: "COMPLETED",
        report_status: { state: "VERIFIED" }
    });
    expect(await loadResult(run)).toEqual(resultValue);
    expect(calls.every((c) => c.body === undefined)).toBe(true);
});

it("allows explicit same-command Start only after exact service refusal and verified non-submission", async () => {
    const prepared = await prepareBacktest(creation, source);
    submitFailure = "unavailable";
    const error: unknown = await confirmBacktest(prepared).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toHaveProperty("observe");
    submitFailure = undefined;
    expect((await confirmBacktest(prepared)).run_id).toBe(run);
    expect(posts("/submit")).toHaveLength(2);
    expect(posts("/submit").map((value) => value.command)).toEqual([
        prepared.backtest_command_id,
        prepared.backtest_command_id
    ]);
});
it("an ambiguous Start remains observe-only even after a later NOT_SUBMITTED read", async () => {
    const prepared = await prepareBacktest(creation, source);
    submitFailure = "transport";
    const pending = recovery(await confirmBacktest(prepared).catch((value: unknown) => value));
    submitFailure = undefined;
    await pending.observe().catch(() => null);
    await confirmBacktest(prepared).catch(() => null);
    expect(posts("/submit")).toHaveLength(1);
    expect(pending).not.toHaveProperty("resume");
});
it("creation context rejects a foreign manual revision without using its defaults", async () => {
    vi.mocked(request).mockImplementation(<T>(_path: string, schema: z.ZodType<T>) =>
        Promise.resolve(
            schema.parse({
                ...creation,
                input_defaults: {
                    ...defaults,
                    origin: {
                        ...origin,
                        strategy_revision_fingerprint: "0".repeat(64)
                    }
                }
            })
        )
    );
    await expect(loadCreationContext(origin)).rejects.toThrow();
});
it("queries official source inventory and offers only current available 1-minute Binance sources", async () => {
    const available = {
        is_current_revision: true,
        ...source,
        display_name: "Binance 现货",
        type_id: "binance.spot.market_data",
        new_work_status: "AVAILABLE",
        new_work_unavailable_code: null,
        history_read_policy: "EXACT_SEALED_PROOF",
        time_bar_capability: {
            provider_base_semantic: {
                schema_version: 3,
                formation: {
                    schema_version: 1,
                    kind: "FIXED_DURATION",
                    window_minutes: 1,
                    stride_minutes: 1,
                    alignment: "UTC"
                },
                price_type: "LAST",
                adjustment_policy: "RAW"
            },
            derived_algorithm: null,
            minimum_window_minutes: 1,
            maximum_window_minutes: 1440
        }
    };
    const { expected_type_id: omittedType, instrument_id: omittedInstrument, ...item } = available;
    void omittedType;
    void omittedInstrument;
    vi.mocked(request).mockImplementation(<T>(path: string, schema: z.ZodType<T>) => {
        expect(path).toBe("/api/v2/market-data/sources");
        return Promise.resolve(
            schema.parse({
                schema_version: 1,
                sources: [
                    item,
                    { ...item, is_current_revision: false },
                    {
                        ...item,
                        new_work_status: "UNAVAILABLE",
                        new_work_unavailable_code: "CONTROLLED"
                    },
                    { ...item, type_id: "other.provider" }
                ]
            })
        );
    });
    expect(await loadSources()).toEqual([item]);
});

it.each(["CONDITIONS_CHANGED", "SOURCE_UNAVAILABLE"] as const)(
    "only the correlated explicit %s reply offers return to fresh conditions",
    async (reason) => {
        refusedPrepare = reason;
        const error: unknown = await prepareBacktest(creation, source).catch(
            (value: unknown) => value
        );
        expect(isPreparationNotStarted(error)).toBe(true);
        if (!isPreparationNotStarted(error)) throw new Error("expected the scoped refusal");
        expect(error.message).toContain("这次准备尚未开始");
        expect(error).not.toHaveProperty("observe");
        expect(posts("/backtest/preparations")).toHaveLength(1);
        const original = JSON.parse(
            sessionStorage.getItem(Object.keys(sessionStorage)[0] ?? "") ?? "null"
        ) as { command: string; input: unknown };
        const again: unknown = await prepareBacktest(creation, source).catch(
            (value: unknown) => value
        );
        expect(isPreparationNotStarted(again)).toBe(true);
        expect(posts("/backtest/preparations")).toHaveLength(1);
        expect(await error.reviewConditions()).toBeNull();
        expect(sessionStorage.length).toBe(0);
        refusedPrepare = undefined;
        prepareRelease = "7".repeat(64);
        const fresh = {
            ...creation,
            input_defaults: {
                ...defaults,
                release_manifest_fingerprint: prepareRelease
            }
        };
        const actual = await prepareBacktest(fresh, source);
        expect(actual.command_id).not.toBe(original.command);
        const next = posts("/backtest/preparations")[1];
        expect(next?.body).toMatchObject({
            release_manifest_fingerprint: prepareRelease
        });
        expect(posts("/submit")).toHaveLength(0);
    }
);
it("generic errors, 404 and another attempted prepare cannot clear an old UNKNOWN intent", async () => {
    unknownPrepare = true;
    const first = recovery(
        await prepareBacktest(creation, source).catch((value: unknown) => value)
    );
    const retained = sessionStorage.getItem(Object.keys(sessionStorage)[0] ?? "");
    unknownPrepare = false;
    refusedPrepare = "CONDITIONS_CHANGED";
    const second: unknown = await prepareBacktest(creation, source).catch(
        (value: unknown) => value
    );
    expect(isPreparationNotStarted(second)).toBe(false);
    await first.observe().catch(() => null);
    expect(posts("/backtest/preparations")).toHaveLength(1);
    expect(sessionStorage.getItem(Object.keys(sessionStorage)[0] ?? "")).toBe(retained);
});
it.each(["command", "input", "late-local-intent"])(
    "a %s refusal cannot unlock another request",
    async (kind) => {
        refusedPrepare = "SOURCE_UNAVAILABLE";
        if (kind === "command") refusalMutation = { command_id: future };
        if (kind === "input")
            refusalMutation = {
                input: {
                    ...defaults,
                    release_manifest_fingerprint: "6".repeat(64),
                    source,
                    backtest_command_id: future
                }
            };
        if (kind === "late-local-intent") replaceIntentBeforeRefusal = true;
        const error: unknown = await prepareBacktest(creation, source).catch(
            (value: unknown) => value
        );
        expect(isPreparationNotStarted(error)).toBe(false);
        expect(error).not.toHaveProperty("reviewConditions");
        expect(sessionStorage.length).toBe(1);
        const retained = JSON.parse(
            sessionStorage.getItem(Object.keys(sessionStorage)[0] ?? "") ?? "null"
        ) as Record<string, unknown>;
        expect(retained).not.toHaveProperty("refusal");
        if (kind === "late-local-intent") expect(retained.command).toBe(future);
        expect(posts("/backtest/preparations")).toHaveLength(1);
    }
);
it("a refusal already superseded in local state cannot discard the newer intent", async () => {
    refusedPrepare = "CONDITIONS_CHANGED";
    const error: unknown = await prepareBacktest(creation, source).catch((value: unknown) => value);
    if (!isPreparationNotStarted(error)) throw new Error("expected scoped refusal");
    const key = Object.keys(sessionStorage)[0];
    if (key === undefined) throw new Error("original intent missing");
    const newer = JSON.stringify({ original_is_superseded: true });
    sessionStorage.setItem(key, newer);
    await expect(error.reviewConditions()).rejects.toThrow();
    expect(sessionStorage.getItem(key)).toBe(newer);
});

it("an existing accepted original remains authoritative instead of a later refusal path", async () => {
    accepted = true;
    prepId = "00000000-0000-4000-8000-000000009405";
    refusedPrepare = "CONDITIONS_CHANGED";
    const original = preparationSchema.parse(prep());
    const value = await prepareBacktest({ ...creation, existing_preparations: [original] }, source);
    expect(value).toEqual(original);
    expect(posts("/backtest/preparations")).toHaveLength(0);
    expect(sessionStorage.length).toBe(0);
});

it("a retained refusal consumes exact fresh same-command accepted history without another POST", async () => {
    refusedPrepare = "CONDITIONS_CHANGED";
    const error: unknown = await prepareBacktest(creation, source).catch((value: unknown) => value);
    expect(isPreparationNotStarted(error)).toBe(true);
    const key = Object.keys(sessionStorage)[0] ?? "";
    accepted = true;
    const actual = preparationSchema.parse(prep());
    expect(await prepareBacktest({ ...creation, existing_preparations: [actual] }, source)).toEqual(
        actual
    );
    expect(posts("/backtest/preparations")).toHaveLength(1);
    expect(sessionStorage.getItem(key)).toBeNull();
});
it.each([false, true])(
    "review restores and consumes the later accepted original (run=%s) by normal success",
    async (runAccepted) => {
        refusedPrepare = "SOURCE_UNAVAILABLE";
        const error: unknown = await prepareBacktest(creation, source).catch(
            (value: unknown) => value
        );
        if (!isPreparationNotStarted(error)) throw new Error("expected correlated refusal");
        const key = Object.keys(sessionStorage)[0] ?? "";
        accepted = true;
        submitted = runAccepted;
        const actual = preparationSchema.parse(prep());
        expect(await error.reviewConditions()).toEqual(actual);
        expect(sessionStorage.getItem(key)).toBeNull();
        expect(posts("/backtest/preparations")).toHaveLength(1);
        expect(posts("/submit")).toHaveLength(0);
    }
);
it.each([
    "RESEARCH_PREPARATION_UNAVAILABLE",
    "RESEARCH_PREPARATION_OUTCOME_UNKNOWN",
    "RESEARCH_PREPARATION_NOT_FOUND",
    "NOT_FOUND"
])(
    "a refused invocation with an unverifiable original query (%s) retains its marker",
    async (code) => {
        refusedPrepare = "CONDITIONS_CHANGED";
        const error: unknown = await prepareBacktest(creation, source).catch(
            (value: unknown) => value
        );
        if (!isPreparationNotStarted(error)) throw new Error("expected correlated refusal");
        const key = Object.keys(sessionStorage)[0] ?? "";
        const retained = sessionStorage.getItem(key);
        preparationQueryFailure = new ChatRequestError(code);
        const unknown: unknown = await error.reviewConditions().catch((value: unknown) => value);
        expect(isPreparationNotStarted(unknown)).toBe(false);
        expect(unknown).toHaveProperty("observe");
        expect(sessionStorage.getItem(key)).toBe(retained);
        expect(posts("/backtest/preparations")).toHaveLength(1);
    }
);
it("retained refusal alone does not override a positive original GET when context history is empty", async () => {
    refusedPrepare = "CONDITIONS_CHANGED";
    await prepareBacktest(creation, source).catch(() => null);
    const key = Object.keys(sessionStorage)[0] ?? "";
    accepted = true;
    const actual = preparationSchema.parse(prep());
    expect(await prepareBacktest(creation, source)).toEqual(actual);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(posts("/backtest/preparations")).toHaveLength(1);
});

it("after restoring a completed original Run a new explicit logical prepare is possible for the same origin", async () => {
    refusedPrepare = "CONDITIONS_CHANGED";
    const error: unknown = await prepareBacktest(creation, source).catch((value: unknown) => value);
    if (!isPreparationNotStarted(error)) throw new Error("expected correlated refusal");
    accepted = true;
    submitted = true;
    const original = preparationSchema.parse(prep());
    expect(await error.reviewConditions()).toEqual(original);
    expect(sessionStorage.length).toBe(0);
    refusedPrepare = undefined;
    accepted = false;
    submitted = false;
    const next = await prepareBacktest({ ...creation, existing_preparations: [original] }, source);
    expect(next.command_id).not.toBe(original.command_id);
    expect(next.backtest_command_id).not.toBe(original.backtest_command_id);
    expect(next.run_id).toBeNull();
    expect(posts("/backtest/preparations")).toHaveLength(2);
    expect(posts("/submit")).toHaveLength(0);
});

it("a foreign positive original query cannot consume a correlated refusal marker", async () => {
    refusedPrepare = "SOURCE_UNAVAILABLE";
    const error: unknown = await prepareBacktest(creation, source).catch((value: unknown) => value);
    if (!isPreparationNotStarted(error)) throw new Error("expected correlated refusal");
    const key = Object.keys(sessionStorage)[0] ?? "";
    const retained = sessionStorage.getItem(key);
    accepted = true;
    prepMutation = { command_id: future };
    const unknown: unknown = await error.reviewConditions().catch((value: unknown) => value);
    expect(unknown).toHaveProperty("observe");
    expect(sessionStorage.getItem(key)).toBe(retained);
});
