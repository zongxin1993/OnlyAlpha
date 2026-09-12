import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import {
    parseBacktestRunId,
    parseResearchRunId,
    parseSha256Fingerprint
} from "../../domain/research/identity";
import { FetchResearchApiClient, type ProductHealthSelector } from "./client";
import { errorMessage, ProductWebError, ResearchWebError } from "./errors";
import type { components } from "./generated";
import {
    backtestEvidenceSchema,
    backtestRunSchema,
    productErrorSchema,
    productHealthSchema,
    strategySchema
} from "./schemas";

const strategyId = parseSha256Fingerprint("a".repeat(64));
const runId = parseBacktestRunId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
const otherRunId = parseBacktestRunId("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
const strategy: components["schemas"]["StrategyDto"] = {
    schema_version: 1,
    strategy_fingerprint: strategyId,
    revision: { schema_version: 1, display: "immutable revision", parameters: { period: "14" } },
    freeze_relation_fingerprints: ["b".repeat(64)],
    current_stage: "BACKTEST",
    promotion_records: [{ decision: "APPROVED", actor: "fixture-author" }]
};
const run: components["schemas"]["BacktestRunDto"] = {
    schema_version: 1,
    run_id: runId,
    state: "COMPLETED",
    revision: 2,
    specification_fingerprint: "c".repeat(64),
    admission_resolution_fingerprint: "d".repeat(64),
    queued_at: "2026-09-01T00:00:00+00:00",
    started_at: "2026-09-01T00:00:01+00:00",
    cancel_requested_at: null,
    finished_at: "2026-09-01T00:00:02+00:00",
    result_fingerprint: "e".repeat(64),
    evidence_fingerprint: "f".repeat(64),
    determinism_fingerprint: "1".repeat(64),
    failure: null
};
const evidence: components["schemas"]["BacktestEvidenceDto"] = {
    schema_version: 1,
    manifest: {
        schema_version: 1,
        backtest_run_id: runId,
        specification_fingerprint: "c".repeat(64),
        admission_resolution_fingerprint: "d".repeat(64),
        strategy_fingerprint: strategyId,
        dataset_binding_fingerprint: "2".repeat(64),
        base_dataset_snapshot_fingerprint: "3".repeat(64),
        market_product_composition_fingerprint: "4".repeat(64),
        portfolio_profile_fingerprint: "5".repeat(64),
        risk_profile_fingerprint: "6".repeat(64),
        execution_profile_fingerprint: "7".repeat(64),
        kernel_semantics_version: "1",
        implementation_fingerprints: ["8".repeat(64)],
        result_fingerprint: "e".repeat(64),
        determinism_fingerprint: "1".repeat(64),
        evidence_fingerprint: "f".repeat(64),
        artifacts: [
            {
                name: "result.json",
                sha256: "9".repeat(64),
                size: 128,
                media_type: "application/json"
            }
        ]
    }
};
const productError: components["schemas"]["ProductErrorEnvelopeDto"] = {
    schema_version: 1,
    error: {
        phase: "EVIDENCE_COMMIT",
        code: "BACKTEST_EVIDENCE_UNAVAILABLE",
        detail: "Required Product authority is unavailable"
    }
};

const reads = [
    {
        name: "Strategy",
        path: `/api/v2/strategies/${strategyId}`,
        read: (client: FetchResearchApiClient, signal?: AbortSignal) =>
            client.getStrategy(strategyId, signal),
        payload: strategy,
        mismatch: { ...strategy, strategy_fingerprint: "0".repeat(64) },
        schema: strategySchema
    },
    {
        name: "Backtest Run",
        path: `/api/v2/backtest/runs/${runId}`,
        read: (client: FetchResearchApiClient, signal?: AbortSignal) =>
            client.getBacktestRun(runId, signal),
        payload: run,
        mismatch: { ...run, run_id: otherRunId },
        schema: backtestRunSchema
    },
    {
        name: "Backtest Evidence",
        path: `/api/v2/backtest/runs/${runId}/evidence`,
        read: (client: FetchResearchApiClient, signal?: AbortSignal) =>
            client.getBacktestEvidence(runId, signal),
        payload: evidence,
        mismatch: { ...evidence, manifest: { ...evidence.manifest, backtest_run_id: otherRunId } },
        schema: backtestEvidenceSchema
    }
];

const server = setupServer();
beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
});
afterEach(() => {
    server.resetHandlers();
    vi.restoreAllMocks();
});
afterAll(() => {
    server.close();
});

function response(body: unknown, status = 200) {
    return new HttpResponse(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" }
    });
}

describe("read-only Product API client admission", () => {
    it.each(reads)(
        "reads $name through its exact GET path and retains admitted transport values",
        async ({ path, read, payload }) => {
            const requests: string[] = [];
            server.use(
                http.get(`*${path}`, ({ request }) => {
                    requests.push(request.method);
                    expect(request.headers.get("accept")).toBe("application/json");
                    expect(request.headers.has("idempotency-key")).toBe(false);
                    expect(new URL(request.url).pathname).toBe(path);
                    return response(payload);
                })
            );
            expect(await read(new FetchResearchApiClient())).toEqual(payload);
            expect(requests).toEqual(["GET"]);
        }
    );

    it.each(reads)(
        "rejects malformed $name responses instead of returning partial facts",
        async ({ path, read, payload, schema }) => {
            expect(schema.safeParse(payload).success).toBe(true);
            expect(schema.safeParse({ ...payload, extra_authority: true }).success).toBe(false);
            server.use(http.get(`*${path}`, () => response({ ...payload, schema_version: 2 })));
            await expect(read(new FetchResearchApiClient())).rejects.toMatchObject({
                code: "CONTRACT_ERROR"
            });
        }
    );

    it.each(reads)(
        "rejects $name returned under the wrong exact identity",
        async ({ path, read, mismatch }) => {
            server.use(http.get(`*${path}`, () => response(mismatch)));
            const requested = read(new FetchResearchApiClient());
            await expect(requested).rejects.toMatchObject({ code: "CONTRACT_ERROR" });
            await expect(requested).rejects.toThrow("identity does not match");
        }
    );

    it.each([400, 404, 409, 500, 503])(
        "preserves Product error code, phase and HTTP %s without Research relabeling",
        async (status) => {
            server.use(
                http.get(`*/api/v2/backtest/runs/${runId}`, () => response(productError, status))
            );
            const failure: unknown = await new FetchResearchApiClient()
                .getBacktestRun(runId)
                .catch((error: unknown) => error);
            expect(failure).toBeInstanceOf(ProductWebError);
            expect(failure).not.toBeInstanceOf(ResearchWebError);
            if (!(failure instanceof ProductWebError))
                throw new Error("Expected the admitted Product error family");
            expect(failure.code).toBe("BACKTEST_EVIDENCE_UNAVAILABLE");
            expect(failure.phase).toBe("EVIDENCE_COMMIT");
            expect(failure.status).toBe(status);
            expect(errorMessage(failure)).toBe(
                "BACKTEST_EVIDENCE_UNAVAILABLE: Required Product authority is unavailable"
            );
        }
    );

    it.each([
        { status: 201, body: strategy },
        { status: 418, body: productError },
        { status: 503, body: { status: "NOT_READY", checks: {} } },
        {
            status: 409,
            body: {
                error: { phase: "COMMAND", code: "RESEARCH_RUN_CONFLICT", detail: "Research only" }
            }
        },
        {
            status: 404,
            body: {
                schema_version: 2,
                code: "RESEARCH_ARTIFACT_NOT_FOUND",
                detail: "Research only"
            }
        },
        {
            status: 400,
            body: {
                schema_version: 1,
                error: { phase: "COMMAND", code: "PRODUCT_REQUEST_INVALID" }
            }
        }
    ])(
        "fails closed on a wrong Product response family or status: $status",
        async ({ status, body }) => {
            server.use(http.get(`*/api/v2/strategies/${strategyId}`, () => response(body, status)));
            await expect(
                new FetchResearchApiClient().getStrategy(strategyId)
            ).rejects.toMatchObject({ code: "CONTRACT_ERROR", status });
        }
    );

    it("does not admit Product or health errors through unchanged Research error contracts", async () => {
        const researchRunId = parseResearchRunId(runId);
        server.use(http.get(`*/api/v2/research/runs/${runId}`, () => response(productError, 503)));
        await expect(new FetchResearchApiClient().getRun(researchRunId)).rejects.toMatchObject({
            code: "CONTRACT_ERROR",
            status: 503
        });
        server.use(
            http.get(`*/api/v2/research/runs/${runId}`, () =>
                response({ status: "NOT_READY", checks: {} }, 503)
            )
        );
        await expect(new FetchResearchApiClient().getRun(researchRunId)).rejects.toMatchObject({
            code: "CONTRACT_ERROR",
            status: 503
        });
        server.use(
            http.get(`*/api/v2/research/runs/${runId}`, () =>
                response(
                    {
                        error: {
                            phase: "COMMAND",
                            code: "RESEARCH_RUN_CONFLICT",
                            detail: "Original Research error"
                        }
                    },
                    409
                )
            )
        );
        await expect(new FetchResearchApiClient().getRun(researchRunId)).rejects.toMatchObject({
            code: "RESEARCH_RUN_CONFLICT",
            phase: "COMMAND",
            status: 409
        });
    });

    it("rejects invalid or unsafe exact identities and integer transport fields", () => {
        expect(parseBacktestRunId(runId)).toBe(runId);
        for (const invalid of [
            "not-an-id",
            runId.toUpperCase(),
            ` ${runId}`,
            "aaaaaaaa-aaaa-1aaa-8aaa-aaaaaaaaaaaa"
        ]) {
            expect(() => parseBacktestRunId(invalid)).toThrow(
                "Backtest Run ID must be an exact canonical UUID4"
            );
            expect(backtestRunSchema.safeParse({ ...run, run_id: invalid }).success).toBe(false);
        }
        for (const invalid of [Number.MAX_SAFE_INTEGER + 1, -1, 1.5, Infinity]) {
            expect(backtestRunSchema.safeParse({ ...run, revision: invalid }).success).toBe(false);
            expect(
                backtestEvidenceSchema.safeParse({
                    ...evidence,
                    manifest: {
                        ...evidence.manifest,
                        artifacts: [
                            {
                                name: "result.json",
                                sha256: "9".repeat(64),
                                size: invalid,
                                media_type: "application/json"
                            }
                        ]
                    }
                }).success
            ).toBe(false);
        }
        expect(
            backtestRunSchema.safeParse({ ...run, specification_fingerprint: "A".repeat(64) })
                .success
        ).toBe(false);
        expect(backtestRunSchema.safeParse({ ...run, queued_at: "not-time" }).success).toBe(false);
        expect(
            strategySchema.safeParse({ ...strategy, freeze_relation_fingerprints: ["invalid"] })
                .success
        ).toBe(false);
        expect(strategySchema.safeParse({ ...strategy, revision: [] }).success).toBe(false);
        expect(
            backtestEvidenceSchema.safeParse({
                ...evidence,
                manifest: { ...evidence.manifest, implementation_fingerprints: ["invalid"] }
            }).success
        ).toBe(false);
        expect(
            backtestEvidenceSchema.safeParse({
                ...evidence,
                manifest: {
                    ...evidence.manifest,
                    artifacts: [
                        {
                            name: "result.json",
                            sha256: "invalid",
                            size: 1,
                            media_type: "application/json"
                        }
                    ]
                }
            }).success
        ).toBe(false);
        expect(productErrorSchema.safeParse({ ...productError, unexpected: true }).success).toBe(
            false
        );
    });

    it("admits optional Run references and failure as transport facts without inventing completion", async () => {
        const failed: components["schemas"]["BacktestRunDto"] = {
            ...run,
            state: "FAILED",
            started_at: null,
            cancel_requested_at: "2026-09-01T00:00:01+00:00",
            result_fingerprint: null,
            evidence_fingerprint: null,
            determinism_fingerprint: null,
            failure: {
                phase: "ADMISSION",
                code: "BACKTEST_INPUT_NOT_ADMITTED",
                detail: "Required input absent"
            }
        };
        server.use(http.get(`*/api/v2/backtest/runs/${runId}`, () => response(failed)));
        expect(await new FetchResearchApiClient().getBacktestRun(runId)).toEqual(failed);
    });
});

describe("official health read boundary", () => {
    it("preserves absent versus null or string reasons without materializing undefined fields", () => {
        const body = { status: "LIVE", checks: { http: "LIVE" } };
        expect(productHealthSchema.parse(body)).not.toHaveProperty("reason");
        expect(productHealthSchema.parse({ ...body, reason: undefined })).not.toHaveProperty(
            "reason"
        );
        expect(productHealthSchema.parse({ ...body, reason: null })).toEqual({
            ...body,
            reason: null
        });
        expect(productHealthSchema.parse({ ...body, reason: "EXPLICIT_REASON" })).toEqual({
            ...body,
            reason: "EXPLICIT_REASON"
        });
    });

    const healthReads: {
        selector: ProductHealthSelector;
        body: components["schemas"]["ResearchHealthDto"];
    }[] = [
        { selector: "live", body: { status: "LIVE", checks: { http: "LIVE" } } },
        {
            selector: "ready",
            body: { status: "READY", checks: { product_kernel: "READY" }, reason: null }
        },
        {
            selector: "execution",
            body: { status: "AVAILABLE", checks: { backtest_worker: "AVAILABLE" } }
        }
    ];

    it.each(healthReads)(
        "reads health/$selector using the same client without changing the declared scope",
        async ({ selector, body }) => {
            server.use(
                http.get(`*/health/${selector}`, ({ request }) => {
                    expect(request.method).toBe("GET");
                    return response(body);
                })
            );
            expect(await new FetchResearchApiClient().getHealth(selector)).toEqual(body);
        }
    );

    it.each<{ selector: ProductHealthSelector; status: string; reason: string }>([
        { selector: "ready", status: "NOT_READY", reason: "KERNEL_RECOVERING" },
        {
            selector: "execution",
            status: "UNKNOWN",
            reason: "BACKTEST_WORKER_CAPACITY_UNAVAILABLE"
        },
        { selector: "execution", status: "DEGRADED", reason: "BACKTEST_WORKER_ABSENT" }
    ])(
        "retains health/$selector HTTP 503 as admitted unhealthy observation $status",
        async ({ selector, status, reason }) => {
            const body = { status, checks: { authority: status }, reason };
            server.use(http.get(`*/health/${selector}`, () => response(body, 503)));
            expect(await new FetchResearchApiClient().getHealth(selector)).toEqual(body);
        }
    );

    it.each([201, 400, 404, 409, 500, 503])(
        "does not accept health/live HTTP %s as a normal health observation",
        async (status) => {
            server.use(
                http.get("*/health/live", () =>
                    response({ status: "LIVE", checks: { http: "LIVE" } }, status)
                )
            );
            await expect(new FetchResearchApiClient().getHealth("live")).rejects.toMatchObject({
                code: "CONTRACT_ERROR",
                status
            });
        }
    );

    it.each([400, 500])(
        "does not broadly bypass unhealthy status admission for readiness HTTP %s",
        async (status) => {
            server.use(
                http.get("*/health/ready", () =>
                    response({ status: "NOT_READY", checks: {} }, status)
                )
            );
            await expect(new FetchResearchApiClient().getHealth("ready")).rejects.toMatchObject({
                code: "CONTRACT_ERROR",
                status
            });
        }
    );

    it.each([
        productError,
        { status: "NOT_READY", checks: { worker: 1 } },
        { status: "NOT_READY", checks: {}, schema_version: 1 },
        { status: "NOT_READY", checks: {}, reason: 1 },
        { checks: {} }
    ])(
        "rejects malformed health 503 DTOs instead of treating them as Product errors",
        async (body) => {
            expect(productHealthSchema.safeParse(body).success).toBe(false);
            server.use(http.get("*/health/ready", () => response(body, 503)));
            await expect(new FetchResearchApiClient().getHealth("ready")).rejects.toMatchObject({
                code: "CONTRACT_ERROR"
            });
        }
    );
});

describe("shared transport failure behavior", () => {
    it.each(reads)(
        "passes AbortSignal for $name and propagates abort without retry or relabeling",
        async ({ path, read }) => {
            const abort = new DOMException("Controlled cancellation", "AbortError");
            const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(abort);
            const controller = new AbortController();
            controller.abort();
            await expect(read(new FetchResearchApiClient(), controller.signal)).rejects.toBe(abort);
            expect(fetch).toHaveBeenCalledWith(
                path,
                expect.objectContaining({ method: "GET", signal: controller.signal })
            );
            expect(fetch).toHaveBeenCalledTimes(1);
        }
    );

    it("forwards the health AbortSignal through the same transport", async () => {
        const abort = new DOMException("Controlled cancellation", "AbortError");
        const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(abort);
        const controller = new AbortController();
        controller.abort();
        await expect(
            new FetchResearchApiClient().getHealth("ready", controller.signal)
        ).rejects.toBe(abort);
        expect(fetch).toHaveBeenCalledWith(
            "/health/ready",
            expect.objectContaining({ method: "GET", signal: controller.signal })
        );
        expect(fetch).toHaveBeenCalledTimes(1);
    });

    it("keeps network failure a transport error without invented Product or health facts", async () => {
        server.use(http.get(`*/api/v2/strategies/${strategyId}`, () => HttpResponse.error()));
        await expect(new FetchResearchApiClient().getStrategy(strategyId)).rejects.toMatchObject({
            code: "TRANSPORT_ERROR"
        });
        server.use(http.get("*/health/execution", () => HttpResponse.error()));
        await expect(new FetchResearchApiClient().getHealth("execution")).rejects.toMatchObject({
            code: "TRANSPORT_ERROR"
        });
    });

    it("rejects invalid JSON from both read families with the observed HTTP status", async () => {
        server.use(
            http.get(
                `*/api/v2/strategies/${strategyId}`,
                () => new HttpResponse("not-json", { status: 200 })
            ),
            http.get("*/health/ready", () => new HttpResponse("not-json", { status: 503 }))
        );
        await expect(new FetchResearchApiClient().getStrategy(strategyId)).rejects.toMatchObject({
            code: "CONTRACT_ERROR",
            status: 200
        });
        await expect(new FetchResearchApiClient().getHealth("ready")).rejects.toMatchObject({
            code: "CONTRACT_ERROR",
            status: 503
        });
    });
});
