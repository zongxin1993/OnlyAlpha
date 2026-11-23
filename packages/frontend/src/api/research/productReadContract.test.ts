import { parseBacktestRunId, parseSha256Fingerprint } from "../../domain/research/identity";
import { strategySchema, productErrorSchema, productHealthSchema } from "./schemas";

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
const productError = {
    schema_version: 1,
    error: {
        phase: "EVIDENCE_COMMIT",
        code: "BACKTEST_EVIDENCE_UNAVAILABLE",
        detail: "Required Product authority is unavailable"
    }
};

describe("Product read contracts", () => {
    it("rejects malformed Strategy records and extra authority", () => {
        expect(strategySchema.safeParse(strategy).success).toBe(true);
        expect(strategySchema.safeParse({ ...strategy, extra_authority: true }).success).toBe(false);
        expect(strategySchema.safeParse({ ...strategy, schema_version: 2 }).success).toBe(false);
        expect(
            strategySchema.safeParse({ ...strategy, freeze_relation_fingerprints: ["invalid"] })
                .success
        ).toBe(false);
        expect(strategySchema.safeParse({ ...strategy, revision: [] }).success).toBe(false);
    });
    it("requires an exact canonical Backtest Run ID", () => {
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
        }
    });
    it("rejects extra fields in Product errors", () => {
        expect(productErrorSchema.safeParse({ ...productError, unexpected: true }).success).toBe(
            false
        );
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
