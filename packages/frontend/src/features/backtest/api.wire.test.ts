// Golden JSON is exported by the actual Rust Operation::view -> Product DTO
// serializer. These are schema/recovery checks, never executable READY grants.
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import type { z } from "zod";
import type * as ProductRequestApi from "../../api/productRequest";
import { request } from "../../api/productRequest";
import {
    creationSchema,
    loadCreationContext,
    loadPreparation,
    prepareBacktest,
    preparationSchema
} from "./api";
import wire from "./fixtures/preparation-wire-v2.json";

vi.mock("../../api/productRequest", async (original) => ({
    ...(await original<typeof ProductRequestApi>()),
    request: vi.fn()
}));

beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(request).mockReset();
});
afterEach(() => vi.restoreAllMocks());

function context(value: z.infer<typeof preparationSchema>) {
    return creationSchema.parse({
        schema_version: 2,
        strategy_name: "BTC 价量动量",
        input_defaults: {
            schema_version: 2,
            profile: value.profile,
            origin: value.origin,
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
        limitations: ["短样本仅供探索"],
        existing_preparations: []
    });
}
for (const [name, value] of Object.entries(wire)) {
    it(`accepts every complete Rust field in ${name} GET, POST and context history`, async () => {
        const parsed = preparationSchema.parse(value);
        expect(parsed).toEqual(value);
        vi.mocked(request).mockImplementation(<T>(_path: string, schema: z.ZodType<T>) =>
            Promise.resolve(schema.parse(value))
        );
        expect(await loadPreparation(parsed.command_id)).toEqual(value);
        expect(vi.mocked(request).mock.calls[0]?.[0]).toBe(
            `/api/v2/backtest/preparations/commands/${parsed.command_id}`
        );

        vi.mocked(request).mockClear();
        vi.spyOn(crypto, "randomUUID")
            .mockReturnValueOnce(parsed.command_id as ReturnType<typeof crypto.randomUUID>)
            .mockReturnValueOnce(
                parsed.backtest_command_id as ReturnType<typeof crypto.randomUUID>
            );
        const defaults = context(parsed);
        expect(await prepareBacktest(defaults, parsed.source)).toEqual(value);
        expect(vi.mocked(request).mock.calls).toHaveLength(1);
        expect(vi.mocked(request).mock.calls[0]?.[0]).toBe("/api/v2/backtest/preparations");

        const history = { ...defaults, existing_preparations: [value] };
        vi.mocked(request).mockImplementation(<T>(_path: string, schema: z.ZodType<T>) =>
            Promise.resolve(schema.parse(history))
        );
        expect((await loadCreationContext(parsed.origin)).existing_preparations).toEqual([value]);
    });
}
it("keeps the required validation field and origin/state constraints from the owning wire", () => {
    for (const value of Object.values(wire)) {
        const missing = { ...value } as Record<string, unknown>;
        delete missing.validation_fingerprint;
        expect(preparationSchema.safeParse(missing).success).toBe(false);
        expect(
            preparationSchema.safeParse({ ...value, validation_fingerprint: "latest" }).success
        ).toBe(false);
        expect(preparationSchema.safeParse({ ...value, hidden_run_grant: true }).success).toBe(
            false
        );
    }
    expect(
        preparationSchema.safeParse({ ...wire.manual_ready, validation_fingerprint: null }).success
    ).toBe(false);
    for (const value of [wire.frozen_ready, wire.frozen_progress])
        expect(
            preparationSchema.safeParse({ ...value, validation_fingerprint: "8".repeat(64) })
                .success
        ).toBe(false);
    expect(preparationSchema.parse(wire.manual_progress).validation_fingerprint).toBeNull();
});
