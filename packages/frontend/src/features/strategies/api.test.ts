import { afterEach, expect, it, vi } from "vitest";
import * as authoring from "./api";
import {
    saveDefinition,
    freezeStrategy,
    prepareResearch,
    resumePreparation,
    cancelPreparation,
    cancelResearch,
    loadWorkflows,
    loadWorkflow
} from "./api";
const factor = "a".repeat(64),
    study = "b".repeat(64),
    pin = "c".repeat(64);
const draft = {
    schema_version: 1,
    strategy_id: "private.strategy.btc_momentum",
    semantic_version: "1",
    base_revision_fingerprint: null,
    definition: {},
    description: "价量动量",
    tags: []
};
const context = {
    schema_version: 1,
    factor_name: "价量动量",
    formula: "close",
    factor_proposal_fingerprint: factor,
    study_proposal_fingerprint: study,
    draft,
    source: { instrument_id: "BTCUSDT.BINANCE" },
    research_context: {},
    release_manifest_fingerprint: factor,
    expected_active_generation: factor,
    initialize_fresh_runtime: false,
    existing_preparations: []
};
const revision = {
    schema_version: 1,
    strategy_id: draft.strategy_id,
    semantic_version: "1",
    parent_revision_fingerprint: null,
    definition: {},
    definition_fingerprint: factor,
    revision_fingerprint: pin,
    description: draft.description,
    tags: []
};
const state = {
    schema_version: 1,
    strategy_id: draft.strategy_id,
    draft,
    draft_fingerprint: study,
    current_revision_fingerprint: pin,
    revisions: [revision]
};
const base = `/api/v2/private-assets/strategies/${draft.strategy_id}`;
function reply(body: unknown) {
    return Response.json(body, { headers: { "cache-control": "no-store" } });
}

function requestCommand(init?: RequestInit): string {
    const value = new Headers(init?.headers).get("Idempotency-Key");
    if (value === null) throw new Error("controlled write lacks its original Command");
    return value;
}
function requestBody(init?: RequestInit): unknown {
    if (init?.body === undefined) return null;
    if (typeof init.body !== "string") throw new Error("controlled body must be JSON text");
    return JSON.parse(init.body) as unknown;
}
afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    sessionStorage.clear();
});
it("recovers lost save and publish responses by their original commands without repeated writes", async () => {
    const writes: { path: string; command: string; method: string }[] = [];
    const fetch = vi.fn((path: string, init?: RequestInit) =>
        Promise.resolve().then(() => {
            if (init?.method === "PUT" || init?.method === "POST") {
                writes.push({ path, command: requestCommand(init), method: init.method });
                throw new TypeError("controlled response loss");
            }
            const original = writes.find((w) => path === `${base}/commands/${w.command}`);
            if (original)
                return reply({
                    schema_version: 1,
                    command_id: original.command,
                    strategy_id: draft.strategy_id,
                    result: {
                        draft,
                        draft_fingerprint: study,
                        revision: original.method === "PUT" ? null : revision
                    }
                });
            if (path === base)
                return reply(
                    writes.length < 2
                        ? {
                              ...state,
                              draft: null,
                              draft_fingerprint: null,
                              current_revision_fingerprint: null,
                              revisions: []
                          }
                        : state
                );
            throw new Error(`unexpected path ${path}`);
        })
    );
    vi.stubGlobal("fetch", fetch);
    expect((await saveDefinition(context)).current_revision_fingerprint).toBe(pin);
    expect(writes.map((w) => [w.method, w.path])).toEqual([
        ["PUT", `${base}/draft`],
        ["POST", `${base}/revisions`]
    ]);
    expect(writes[0]?.command).not.toBe(writes[1]?.command);
    for (const write of writes)
        expect(
            fetch.mock.calls.some(([path]) => path === `${base}/commands/${write.command}`)
        ).toBe(true);
});
it("keeps an unresolved original save and observes it again instead of allocating another command", async () => {
    const writes: string[] = [];
    const reads: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (init?.method === "PUT") {
                    writes.push(requestCommand(init));
                    throw new TypeError("offline");
                }
                if (path.includes("/commands/")) {
                    reads.push(path);
                    return reply(null);
                }
                if (path === base)
                    return reply({ ...state, current_revision_fingerprint: null, revisions: [] });
                throw new Error("unexpected write");
            })
        )
    );
    await expect(saveDefinition(context)).rejects.toThrow();
    await expect(saveDefinition(context)).rejects.toThrow();
    expect(writes).toHaveLength(1);
    expect(reads.length).toBeGreaterThanOrEqual(2);
    expect(new Set(reads)).toEqual(new Set([`${base}/commands/${writes[0] ?? ""}`]));
});
it("rejects a foreign original receipt without publishing a replacement revision", async () => {
    let command = "";
    const posted: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (init?.method === "PUT") {
                    command = requestCommand(init);
                    throw new TypeError("offline");
                }
                if (init?.method === "POST") {
                    posted.push(path);
                    throw new Error("must not publish");
                }
                if (path === `${base}/commands/${command}`)
                    return reply({
                        schema_version: 1,
                        command_id: "00000000-0000-4000-8000-000000000099",
                        strategy_id: draft.strategy_id,
                        result: { draft, draft_fingerprint: study, revision: null }
                    });
                if (path === base)
                    return reply({ ...state, current_revision_fingerprint: null, revisions: [] });
                throw new Error("unexpected path");
            })
        )
    );
    await expect(saveDefinition(context)).rejects.toThrow();
    expect(posted).toEqual([]);
});
it("recovers only the original prepared Freeze and never freezes an unverified report", async () => {
    const run = "00000000-0000-4000-8000-000000000002";
    const report = {
        candidate_fingerprint: factor,
        research_result_fingerprint: study,
        start_at: "2025-01-02T12:00:00Z",
        end_at: "2025-01-03T00:00:00Z",
        observation_count: 720,
        warmup_bars: 20,
        node_count: 6,
        execution_graph_verified: true,
        limitations: []
    };
    const research = {
        schema_version: 1,
        kind: "PRIVATE_STRATEGY",
        run_id: run,
        state: "COMPLETED",
        revision: "2",
        report_status: { state: "VERIFIED" },
        report
    };
    const calls: { path: string; command: string | null; body: unknown }[] = [];
    let command = "";
    const request = { research_run_id: run, candidate_fingerprint: factor, comment: null };
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                calls.push({
                    path,
                    command: new Headers(init?.headers).get("Idempotency-Key"),
                    body: requestBody(init)
                });
                if (path === "/api/v2/strategy-freezes") {
                    command = requestCommand(init);
                    throw new TypeError("offline");
                }
                if (path === `/api/v2/strategy-freezes/commands/${command}`)
                    return reply({ state: "PENDING", request, result: null });
                if (path === `/api/v2/strategy-freezes/commands/${command}/resume`)
                    return reply({
                        schema_version: 1,
                        command_id: command,
                        strategy_fingerprint: pin,
                        freeze_relation_fingerprint: study,
                        accepted_at: "2026-11-02T00:00:00Z",
                        replayed: true
                    });
                throw new Error("unexpected path");
            })
        )
    );
    expect((await freezeStrategy(research)).strategy_fingerprint).toBe(pin);
    expect(calls.filter((c) => c.path === "/api/v2/strategy-freezes")).toHaveLength(1);
    const resumed = calls.find((c) => c.path.endsWith("/resume"));
    expect(resumed?.command).toBe(command);
    expect(resumed?.body).toEqual(request);
    const count = calls.length;
    await expect(
        freezeStrategy({ ...research, report_status: { state: "UNAVAILABLE" } })
    ).rejects.toThrow();
    expect(calls).toHaveLength(count);
});

it("retains the original unresolved preparation across another call without a second research identity", async () => {
    const selected = {
        ...context,
        source: {
            integration_id: "00000000-0000-4000-8000-000000000011",
            integration_revision_fingerprint: factor,
            expected_type_id: "binance.spot.market_data",
            source_id: "binance.spot",
            environment: "LIVE",
            instrument_id: "BTCUSDT.BINANCE"
        }
    };
    const writes: string[] = [];
    const reads: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (path === "/api/v2/research/strategy-preparations") {
                    writes.push(requestCommand(init));
                    throw new TypeError("controlled response loss");
                }
                reads.push(path);
                return Response.json(
                    { error: { code: "RESEARCH_PREPARATION_UNAVAILABLE" } },
                    { status: 503, headers: { "cache-control": "no-store" } }
                );
            })
        )
    );
    await expect(prepareResearch(selected, state)).rejects.toThrow();
    await expect(prepareResearch(selected, state)).rejects.toThrow();
    expect(writes).toHaveLength(1);
    expect(new Set(reads)).toEqual(
        new Set([`/api/v2/research/strategy-preparations/commands/${writes[0] ?? ""}`])
    );
});

const preparationCommand = "00000000-0000-4000-8000-000000000031";
const researchCommand = "00000000-0000-4000-8000-000000000032";
const pendingPreparation = {
    schema_version: 1,
    command_id: preparationCommand,
    revision: "9007199254740993",
    state: "INPUT_PENDING",
    phase: "ACQUISITION",
    prepared_study_fingerprint: null,
    research_command_id: researchCommand,
    research_outcome: "NOT_SUBMITTED",
    run_id: null,
    readiness: { state: "NOT_APPLICABLE", code: null }
};
it("continues the original preparation with its exact revision and observes a lost reply", async () => {
    const calls: { path: string; command: string | null; body: unknown }[] = [];
    const resumed = {
        ...pendingPreparation,
        revision: "9007199254740994",
        state: "RUNNING",
        phase: "ACQUISITION"
    };
    const identities = vi.spyOn(crypto, "randomUUID");
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                calls.push({
                    path,
                    command: new Headers(init?.headers).get("Idempotency-Key"),
                    body: requestBody(init)
                });
                if (path === `/api/v2/research/strategy-preparations/${preparationCommand}/resume`)
                    throw new TypeError("controlled response loss");
                if (
                    path === `/api/v2/research/strategy-preparations/commands/${preparationCommand}`
                )
                    return reply(resumed);
                throw new Error("unexpected new preparation");
            })
        )
    );
    expect((await resumePreparation(pendingPreparation)).state).toBe("RUNNING");
    expect(calls.filter((value) => value.body !== null)).toEqual([
        {
            path: `/api/v2/research/strategy-preparations/${preparationCommand}/resume`,
            command: preparationCommand,
            body: {
                schema_version: 1,
                preparation_command_id: preparationCommand,
                expected_revision: "9007199254740993"
            }
        }
    ]);
    expect(calls.at(-1)?.path).toBe(
        `/api/v2/research/strategy-preparations/commands/${preparationCommand}`
    );
    expect(identities).not.toHaveBeenCalled();
    identities.mockRestore();
});
it("keeps an unresolved preparation cancellation and queries the original task without a second write", async () => {
    const writes: { path: string; command: string | null; body: unknown }[] = [];
    const reads: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (init?.method === "POST") {
                    writes.push({
                        path,
                        command: new Headers(init.headers).get("Idempotency-Key"),
                        body: requestBody(init)
                    });
                    throw new TypeError("controlled response loss");
                }
                reads.push(path);
                return Response.json(
                    { error: { code: "RESEARCH_PREPARATION_UNAVAILABLE" } },
                    { status: 503, headers: { "cache-control": "no-store" } }
                );
            })
        )
    );
    await expect(cancelPreparation(pendingPreparation)).rejects.toThrow();
    await expect(cancelPreparation(pendingPreparation)).rejects.toThrow();
    expect(writes).toHaveLength(1);
    expect(writes[0]?.path).toBe(
        `/api/v2/research/strategy-preparations/${preparationCommand}/cancellation`
    );
    expect(writes[0]?.command).toBeTruthy();
    expect(writes[0]?.command).not.toBe(preparationCommand);
    expect(writes[0]?.body).toEqual({
        schema_version: 1,
        preparation_command_id: preparationCommand,
        expected_revision: "9007199254740993"
    });
    expect(new Set(reads)).toEqual(
        new Set([`/api/v2/research/strategy-preparations/commands/${preparationCommand}`])
    );
});
it("keeps an unresolved research cancellation bound to its original run", async () => {
    const run = "00000000-0000-4000-8000-000000000033";
    const research = {
        schema_version: 1,
        kind: "PRIVATE_STRATEGY",
        run_id: run,
        state: "RUNNING",
        revision: "3",
        report_status: { state: "NOT_APPLICABLE" },
        report: null
    };
    const writes: { path: string; command: string | null; body: unknown }[] = [];
    const reads: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (init?.method === "POST") {
                    writes.push({
                        path,
                        command: new Headers(init.headers).get("Idempotency-Key"),
                        body: requestBody(init)
                    });
                    throw new TypeError("controlled response loss");
                }
                reads.push(path);
                return Response.json(
                    { error: { code: "RESEARCH_UNAVAILABLE" } },
                    { status: 503, headers: { "cache-control": "no-store" } }
                );
            })
        )
    );
    await expect(cancelResearch(research)).rejects.toThrow();
    await expect(cancelResearch(research)).rejects.toThrow();
    expect(writes).toHaveLength(1);
    expect(writes[0]?.path).toBe(`/api/v2/research/runs/${run}/cancellation`);
    expect(writes[0]?.command).toBeTruthy();
    expect(writes[0]?.body).toEqual({ schema_version: 1, run_id: run });
    expect(new Set(reads)).toEqual(new Set([`/api/v2/research/runs/${run}`]));
});
it("reads workflow history from the owning query and rejects a foreign strategy detail", async () => {
    const history = {
        schema_version: 1,
        strategy_id: draft.strategy_id,
        authoring: state,
        preparations: [pendingPreparation],
        backtest_preparations: []
    };
    const reads: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                expect(init?.method).toBe("GET");
                reads.push(path);
                if (path === "/api/v2/strategy-workflows")
                    return reply({
                        schema_version: 1,
                        items: [
                            {
                                strategy_id: history.strategy_id,
                                authoring: history.authoring,
                                preparations: history.preparations,
                                backtest_preparations: history.backtest_preparations
                            }
                        ]
                    });
                return reply({ ...history, strategy_id: "private.strategy.other" });
            })
        )
    );
    expect((await loadWorkflows()).items[0]?.strategy_id).toBe(draft.strategy_id);
    await expect(loadWorkflow(draft.strategy_id)).rejects.toThrow();
    expect(reads).toEqual([
        "/api/v2/strategy-workflows",
        `/api/v2/strategy-workflows/${draft.strategy_id}`
    ]);
});

const manualSave = "00000000-0000-4000-8000-000000000141";
const manualPublish = "00000000-0000-4000-8000-000000000142";
function retainedManual(phase: "SAVE_UNKNOWN" | "PUBLISH_UNKNOWN") {
    return {
        schema_version: 2,
        strategy_id: draft.strategy_id,
        binding: {
            kind: "MANUAL_FACTOR",
            factor_id: "private.factor.momentum",
            revision_fingerprint: factor,
            content_fingerprint: study
        },
        draft,
        expected: null,
        save_command: manualSave,
        publish_command: manualPublish,
        phase,
        saved: phase === "PUBLISH_UNKNOWN" ? study : null
    };
}
function retainManual(value: ReturnType<typeof retainedManual>) {
    sessionStorage.setItem(
        `onlyalpha.strategy.definition.pending.${draft.strategy_id}`,
        JSON.stringify(value)
    );
}
it("restores the original Manual publication intent and observes exact receipts without any repeated write", async () => {
    retainManual(retainedManual("PUBLISH_UNKNOWN"));
    const reads: string[] = [];
    const identities = vi.spyOn(crypto, "randomUUID");
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                expect(init?.method).toBe("GET");
                reads.push(path);
                if (path === `${base}/commands/${manualPublish}`)
                    return reply({
                        schema_version: 1,
                        command_id: manualPublish,
                        strategy_id: draft.strategy_id,
                        result: { draft, draft_fingerprint: study, revision }
                    });
                if (path === base) return reply(state);
                throw new Error("recovery must observe the original publication identity");
            })
        )
    );
    const pending = authoring.pendingManualDefinition(draft.strategy_id);
    expect(pending?.name).toBe(draft.description);
    expect(reads).toHaveLength(0);
    expect(await pending?.observe()).toEqual(state);
    expect(reads).toEqual([`${base}/commands/${manualPublish}`, base]);
    expect(identities).not.toHaveBeenCalled();
    expect(
        sessionStorage.getItem(`onlyalpha.strategy.definition.pending.${draft.strategy_id}`)
    ).toBeNull();
});
it("keeps an unknown original Manual save read-only, then first publishes with its already reserved command", async () => {
    retainManual(retainedManual("SAVE_UNKNOWN"));
    let saveAccepted = false;
    const writes: { path: string; command: string; method: string }[] = [];
    const reads: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((path: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (init?.method === "POST" || init?.method === "PUT") {
                    writes.push({ path, command: requestCommand(init), method: init.method });
                    expect(path).toBe(`${base}/revisions`);
                    expect(requestCommand(init)).toBe(manualPublish);
                    expect(init.method).toBe("POST");
                    return reply({
                        schema_version: 1,
                        command_id: manualPublish,
                        strategy_id: draft.strategy_id,
                        result: { draft, draft_fingerprint: study, revision }
                    });
                }
                reads.push(path);
                if (path === `${base}/commands/${manualSave}`)
                    return reply(
                        saveAccepted
                            ? {
                                  schema_version: 1,
                                  command_id: manualSave,
                                  strategy_id: draft.strategy_id,
                                  result: { draft, draft_fingerprint: study, revision: null }
                              }
                            : null
                    );
                if (path === base) return reply(state);
                throw new Error("recovery must not search a new strategy identity");
            })
        )
    );
    const pending = authoring.pendingManualDefinition(draft.strategy_id);
    expect(pending).not.toBeNull();
    const unknown = await pending?.observe().catch((error: unknown) => error);
    expect(unknown).toHaveProperty("observe");
    expect(writes).toHaveLength(0);
    await pending?.observe().catch(() => null);
    expect(reads).toEqual([`${base}/commands/${manualSave}`, `${base}/commands/${manualSave}`]);
    expect(writes).toHaveLength(0);
    saveAccepted = true;
    expect(await pending?.observe()).toEqual(state);
    expect(writes).toEqual([{ path: `${base}/revisions`, command: manualPublish, method: "POST" }]);
});
it.each(["intent-id", "draft-id", "other-flow"])(
    "rejects a malformed %s pending locator without clearing or submitting it",
    (fault) => {
        const original = retainedManual("SAVE_UNKNOWN");
        const damaged =
            fault === "intent-id"
                ? { ...original, strategy_id: "private.strategy.other" }
                : fault === "draft-id"
                  ? { ...original, draft: { ...draft, strategy_id: "private.strategy.other" } }
                  : { ...original, binding: { kind: "RESEARCH", factor, study } };
        const raw = JSON.stringify(damaged);
        sessionStorage.setItem(`onlyalpha.strategy.definition.pending.${draft.strategy_id}`, raw);
        const fetch = vi.fn();
        vi.stubGlobal("fetch", fetch);
        expect(() => authoring.pendingManualDefinition(draft.strategy_id)).toThrow();
        expect(fetch).not.toHaveBeenCalled();
        expect(
            sessionStorage.getItem(`onlyalpha.strategy.definition.pending.${draft.strategy_id}`)
        ).toBe(raw);
    }
);
