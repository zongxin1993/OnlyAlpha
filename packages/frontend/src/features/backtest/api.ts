// Product commands remain backend-owned. Local records retain only the original
// Human request; they confer no Freeze, Qualification, Runtime or Run authority.
import { z } from "zod";
import { request, ChatRequestError } from "../factorChat/api";
import { marketDataSourceListSchema } from "../../api/marketData/model";
export { loadModels, interpretResult, loadInterpretation } from "./analysis";

const sha = z.string().regex(/^[0-9a-f]{64}$/);
const uuid = z
    .string()
    .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
const decimal = z
    .string()
    .max(200)
    .regex(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/);
const utc = z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)$/);
const revision = z
    .string()
    .regex(/^(0|[1-9][0-9]*)$/)
    .refine((value) => value.length <= 19 && BigInt(value) <= 9223372036854775807n);
export const sourceSchema = z.strictObject({
    integration_id: z.string().min(1),
    integration_revision_fingerprint: sha,
    expected_type_id: z.literal("binance.spot.market_data"),
    source_id: z.string(),
    environment: z.string(),
    instrument_id: z.literal("BTCUSDT.BINANCE")
});
export type BacktestSource = z.infer<typeof sourceSchema>;
export const originSchema = z.discriminatedUnion("kind", [
    z.strictObject({
        kind: z.literal("MANUAL_STRATEGY"),
        strategy_id: z.string().min(1),
        strategy_revision_fingerprint: sha
    }),
    z.strictObject({
        kind: z.literal("FROZEN_STRATEGY"),
        strategy_fingerprint: sha,
        freeze_relation_fingerprint: sha,
        qualification_decision_fingerprint: sha,
        promotion_fingerprint: sha
    })
]);
export type BacktestOrigin = z.infer<typeof originSchema>;
const readiness = z.strictObject({
    state: z.enum(["VERIFIED", "UNAVAILABLE", "NOT_APPLICABLE"]),
    code: z.string().nullable()
});
export const preparationSchema = z
    .strictObject({
        schema_version: z.literal(2),
        command_id: uuid,
        profile: z.literal("BTC_SPOT_NEXT_OPEN_BACKTEST_V1"),
        origin: originSchema,
        strategy_fingerprint: sha.nullable(),
        validation_fingerprint: sha.nullable(),
        freeze_relation_fingerprint: sha.nullable(),
        qualification_decision_fingerprint: sha.nullable(),
        promotion_fingerprint: sha.nullable(),
        source: sourceSchema,
        revision,
        state: z.enum([
            "ACCEPTED",
            "RUNNING",
            "INPUT_PENDING",
            "READY",
            "BLOCKED",
            "UNKNOWN",
            "CANCEL_REQUESTED",
            "CANCELLED"
        ]),
        phase: z.string(),
        backtest_command_id: uuid,
        reserved_run_id: uuid,
        preparation_fingerprint: sha.nullable(),
        detail: z.unknown(),
        backtest_outcome: z.enum(["UNOBSERVED", "NOT_SUBMITTED", "OUTCOME_UNKNOWN", "ACCEPTED"]),
        readiness,
        run_id: uuid.nullable(),
        accepted_at: utc,
        cleanup: z
            .strictObject({
                state: z.enum(["PENDING", "COMPLETED"]),
                work_id: uuid.optional()
            })
            .optional()
    })
    .superRefine((value, context) => {
        if (
            value.state === "READY" &&
            [
                value.strategy_fingerprint,
                value.freeze_relation_fingerprint,
                value.qualification_decision_fingerprint,
                value.promotion_fingerprint,
                value.preparation_fingerprint
            ].some((pin) => pin === null)
        )
            context.addIssue({
                code: "custom",
                message: "Ready preparation is incomplete"
            });
        if (
            (value.origin.kind === "MANUAL_STRATEGY" &&
                value.state === "READY" &&
                value.validation_fingerprint === null) ||
            (value.origin.kind === "FROZEN_STRATEGY" && value.validation_fingerprint !== null)
        )
            context.addIssue({
                code: "custom",
                message: "Validation does not match the original strategy"
            });
        if (value.run_id !== null && value.run_id !== value.reserved_run_id)
            context.addIssue({
                code: "custom",
                message: "Original Run does not match"
            });
        if (value.backtest_outcome === "ACCEPTED" && value.run_id === null)
            context.addIssue({
                code: "custom",
                message: "Accepted Run is missing"
            });
    });
export type BacktestPreparation = z.infer<typeof preparationSchema>;
const preparationCommandObservationSchema = z.union([
    preparationSchema,
    z.strictObject({
        schema_version: z.literal(2),
        command_id: uuid,
        state: z.literal("NOT_ACCEPTED")
    })
]);
const defaultsSchema = z.strictObject({
    schema_version: z.literal(2),
    profile: z.literal("BTC_SPOT_NEXT_OPEN_BACKTEST_V1"),
    origin: originSchema,
    release_manifest_fingerprint: sha,
    expected_active_generation: sha.nullable(),
    initialize_fresh_runtime: z.literal(false)
});
export const creationSchema = z.strictObject({
    schema_version: z.literal(2),
    strategy_name: z.string().min(1),
    input_defaults: defaultsSchema,
    sample_start_at: z.literal("2025-01-03T00:00:00Z"),
    sample_end_at: z.literal("2025-01-03T12:00:00Z"),
    initial_cash: z.literal("10000"),
    quantity: z.literal("0.01"),
    fee_bps: z.literal(10),
    slippage_bps: z.literal(2),
    limitations: z.array(z.string()),
    existing_preparations: z.array(preparationSchema)
});
export type BacktestCreation = z.infer<typeof creationSchema>;
const inputSchema = defaultsSchema.extend({
    source: sourceSchema,
    backtest_command_id: uuid
});
const prepareRefusalReason = z.enum(["CONDITIONS_CHANGED", "SOURCE_UNAVAILABLE"]);
const prepareRefusalSchema = z.strictObject({
    schema_version: z.literal(2),
    state: z.literal("NOT_ACCEPTED"),
    command_id: uuid,
    input: inputSchema,
    reason: prepareRefusalReason
});
const prepareReplySchema = z.union([preparationSchema, prepareRefusalSchema]);
const workerObservation = z.strictObject({
    state: z.enum(["STARTING", "IDLE", "RUNNING", "UNKNOWN", "UNAVAILABLE", "STOPPED"]),
    code: z.string().optional(),
    run_id: uuid.optional()
});
const runSchema = z.strictObject({
    schema_version: z.literal(1),
    run_id: uuid,
    strategy_fingerprint: sha,
    state: z.enum(["QUEUED", "RUNNING", "CANCEL_REQUESTED", "COMPLETED", "FAILED", "CANCELLED"]),
    revision,
    accepted_at: utc,
    preparation_command_id: uuid.nullable(),
    report_status: z.strictObject({
        state: z.enum(["PENDING", "NOT_CHECKED", "VERIFIED", "NOT_APPLICABLE", "UNAVAILABLE"]),
        code: z.string().nullable()
    }),
    worker_observation: workerObservation.optional()
});
export type BacktestRun = z.infer<typeof runSchema>;
const metrics = z.strictObject({
    initial_equity: decimal,
    final_equity: decimal,
    return_since_start: decimal.nullable(),
    net_pnl: decimal,
    realized_pnl: decimal,
    unrealized_pnl: decimal,
    fees: decimal,
    maximum_drawdown: decimal.nullable(),
    fill_count: z.number().int().nonnegative(),
    roundtrip_count: z.number().int().nonnegative()
});
const sample = z.strictObject({
    instrument: z.string(),
    start_at: utc,
    end_at: utc,
    quantity: decimal,
    rule_observed_at: utc
});
const trade = z.strictObject({
    ordinal: z.number().int().positive(),
    time_ns: z.string().regex(/^[0-9]+$/),
    side: z.enum(["BUY", "SELL"]),
    quantity: decimal,
    price: decimal,
    fee: decimal,
    signal_time_ns: z.string().regex(/^[0-9]+$/),
    signal: z.string(),
    order_id: z.string(),
    trade_id: z.string()
});
export const resultSchema = z.strictObject({
    schema_version: z.literal(1),
    run_id: uuid,
    strategy_fingerprint: sha,
    evidence_fingerprint: sha,
    result_fingerprint: sha,
    determinism_fingerprint: sha,
    state: z.enum(["COMPLETED", "CANCELLED", "FAILED"]),
    sample,
    metrics,
    curve: z.array(
        z.strictObject({
            at_ns: z.string().regex(/^[0-9]+$/),
            nav: decimal,
            drawdown: decimal.nullable()
        })
    ),
    baseline: z
        .strictObject({
            final_equity: decimal,
            net_pnl: decimal,
            return_since_start: decimal
        })
        .nullable(),
    trades: z.array(trade),
    positions: z.array(
        z.strictObject({
            instrument: z.string(),
            quantity: decimal,
            average_price: decimal.nullable(),
            state: z.enum(["OPEN", "CLOSED", "RECONCILING"])
        })
    ),
    limitations: z.array(z.string())
});
export type BacktestResult = z.infer<typeof resultSchema>;
const confirmationSchema = z.strictObject({
    schema_version: z.literal(1),
    backtest_command_id: uuid,
    state: z.enum(["ACCEPTED", "OUTCOME_UNKNOWN"]),
    run_id: uuid.nullable()
});
type Confirmation = z.infer<typeof confirmationSchema>;
function same(left: unknown, right: unknown) {
    return JSON.stringify(left) === JSON.stringify(right);
}
function mismatch() {
    return new Error("当前记录与所选策略不一致，已停止操作。请重新查看原任务。");
}
function failure() {
    return new Error("暂时无法读取当前记录。原策略与回测仍然保留，请重新查看。");
}
async function read<T>(path: string, schema: z.ZodType<T>): Promise<T> {
    try {
        return await request(path, schema);
    } catch {
        throw failure();
    }
}
function requireOperation(value: BacktestPreparation, original: BacktestPreparation) {
    if (
        value.command_id !== original.command_id ||
        value.backtest_command_id !== original.backtest_command_id ||
        value.reserved_run_id !== original.reserved_run_id ||
        !same(value.origin, original.origin) ||
        !same(value.source, original.source) ||
        !same(value.profile, original.profile)
    )
        throw mismatch();
}
class Pending<T = BacktestPreparation> extends Error {
    constructor(readonly observe: () => Promise<T>) {
        super("操作结果尚未确认，正在查询原任务。系统不会重复提交。");
    }
}
export async function loadSources() {
    const value = await read("/api/v2/market-data/sources", marketDataSourceListSchema);
    return value.sources.filter(
        (source) =>
            source.type_id === "binance.spot.market_data" &&
            source.is_current_revision &&
            source.new_work_status === "AVAILABLE" &&
            source.time_bar_capability.minimum_window_minutes <= 1 &&
            source.time_bar_capability.maximum_window_minutes >= 1
    );
}
export async function loadCreationContext(input: BacktestOrigin): Promise<BacktestCreation> {
    const origin = originSchema.parse(input);
    const query = new URLSearchParams(
        origin.kind === "MANUAL_STRATEGY"
            ? {
                  strategy_id: origin.strategy_id,
                  strategy_revision_fingerprint: origin.strategy_revision_fingerprint
              }
            : {
                  strategy_fingerprint: origin.strategy_fingerprint,
                  freeze_relation_fingerprint: origin.freeze_relation_fingerprint,
                  qualification_decision_fingerprint: origin.qualification_decision_fingerprint,
                  promotion_fingerprint: origin.promotion_fingerprint
              }
    );
    const context = await read(
        `/api/v2/backtest/creation-context?${query.toString()}`,
        creationSchema
    );
    if (
        !same(context.input_defaults.origin, origin) ||
        context.existing_preparations.some((value) => !same(value.origin, origin))
    )
        throw mismatch();
    return context;
}
export function loadRuns() {
    return read(
        "/api/v2/backtest/runs",
        z.strictObject({
            schema_version: z.literal(1),
            items: z.array(runSchema)
        })
    );
}
export async function loadRun(id: string): Promise<BacktestRun> {
    uuid.parse(id);
    const value = await read(`/api/v2/backtest/runs/${id}`, runSchema);
    if (value.run_id !== id) throw mismatch();
    return value;
}
export async function loadResult(id: string): Promise<BacktestResult> {
    uuid.parse(id);
    const value = await read(`/api/v2/backtest/runs/${id}/result`, resultSchema);
    if (value.run_id !== id) throw mismatch();
    return value;
}
export async function loadPreparation(id: string): Promise<BacktestPreparation> {
    uuid.parse(id);
    const value = await request(`/api/v2/backtest/preparations/commands/${id}`, preparationSchema);
    if (value.command_id !== id) throw mismatch();
    return value;
}

const prepareIntentSchema = z.strictObject({
    schema_version: z.literal(2),
    command: uuid,
    input: inputSchema,
    refusal: prepareRefusalReason.optional()
});
type PrepareIntent = z.infer<typeof prepareIntentSchema>;
function intentKey(origin: BacktestOrigin) {
    return `onlyalpha.backtest.preparation.v2.${JSON.stringify(origin)}`;
}
export function pendingPreparation(rawOrigin: BacktestOrigin): {
    observe: () => Promise<BacktestPreparation>;
} | null {
    const origin = originSchema.parse(rawOrigin),
        key = intentKey(origin);
    const retained = sessionStorage.getItem(key);
    if (retained === null) return null;
    const observe = async (): Promise<BacktestPreparation> => {
        let intent: PrepareIntent;
        try {
            if (sessionStorage.getItem(key) !== retained) throw mismatch();
            intent = prepareIntentSchema.parse(JSON.parse(retained) as unknown);
            if (!same(intent.input.origin, origin)) throw mismatch();
        } catch {
            throw new Pending(observe);
        }
        let actual: BacktestPreparation | null;
        try {
            actual = await queryRefusedPreparation(intent);
        } catch {
            throw new Pending(observe);
        }
        if (sessionStorage.getItem(key) !== retained) throw new Pending(observe);
        if (actual === null) {
            if (intent.refusal !== undefined) throw notStarted(intent);
            throw new Pending(observe);
        }
        return acceptPreparation(actual, intent);
    };
    return { observe };
}
export class PreparationNotStarted extends Error {
    constructor(
        readonly reviewConditions: () => Promise<BacktestPreparation | null>,
        reason: z.infer<typeof prepareRefusalReason>
    ) {
        super(
            reason === "CONDITIONS_CHANGED"
                ? "应用已更新，这次准备尚未开始。请返回条件重新确认。"
                : "所选数据源暂不可用，这次准备尚未开始。请返回条件检查数据源。"
        );
    }
}
export function isPreparationNotStarted(value: unknown): value is PreparationNotStarted {
    return value instanceof PreparationNotStarted;
}
function notStarted(intent: PrepareIntent): PreparationNotStarted {
    const reason = intent.refusal;
    if (reason === undefined) throw mismatch();
    const key = intentKey(intent.input.origin),
        retained = JSON.stringify(intent);
    return new PreparationNotStarted(async () => {
        if (sessionStorage.getItem(key) !== retained) throw mismatch();
        // A refusal described one HTTP invocation. Positive original authority
        // may since have appeared and always wins over this auxiliary marker.
        const actual = await queryRefusedPreparation(intent);
        if (actual !== null) return acceptPreparation(actual, intent);
        if (sessionStorage.getItem(key) !== retained) throw mismatch();
        // The verified Backtest negative is sufficient here only because the original
        // correlated refusal was retained and this is an explicit user click.
        // This discards auxiliary intent; it never revokes a server Command.
        sessionStorage.removeItem(key);
        return null;
    }, reason);
}
async function queryRefusedPreparation(intent: PrepareIntent): Promise<BacktestPreparation | null> {
    try {
        const observed = await request(
            `/api/v2/backtest/preparations/commands/${intent.command}`,
            preparationCommandObservationSchema
        );
        if (observed.command_id !== intent.command) throw mismatch();
        // Only the successful, strict original-Command observation is None.
        // HTTP errors and every detail/code/message remain uncertain.
        if (observed.state === "NOT_ACCEPTED") return null;
        requireIntent(observed, intent);
        return observed;
    } catch {
        throw new Pending(() => restoreRefusedPreparation(intent));
    }
}
async function restoreRefusedPreparation(intent: PrepareIntent): Promise<BacktestPreparation> {
    const actual = await queryRefusedPreparation(intent);
    if (actual !== null) return acceptPreparation(actual, intent);
    throw notStarted(intent);
}
function refusedPreparation(
    value: z.infer<typeof prepareRefusalSchema>,
    intent: PrepareIntent
): never {
    const key = intentKey(intent.input.origin);
    if (
        value.command_id !== intent.command ||
        !same(value.input, intent.input) ||
        sessionStorage.getItem(key) !== JSON.stringify(intent)
    )
        throw mismatch();
    const refused = { ...intent, refusal: value.reason };
    sessionStorage.setItem(key, JSON.stringify(refused));
    throw notStarted(refused);
}
function requireIntent(value: BacktestPreparation, intent: PrepareIntent) {
    if (
        value.command_id !== intent.command ||
        value.backtest_command_id !== intent.input.backtest_command_id ||
        !same(value.origin, intent.input.origin) ||
        !same(value.source, intent.input.source) ||
        !same(value.profile, intent.input.profile)
    )
        throw mismatch();
}
async function observePreparation(intent: PrepareIntent): Promise<BacktestPreparation> {
    try {
        const value = await loadPreparation(intent.command);
        return acceptPreparation(value, intent);
    } catch {
        throw new Pending(() => observePreparation(intent));
    }
}
function acceptPreparation(value: BacktestPreparation, intent: PrepareIntent): BacktestPreparation {
    requireIntent(value, intent);
    const key = intentKey(intent.input.origin);
    if (sessionStorage.getItem(key) === JSON.stringify(intent)) sessionStorage.removeItem(key);
    return value;
}
async function observeOperation(original: BacktestPreparation): Promise<BacktestPreparation> {
    let actual: BacktestPreparation;
    try {
        actual = await loadPreparation(original.command_id);
    } catch {
        throw new Pending(() => observeOperation(original));
    }
    requireOperation(actual, original);
    return actual;
}
export async function prepareBacktest(
    raw: BacktestCreation,
    rawSource: BacktestSource
): Promise<BacktestPreparation> {
    const context = creationSchema.parse(raw),
        source = sourceSchema.parse(rawSource);
    if (
        context.input_defaults.origin.kind === "FROZEN_STRATEGY" &&
        context.input_defaults.expected_active_generation === null
    )
        throw new Error("回测环境尚未就绪，请重新查看后再准备。");
    const key = intentKey(context.input_defaults.origin);
    const retained = sessionStorage.getItem(key);
    if (retained !== null) {
        const intent = prepareIntentSchema.parse(JSON.parse(retained) as unknown);
        if (intent.refusal !== undefined) {
            const original = context.existing_preparations.find(
                (value) => value.command_id === intent.command
            );
            if (original !== undefined) {
                requireIntent(original, intent);
                return acceptPreparation(original, intent);
            }
            return restoreRefusedPreparation(intent);
        }
        if (
            !same(intent.input.origin, context.input_defaults.origin) ||
            !same(intent.input.source, source) ||
            intent.input.release_manifest_fingerprint !==
                context.input_defaults.release_manifest_fingerprint ||
            intent.input.expected_active_generation !==
                context.input_defaults.expected_active_generation
        )
            throw new Pending(() => observePreparation(intent));
        return observePreparation(intent);
    }
    const exact = context.existing_preparations.filter(
        (value) =>
            same(value.origin, context.input_defaults.origin) &&
            same(value.source, source) &&
            value.state !== "CANCELLED" &&
            value.run_id === null
    );
    if (exact.length > 0) {
        if (exact.length !== 1)
            throw new Error("已有多份准备记录，请从策略记录选择需要继续的一份。");
        const selected = exact[0];
        if (selected === undefined) throw mismatch();
        const original = await loadPreparation(selected.command_id);
        requireOperation(original, selected);
        return original;
    }
    const intent: PrepareIntent = {
        schema_version: 2,
        command: crypto.randomUUID(),
        input: {
            ...context.input_defaults,
            source,
            backtest_command_id: crypto.randomUUID()
        }
    };
    sessionStorage.setItem(key, JSON.stringify(intent));
    try {
        const value = await request(
            "/api/v2/backtest/preparations",
            prepareReplySchema,
            intent.input,
            intent.command
        );
        if (value.state === "NOT_ACCEPTED") return refusedPreparation(value, intent);
        return acceptPreparation(value, intent);
    } catch (error) {
        if (isPreparationNotStarted(error)) throw error;
        return observePreparation(intent);
    }
}
async function observeStart(preparation: BacktestPreparation): Promise<Confirmation> {
    let value: BacktestPreparation;
    try {
        value = await loadPreparation(preparation.command_id);
    } catch {
        throw new Pending(() => observeStart(preparation));
    }
    requireOperation(value, preparation);
    if (value.preparation_fingerprint !== preparation.preparation_fingerprint) throw mismatch();
    if (value.backtest_outcome === "ACCEPTED" && value.run_id === preparation.reserved_run_id)
        return {
            schema_version: 1,
            backtest_command_id: preparation.backtest_command_id,
            state: "ACCEPTED",
            run_id: value.run_id
        };
    throw new Pending(() => observeStart(preparation));
}
export async function confirmBacktest(input: BacktestPreparation): Promise<Confirmation> {
    const value = await loadPreparation(input.command_id);
    requireOperation(value, input);
    if (value.preparation_fingerprint !== input.preparation_fingerprint) throw mismatch();
    if (value.backtest_outcome === "ACCEPTED" && value.run_id === value.reserved_run_id)
        return {
            schema_version: 1,
            backtest_command_id: value.backtest_command_id,
            state: "ACCEPTED",
            run_id: value.run_id
        };
    const marker = `onlyalpha.backtest.submit.v2.${value.command_id}`;
    if (value.backtest_outcome === "OUTCOME_UNKNOWN" || sessionStorage.getItem(marker) !== null)
        throw new Pending(() => observeStart(value));
    if (
        value.state !== "READY" ||
        value.readiness.state !== "VERIFIED" ||
        value.preparation_fingerprint === null ||
        value.backtest_outcome !== "NOT_SUBMITTED"
    )
        throw new Error("请等待回测准备完成并可核验后，再确认开始。");
    sessionStorage.setItem(marker, value.backtest_command_id);
    try {
        const reply = await request(
            `/api/v2/backtest/preparations/${value.command_id}/submit`,
            confirmationSchema,
            {
                schema_version: 1,
                preparation_command_id: value.command_id,
                preparation_fingerprint: value.preparation_fingerprint
            },
            value.backtest_command_id
        );
        if (
            reply.backtest_command_id !== value.backtest_command_id ||
            reply.state !== "ACCEPTED" ||
            reply.run_id !== value.reserved_run_id
        )
            throw mismatch();
        return reply;
    } catch (error) {
        let actual: BacktestPreparation;
        try {
            actual = await loadPreparation(value.command_id);
        } catch {
            throw new Pending(() => observeStart(value));
        }
        requireOperation(actual, value);
        if (actual.preparation_fingerprint !== value.preparation_fingerprint) throw mismatch();
        if (actual.backtest_outcome === "ACCEPTED" && actual.run_id === value.reserved_run_id)
            return {
                schema_version: 1,
                backtest_command_id: value.backtest_command_id,
                state: "ACCEPTED",
                run_id: actual.run_id
            };
        if (
            error instanceof ChatRequestError &&
            error.message === "BACKTEST_SERVICE_UNAVAILABLE" &&
            actual.backtest_outcome === "NOT_SUBMITTED" &&
            actual.run_id === null
        ) {
            sessionStorage.removeItem(marker);
            throw new Error("回测服务暂时不可用，本次尚未开始。恢复后可再次确认同一次回测。", {
                cause: error
            });
        }
        throw new Pending(() => observeStart(value));
    }
}
export async function cancelPreparation(input: BacktestPreparation): Promise<BacktestPreparation> {
    const current = await loadPreparation(input.command_id);
    requireOperation(current, input);
    if (["CANCEL_REQUESTED", "CANCELLED"].includes(current.state)) return current;
    if (current.run_id !== null) throw new Error("回测已经开始，请在回测任务中取消。");
    const storage = `onlyalpha.backtest.cancel-preparation.v2.${current.command_id}`;
    if (sessionStorage.getItem(storage) !== null)
        throw new Pending(() => observeOperation(current));
    const command = crypto.randomUUID();
    sessionStorage.setItem(storage, command);
    try {
        const value = await request(
            `/api/v2/backtest/preparations/${current.command_id}/cancellation`,
            preparationSchema,
            {
                schema_version: 1,
                preparation_command_id: current.command_id,
                expected_revision: current.revision
            },
            command
        );
        requireOperation(value, current);
        return value;
    } catch {
        const value = await observeOperation(current);
        if (["CANCEL_REQUESTED", "CANCELLED"].includes(value.state)) return value;
        throw new Pending(() => observeOperation(current));
    }
}
export async function resumePreparation(input: BacktestPreparation): Promise<BacktestPreparation> {
    const current = await loadPreparation(input.command_id);
    requireOperation(current, input);
    if (!["BLOCKED", "UNKNOWN", "INPUT_PENDING"].includes(current.state)) return current;
    try {
        const value = await request(
            `/api/v2/backtest/preparations/${current.command_id}/resume`,
            preparationSchema,
            {
                schema_version: 1,
                preparation_command_id: current.command_id,
                expected_revision: current.revision
            },
            current.command_id
        );
        requireOperation(value, current);
        return value;
    } catch {
        throw new Pending(() => observeOperation(current));
    }
}
export async function cancelBacktest(input: BacktestRun): Promise<BacktestRun> {
    const current = await loadRun(input.run_id);
    if (current.strategy_fingerprint !== input.strategy_fingerprint) throw mismatch();
    if (["CANCEL_REQUESTED", "CANCELLED", "COMPLETED", "FAILED"].includes(current.state))
        return current;
    const storage = `onlyalpha.backtest.cancel-run.v1.${current.run_id}`;
    const observe = async () => {
        const value = await loadRun(current.run_id);
        if (value.strategy_fingerprint !== current.strategy_fingerprint) throw mismatch();
        return value;
    };
    if (sessionStorage.getItem(storage) !== null) throw new Pending(observe);
    const command = crypto.randomUUID();
    sessionStorage.setItem(storage, command);
    try {
        const value = await request(
            `/api/v2/backtest/runs/${current.run_id}/cancellation`,
            runSchema,
            { schema_version: 1, run_id: current.run_id },
            command
        );
        if (
            value.run_id !== current.run_id ||
            value.strategy_fingerprint !== current.strategy_fingerprint
        )
            throw mismatch();
        return value;
    } catch {
        const value = await observe();
        if (["CANCEL_REQUESTED", "CANCELLED", "COMPLETED", "FAILED"].includes(value.state))
            return value;
        throw new Pending(observe);
    }
}
