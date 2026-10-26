/** Independent stored evidence/observation format guards; no deferred API mock or fallback. */
import { parseBacktestRunId, parseSha256Fingerprint } from "../../domain/research/identity";
import {
    strategySchema,
    backtestRunSchema,
    backtestEvidenceSchema,
    productErrorSchema,
    productHealthSchema
} from "./schemas";

const strategyId = parseSha256Fingerprint("a".repeat(64));
const runId = parseBacktestRunId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
const strategy = {
    schema_version: 1,
    strategy_fingerprint: strategyId,
    revision: { schema_version: 1, display: "immutable revision", parameters: { period: "14" } },
    freeze_relation_fingerprints: ["b".repeat(64)],
    current_stage: "BACKTEST",
    promotion_records: [{ decision: "APPROVED", actor: "fixture-author" }]
};
const run = {
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
const evidence = {
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
const productError = {
    schema_version: 1,
    error: {
        phase: "EVIDENCE_COMMIT",
        code: "BACKTEST_EVIDENCE_UNAVAILABLE",
        detail: "Required Product authority is unavailable"
    }
};

describe("independent stored Product evidence formats", () => {
    it.each([
        { name: "Strategy", schema: strategySchema, payload: strategy },
        { name: "Backtest Run", schema: backtestRunSchema, payload: run },
        { name: "Backtest Evidence", schema: backtestEvidenceSchema, payload: evidence }
    ])("rejects extra authority or wrong schema in $name", ({ schema, payload }) => {
        expect(schema.safeParse(payload).success).toBe(true);
        expect(schema.safeParse({ ...payload, extra_authority: true }).success).toBe(false);
        expect(schema.safeParse({ ...payload, schema_version: 2 }).success).toBe(false);
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

    it("admits optional Run references and failure as transport facts without inventing completion", () => {
        const failed = {
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
        expect(backtestRunSchema.parse(failed)).toEqual(failed);
    });
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
});
