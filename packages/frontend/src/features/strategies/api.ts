// Human Product client. Browser intents retain identifiers; every outcome is
// re-read from its original owning command and never inferred from local state.
import { z } from "zod";
import { preparationSchema as backtestPreparationSchema } from "../backtest/api";
const version = z
    .number()
    .int()
    .refine((value) => value === 1);
const sha = z.string().regex(/^[0-9a-f]{64}$/);
const revisionNumber = z.string().regex(/^(?:0|[1-9][0-9]*)$/);
export const draftSchema = z.strictObject({
    schema_version: version,
    strategy_id: z.string().min(1),
    semantic_version: z.string().min(1),
    base_revision_fingerprint: sha.nullable(),
    definition: z.record(z.string(), z.unknown()),
    description: z.string(),
    tags: z.array(z.string())
});
const revisionSchema = z.strictObject({
    schema_version: version,
    strategy_id: z.string().min(1),
    semantic_version: z.string(),
    parent_revision_fingerprint: sha.nullable(),
    definition: z.record(z.string(), z.unknown()),
    definition_fingerprint: sha,
    revision_fingerprint: sha,
    description: z.string(),
    tags: z.array(z.string())
});
const authoringSchema = z.strictObject({
    schema_version: version,
    strategy_id: z.string(),
    current_revision_fingerprint: sha.nullable(),
    draft: draftSchema.nullable(),
    draft_fingerprint: sha.nullable(),
    revisions: z.array(z.unknown())
});
const receiptSchema = z.strictObject({
    schema_version: version,
    command_id: z.uuid(),
    strategy_id: z.string(),
    result: z.strictObject({
        draft: draftSchema,
        draft_fingerprint: sha,
        revision: revisionSchema.nullable()
    })
});
const readiness = z.object({
    state: z
        .string()
        .refine((value) => ["VERIFIED", "UNAVAILABLE", "NOT_APPLICABLE"].includes(value)),
    code: z.string().nullable().optional()
});
const preparationSchema = z
    .object({
        schema_version: version,
        command_id: z.uuid(),
        revision: revisionNumber,
        state: z
            .string()
            .refine((value) =>
                [
                    "ACCEPTED",
                    "RUNNING",
                    "INPUT_PENDING",
                    "READY",
                    "BLOCKED",
                    "UNKNOWN",
                    "CANCEL_REQUESTED",
                    "CANCELLED"
                ].includes(value)
            ),
        phase: z.string(),
        prepared_study_fingerprint: sha.nullable(),
        research_command_id: z.uuid(),
        research_outcome: z.string(),
        run_id: z.uuid().nullable(),
        readiness,
        detail: z.unknown().optional()
    })
    .loose();
const sourceSchema = z.object({ instrument_id: z.string() }).loose();
const creationSchema = z.strictObject({
    schema_version: version,
    factor_name: z.string(),
    formula: z.string(),
    factor_proposal_fingerprint: sha,
    study_proposal_fingerprint: sha,
    draft: draftSchema,
    source: sourceSchema,
    research_context: z.record(z.string(), z.unknown()),
    release_manifest_fingerprint: sha,
    expected_active_generation: sha.nullable(),
    initialize_fresh_runtime: z.boolean(),
    existing_preparations: z.array(preparationSchema)
});
const reportSchema = z.object({
    candidate_fingerprint: sha,
    research_result_fingerprint: sha,
    start_at: z.string(),
    end_at: z.string(),
    observation_count: z.number().int().nonnegative(),
    warmup_bars: z.number().int().nonnegative(),
    node_count: z.number().int().positive(),
    execution_graph_verified: z.boolean(),
    limitations: z.array(z.string())
});
const researchSchema = z.object({
    schema_version: version,
    kind: z.string().optional(),
    run_id: z.uuid(),
    state: z.string(),
    revision: revisionNumber.optional(),
    report_status: z
        .object({
            state: z
                .string()
                .refine((value) => ["VERIFIED", "UNAVAILABLE", "NOT_APPLICABLE"].includes(value)),
            code: z.string().nullable().optional()
        })
        .optional(),
    report: reportSchema.nullable()
});
const confirmationSchema = z.object({
    schema_version: version.optional(),
    research_command_id: z.uuid().optional(),
    state: z.enum(["ACCEPTED", "OUTCOME_UNKNOWN"]).optional(),
    run_id: z.uuid().nullable()
});
const freezeSchema = z.strictObject({
    schema_version: version,
    command_id: z.uuid(),
    strategy_fingerprint: sha,
    freeze_relation_fingerprint: sha,
    accepted_at: z.string(),
    replayed: z.boolean()
});
const freezeInput = z.strictObject({
    research_run_id: z.uuid(),
    candidate_fingerprint: sha,
    comment: z.string().nullable()
});
const freezeCommand = z.strictObject({
    state: z.enum(["NOT_SUBMITTED", "PENDING", "COMPLETED"]),
    request: freezeInput.nullable(),
    result: freezeSchema.nullable()
});
type Creation = z.infer<typeof creationSchema>;
export type Authoring = z.infer<typeof authoringSchema>;
export type StrategyDraft = z.infer<typeof draftSchema>;
type Preparation = z.infer<typeof preparationSchema>;
type Frozen = z.infer<typeof freezeSchema>;
class ResponseFailure extends Error {
    constructor(
        readonly status: number,
        readonly code: string
    ) {
        super("服务暂时无法核实此操作。");
    }
}
class Pending<T> extends Error {
    constructor(readonly observe: () => Promise<T>) {
        super("结果尚未确认，正在核查原操作。");
    }
}
async function http<T>(
    path: string,
    schema: z.ZodType<T>,
    body?: object,
    command?: string,
    method: "POST" | "PUT" = "POST"
): Promise<T> {
    const response = await fetch(path, {
        method: body === undefined ? "GET" : method,
        credentials: "same-origin",
        cache: "no-store",
        headers: {
            Accept: "application/json",
            ...(body === undefined ? {} : { "Content-Type": "application/json" }),
            ...(command === undefined ? {} : { "Idempotency-Key": command })
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    const value: unknown = await response.json();
    if (!response.ok) {
        const envelope = z.object({ error: z.object({ code: z.string() }) }).safeParse(value);
        throw new ResponseFailure(
            response.status,
            envelope.success ? envelope.data.error.code : "REPLY_UNAVAILABLE"
        );
    }
    if (response.headers.get("cache-control") !== "no-store")
        throw new Error("回复暂时无法核验，请稍后重新查看。");
    return schema.parse(value);
}
function same(a: unknown, b: unknown): boolean {
    return JSON.stringify(a) === JSON.stringify(b);
}
function asset(id: string): string {
    return `/api/v2/private-assets/strategies/${encodeURIComponent(id)}`;
}
function saveKey(id: string): string {
    return `onlyalpha.strategy.definition.pending.${id}`;
}
function definitive(error: unknown): boolean {
    return (
        error instanceof ResponseFailure &&
        error.status >= 400 &&
        error.status < 500 &&
        ![408, 425, 429].includes(error.status)
    );
}
export async function loadCreationContext(
    factor: string,
    study: string,
    strategyId?: string
): Promise<Creation> {
    sha.parse(factor);
    sha.parse(study);
    const query = new URLSearchParams({
        factor_proposal_fingerprint: factor,
        study_proposal_fingerprint: study,
        ...(strategyId === undefined ? {} : { strategy_id: strategyId })
    });
    const value = await http(
        `/api/v2/strategy-creation-context?${query.toString()}`,
        creationSchema
    );
    if (
        value.factor_proposal_fingerprint !== factor ||
        value.study_proposal_fingerprint !== study ||
        (strategyId !== undefined && value.draft.strategy_id !== strategyId)
    )
        throw new Error("所选策略资料不一致，请重新查看。");
    return value;
}
export async function loadStrategy(id: string): Promise<Authoring | null> {
    try {
        const value = await http(asset(id), authoringSchema);
        if (value.strategy_id !== id) throw new Error("策略资料不一致。");
        return value;
    } catch (error) {
        if (
            error instanceof ResponseFailure &&
            error.status === 404 &&
            error.code === "PRIVATE_STRATEGY_NOT_FOUND"
        )
            return null;
        throw error;
    }
}
const workflowItem = z.object({
    strategy_id: z.string().min(1),
    authoring: authoringSchema,
    preparations: z.array(preparationSchema),
    backtest_preparations: z.array(backtestPreparationSchema)
});
const workflowSchema = workflowItem.extend({ schema_version: version });
function checkedWorkflow<T extends z.infer<typeof workflowItem>>(
    value: T,
    id = value.strategy_id
): T {
    if (
        value.strategy_id !== id ||
        value.authoring.strategy_id !== id ||
        value.preparations.some(
            (item) => item.strategy_id !== undefined && item.strategy_id !== id
        ) ||
        value.backtest_preparations.some(
            (item) => item.origin.kind === "MANUAL_STRATEGY" && item.origin.strategy_id !== id
        )
    )
        throw new Error("原策略记录暂时无法核验。");
    return value;
}
export async function loadWorkflows() {
    const value = await http(
        "/api/v2/strategy-workflows",
        z.object({ schema_version: version, items: z.array(workflowItem) })
    );
    value.items.forEach((item) => checkedWorkflow(item));
    return value;
}
export async function loadWorkflow(id: string) {
    return checkedWorkflow(
        await http(`/api/v2/strategy-workflows/${encodeURIComponent(id)}`, workflowSchema),
        id
    );
}
const definitionBinding = z.discriminatedUnion("kind", [
    z.strictObject({ kind: z.literal("RESEARCH"), factor: sha, study: sha }),
    z.strictObject({
        kind: z.literal("MANUAL_FACTOR"),
        factor_id: z.string().min(1),
        revision_fingerprint: sha,
        content_fingerprint: sha
    })
]);
export type DefinitionBinding = z.infer<typeof definitionBinding>;
const definitionIntent = z.strictObject({
    schema_version: z.literal(2),
    strategy_id: z.string(),
    binding: definitionBinding,
    draft: draftSchema,
    expected: sha.nullable(),
    save_command: z.uuid(),
    publish_command: z.uuid(),
    phase: z.enum(["SAVE_UNSENT", "SAVE_UNKNOWN", "PUBLISH_UNSENT", "PUBLISH_UNKNOWN"]),
    saved: sha.nullable()
});
type DefinitionIntent = z.infer<typeof definitionIntent>;
// Auxiliary browser intent only: every outcome is still read from the original
// owning commands. This never creates a replacement draft or command identity.
export function pendingManualDefinition(id: string) {
    const retained = sessionStorage.getItem(saveKey(id));
    if (retained === null) return null;
    const intent = definitionIntent.parse(JSON.parse(retained) as unknown);
    if (
        intent.strategy_id !== id ||
        intent.draft.strategy_id !== id ||
        intent.binding.kind !== "MANUAL_FACTOR"
    )
        throw new Error("原策略保存记录暂时无法核验，请从原页面继续查看。");
    return { name: intent.draft.description, observe: () => finishDefinition(intent) };
}
function persistDefinition(intent: DefinitionIntent): void {
    sessionStorage.setItem(saveKey(intent.strategy_id), JSON.stringify(intent));
}
function acceptedDefinition(raw: unknown, intent: DefinitionIntent, publish: boolean) {
    const receipt = receiptSchema.parse(raw);
    if (
        receipt.command_id !== (publish ? intent.publish_command : intent.save_command) ||
        receipt.strategy_id !== intent.strategy_id ||
        !same(receipt.result.draft, intent.draft) ||
        (publish
            ? receipt.result.revision === null || receipt.result.draft_fingerprint !== intent.saved
            : receipt.result.revision !== null)
    )
        throw new Error("原保存回复暂时无法核验。");
    if (
        receipt.result.revision !== null &&
        (receipt.result.revision.strategy_id !== intent.strategy_id ||
            !same(receipt.result.revision.definition, intent.draft.definition) ||
            receipt.result.revision.parent_revision_fingerprint !==
                intent.draft.base_revision_fingerprint)
    )
        throw new Error("原策略版本暂时无法核验。");
    return receipt;
}
async function definitionReceipt(intent: DefinitionIntent, publish: boolean) {
    const command = publish ? intent.publish_command : intent.save_command;
    const raw = await http(`${asset(intent.strategy_id)}/commands/${command}`, z.unknown());
    return raw === null ? null : acceptedDefinition(raw, intent, publish);
}
async function finishDefinition(intent: DefinitionIntent): Promise<Authoring> {
    const resume = () => finishDefinition(intent);
    if (intent.phase === "SAVE_UNSENT" || intent.phase === "SAVE_UNKNOWN") {
        let receipt;
        if (intent.phase === "SAVE_UNSENT") {
            intent.phase = "SAVE_UNKNOWN";
            persistDefinition(intent);
            try {
                receipt = acceptedDefinition(
                    await http(
                        `${asset(intent.strategy_id)}/draft`,
                        z.unknown(),
                        { draft: intent.draft, expected_draft_fingerprint: intent.expected },
                        intent.save_command,
                        "PUT"
                    ),
                    intent,
                    false
                );
            } catch (error) {
                try {
                    receipt = await definitionReceipt(intent, false);
                } catch {
                    throw new Pending(resume);
                }
                if (receipt === null && definitive(error)) {
                    sessionStorage.removeItem(saveKey(intent.strategy_id));
                    throw new Error("策略资料已变化或当前没有保存权限，请重新查看。", {
                        cause: error
                    });
                }
            }
        } else {
            try {
                receipt = await definitionReceipt(intent, false);
            } catch {
                throw new Pending(resume);
            }
        }
        if (receipt == null) throw new Pending(resume);
        intent.saved = receipt.result.draft_fingerprint;
        intent.phase = "PUBLISH_UNSENT";
        persistDefinition(intent);
    }
    let published;
    if (intent.phase === "PUBLISH_UNSENT") {
        intent.phase = "PUBLISH_UNKNOWN";
        persistDefinition(intent);
        try {
            published = acceptedDefinition(
                await http(
                    `${asset(intent.strategy_id)}/revisions`,
                    z.unknown(),
                    { expected_draft_fingerprint: intent.saved },
                    intent.publish_command
                ),
                intent,
                true
            );
        } catch (error) {
            try {
                published = await definitionReceipt(intent, true);
            } catch {
                throw new Pending(resume);
            }
            if (published === null && definitive(error)) {
                sessionStorage.removeItem(saveKey(intent.strategy_id));
                throw new Error("策略版本暂时无法保存，请重新查看已保存定义。", { cause: error });
            }
        }
    } else {
        try {
            published = await definitionReceipt(intent, true);
        } catch {
            throw new Pending(resume);
        }
    }
    if (published?.result.revision == null) throw new Pending(resume);
    let state;
    try {
        state = await loadStrategy(intent.strategy_id);
    } catch {
        throw new Pending(resume);
    }
    if (state?.current_revision_fingerprint !== published.result.revision.revision_fingerprint)
        throw new Pending(resume);
    sessionStorage.removeItem(saveKey(intent.strategy_id));
    return state;
}
export async function saveDefinition(input: unknown): Promise<Authoring> {
    const context = creationSchema.parse(input);
    return saveAuthoredDefinition(context.draft, {
        kind: "RESEARCH",
        factor: context.factor_proposal_fingerprint,
        study: context.study_proposal_fingerprint
    });
}
export async function saveAuthoredDefinition(
    rawDraft: unknown,
    rawBinding: DefinitionBinding
): Promise<Authoring> {
    const draft = draftSchema.parse(rawDraft),
        binding = definitionBinding.parse(rawBinding);
    const key = saveKey(draft.strategy_id);
    const retained = sessionStorage.getItem(key);
    if (retained !== null) {
        const intent = definitionIntent.parse(JSON.parse(retained) as unknown);
        if (
            intent.strategy_id !== draft.strategy_id ||
            !same(intent.binding, binding) ||
            !same(intent.draft.definition, draft.definition)
        )
            throw new Error("请先查看原策略保存结果，再修改策略。");
        return finishDefinition(intent);
    }
    const current = await loadStrategy(draft.strategy_id);
    if (current?.draft != null && !same(current.draft, draft))
        throw new Error("当前策略草稿已经变化，请重新查看后再保存。");
    if (current?.current_revision_fingerprint != null) {
        const selected = current.revisions
            .map((value) => revisionSchema.parse(value))
            .filter((value) => value.revision_fingerprint === current.current_revision_fingerprint);
        if (selected.length !== 1 || !same(selected[0]?.definition, draft.definition))
            throw new Error("已保存策略与当前规则不一致，请重新查看。");
        return current;
    }
    const intent: DefinitionIntent = {
        schema_version: 2,
        strategy_id: draft.strategy_id,
        binding,
        draft,
        expected: current?.draft_fingerprint ?? null,
        save_command: crypto.randomUUID(),
        publish_command: crypto.randomUUID(),
        phase: "SAVE_UNSENT",
        saved: null
    };
    persistDefinition(intent);
    return finishDefinition(intent);
}
export async function loadPreparation(command: string): Promise<Preparation> {
    z.uuid().parse(command);
    const value = await http(
        `/api/v2/research/strategy-preparations/commands/${command}`,
        preparationSchema
    );
    if (value.command_id !== command) throw new Error("原准备记录暂时无法核验。");
    return value;
}
const actionIntent = z.strictObject({
    command: z.uuid(),
    request: z.record(z.string(), z.unknown())
});
async function preparationAction(
    raw: unknown,
    action: "resume" | "cancellation"
): Promise<Preparation> {
    const preparation = preparationSchema.parse(raw);
    if (preparation.run_id !== null || preparation.research_outcome !== "NOT_SUBMITTED")
        throw new Error("请查看原策略研究的实际进度。");
    if (action === "cancellation" && ["CANCEL_REQUESTED", "CANCELLED"].includes(preparation.state))
        return preparation;
    if (
        action === "resume" &&
        !["BLOCKED", "INPUT_PENDING", "UNKNOWN", "ACCEPTED", "RUNNING"].includes(preparation.state)
    )
        throw new Error("请先查看当前准备进度。");
    const key = `onlyalpha.strategy.${action}.pending.${preparation.command_id}`;
    const retained = sessionStorage.getItem(key);
    const intent =
        retained === null
            ? {
                  command: action === "resume" ? preparation.command_id : crypto.randomUUID(),
                  request: {
                      schema_version: 1,
                      preparation_command_id: preparation.command_id,
                      expected_revision: preparation.revision
                  }
              }
            : actionIntent.parse(JSON.parse(retained) as unknown);
    if (
        intent.request.preparation_command_id !== preparation.command_id ||
        (action === "resume" && intent.command !== preparation.command_id)
    )
        throw new Error("请先查看原准备操作的结果。");
    sessionStorage.setItem(key, JSON.stringify(intent));
    const accepted = (value: Preparation, observed: boolean) => {
        if (
            value.command_id !== preparation.command_id ||
            value.research_command_id !== preparation.research_command_id ||
            (action === "cancellation" &&
                !["CANCEL_REQUESTED", "CANCELLED"].includes(value.state)) ||
            (action === "resume" &&
                observed &&
                BigInt(value.revision) <= BigInt(String(intent.request.expected_revision)))
        )
            throw new Error("原准备操作结果尚未确认。");
        if (sessionStorage.getItem(key) === JSON.stringify(intent)) sessionStorage.removeItem(key);
        return value;
    };
    const observe = async (): Promise<Preparation> => {
        try {
            return accepted(await loadPreparation(preparation.command_id), true);
        } catch {
            throw new Pending(observe);
        }
    };
    if (retained !== null) return observe();
    try {
        return accepted(
            await http(
                `/api/v2/research/strategy-preparations/${preparation.command_id}/${action}`,
                preparationSchema,
                intent.request,
                intent.command
            ),
            false
        );
    } catch (error) {
        try {
            return await observe();
        } catch {
            if (definitive(error)) throw new Error("准备操作尚未获准，请重新查看任务进度。");
            throw new Pending(observe);
        }
    }
}
export function resumePreparation(raw: unknown) {
    return preparationAction(raw, "resume");
}
export function cancelPreparation(raw: unknown) {
    return preparationAction(raw, "cancellation");
}
const preparationIntent = z.strictObject({
    command: z.uuid(),
    research_command: z.uuid(),
    request: z.record(z.string(), z.unknown())
});
export async function prepareResearch(raw: unknown, authored: unknown): Promise<Preparation> {
    const context = creationSchema.parse(raw);
    const authoring = authoringSchema.parse(authored);
    if (
        authoring.strategy_id !== context.draft.strategy_id ||
        authoring.current_revision_fingerprint === null
    )
        throw new Error("请先保存当前策略定义。");
    const revisions = authoring.revisions.map((value) => revisionSchema.parse(value));
    const selected = revisions.filter(
        (value) => value.revision_fingerprint === authoring.current_revision_fingerprint
    );
    const revision = selected[0];
    if (
        selected.length !== 1 ||
        revision === undefined ||
        !same(revision.definition, context.draft.definition)
    )
        throw new Error("策略定义已经变化，请重新查看。");
    const source = z
        .strictObject({
            integration_id: z.string(),
            integration_revision_fingerprint: sha,
            expected_type_id: z.literal("binance.spot.market_data"),
            source_id: z.string(),
            environment: z.string(),
            instrument_id: z.literal("BTCUSDT.BINANCE")
        })
        .parse(context.source);
    const request = {
        schema_version: 1,
        profile: "BTC_SPOT_STRATEGY_RESEARCH_V1",
        strategy_id: revision.strategy_id,
        strategy_revision_fingerprint: revision.revision_fingerprint,
        definition_fingerprint: revision.definition_fingerprint,
        context: context.research_context,
        source,
        factor_proposal_fingerprint: context.factor_proposal_fingerprint,
        release_manifest_fingerprint: context.release_manifest_fingerprint,
        expected_active_generation: context.expected_active_generation,
        initialize_fresh_runtime: context.initialize_fresh_runtime
    };
    const key = `onlyalpha.strategy.preparation.pending.${revision.strategy_id}`;
    const retained = sessionStorage.getItem(key);
    const intent =
        retained === null
            ? { command: crypto.randomUUID(), research_command: crypto.randomUUID(), request }
            : preparationIntent.parse(JSON.parse(retained) as unknown);
    if (!same(intent.request, request)) throw new Error("请先查看原研究准备结果，再修改研究条件。");
    // This retains only the original request identity. Acceptance and readiness
    // are always observed from the server, including after a lost POST reply.
    sessionStorage.setItem(key, JSON.stringify(intent));
    const accepted = (value: Preparation): Preparation => {
        if (
            value.command_id !== intent.command ||
            value.research_command_id !== intent.research_command
        )
            throw new Error("准备回复暂时无法核验。");
        sessionStorage.removeItem(key);
        return value;
    };
    const observe = async (): Promise<Preparation> => {
        try {
            return accepted(await loadPreparation(intent.command));
        } catch {
            throw new Pending(observe);
        }
    };
    if (retained !== null) return observe();
    const body = { ...request, research_command_id: intent.research_command };
    try {
        return accepted(
            await http(
                "/api/v2/research/strategy-preparations",
                preparationSchema,
                body,
                intent.command
            )
        );
    } catch (error) {
        try {
            return await observe();
        } catch {
            if (definitive(error)) throw new Error("研究准备未获准，请重新查看当前研究条件。");
            throw new Pending(observe);
        }
    }
}
export async function confirmResearch(raw: unknown) {
    const preparation = preparationSchema.parse(raw);
    if (
        preparation.state !== "READY" ||
        preparation.readiness.state !== "VERIFIED" ||
        preparation.prepared_study_fingerprint === null ||
        preparation.research_outcome !== "NOT_SUBMITTED"
    )
        throw new Error("请等待研究环境完成核验。");
    const body = {
        schema_version: 1,
        preparation_command_id: preparation.command_id,
        prepared_study_fingerprint: preparation.prepared_study_fingerprint
    };
    const observe = async () => {
        const actual = await loadPreparation(preparation.command_id);
        if (
            actual.research_command_id !== preparation.research_command_id ||
            actual.run_id === null ||
            actual.research_outcome !== "ACCEPTED"
        )
            throw new Pending(observe);
        return {
            schema_version: 1,
            research_command_id: actual.research_command_id,
            state: "ACCEPTED" as const,
            run_id: actual.run_id
        };
    };
    try {
        const value = await http(
            `/api/v2/research/strategy-preparations/${preparation.command_id}/submit`,
            confirmationSchema,
            body,
            preparation.research_command_id
        );
        if (
            value.research_command_id !== preparation.research_command_id ||
            value.run_id === null ||
            value.state !== "ACCEPTED"
        )
            return await observe();
        return value;
    } catch (error) {
        if (definitive(error))
            throw new Error("本次研究尚未提交，请重新查看研究环境。", { cause: error });
        try {
            return await observe();
        } catch {
            throw new Pending(observe);
        }
    }
}
export async function loadResearch(run: string) {
    z.uuid().parse(run);
    const value = await http(`/api/v2/research/runs/${run}`, researchSchema);
    if (value.run_id !== run || value.kind !== "PRIVATE_STRATEGY")
        throw new Error("原策略研究暂时无法核验。");
    return value;
}
export async function cancelResearch(raw: unknown) {
    const research = researchSchema.parse(raw);
    if (research.kind !== "PRIVATE_STRATEGY") throw new Error("请查看原策略研究记录。");
    if (["CANCEL_REQUESTED", "CANCELLED", "COMPLETED", "FAILED"].includes(research.state))
        return research;
    const key = `onlyalpha.strategy.cancel-research.pending.${research.run_id}`;
    const retained = sessionStorage.getItem(key);
    const request = { schema_version: 1, run_id: research.run_id };
    const intent =
        retained === null
            ? { command: crypto.randomUUID(), request }
            : actionIntent.parse(JSON.parse(retained) as unknown);
    if (!same(intent.request, request)) throw new Error("请先查看原研究取消结果。");
    sessionStorage.setItem(key, JSON.stringify(intent));
    const accepted = (value: z.infer<typeof researchSchema>) => {
        if (
            value.run_id !== research.run_id ||
            value.kind !== "PRIVATE_STRATEGY" ||
            !["CANCEL_REQUESTED", "CANCELLED", "COMPLETED", "FAILED"].includes(value.state)
        )
            throw new Error("研究取消结果尚未确认。");
        if (sessionStorage.getItem(key) === JSON.stringify(intent)) sessionStorage.removeItem(key);
        return value;
    };
    const observe = async (): Promise<z.infer<typeof researchSchema>> => {
        try {
            return accepted(await loadResearch(research.run_id));
        } catch {
            throw new Pending(observe);
        }
    };
    if (retained !== null) return observe();
    try {
        return accepted(
            await http(
                `/api/v2/research/runs/${research.run_id}/cancellation`,
                researchSchema,
                intent.request,
                intent.command
            )
        );
    } catch (error) {
        try {
            return await observe();
        } catch {
            if (definitive(error)) throw new Error("本次研究取消尚未获准，请重新查看研究进度。");
            throw new Pending(observe);
        }
    }
}
const frozenIntent = z.strictObject({ command: z.uuid(), request: freezeInput });
export async function freezeStrategy(raw: unknown): Promise<Frozen> {
    const research = researchSchema.parse(raw);
    if (
        research.kind !== "PRIVATE_STRATEGY" ||
        research.state !== "COMPLETED" ||
        research.report_status?.state !== "VERIFIED" ||
        research.report?.execution_graph_verified !== true
    )
        throw new Error("完整策略证据尚未通过核验，暂时不能冻结。");
    const key = `onlyalpha.strategy.freeze.pending.${research.run_id}`;
    const retained = sessionStorage.getItem(key);
    const intent =
        retained === null
            ? {
                  command: crypto.randomUUID(),
                  request: {
                      research_run_id: research.run_id,
                      candidate_fingerprint: research.report.candidate_fingerprint,
                      comment: null
                  }
              }
            : frozenIntent.parse(JSON.parse(retained) as unknown);
    if (
        intent.request.research_run_id !== research.run_id ||
        intent.request.candidate_fingerprint !== research.report.candidate_fingerprint
    )
        throw new Error("原冻结对象已变化，请查看原操作结果。");
    sessionStorage.setItem(key, JSON.stringify(intent));
    const accepted = (raw: unknown) => {
        const value = freezeSchema.parse(raw);
        if (value.command_id !== intent.command) throw new Error("原冻结回复暂时无法核验。");
        sessionStorage.removeItem(key);
        return value;
    };
    const observe = async (): Promise<Frozen> => {
        const actual = await http(
            `/api/v2/strategy-freezes/commands/${intent.command}`,
            freezeCommand
        );
        if (!same(actual.request, intent.request)) throw new Pending(observe);
        if (actual.state === "COMPLETED" && actual.result !== null) return accepted(actual.result);
        if (actual.state === "PENDING") {
            try {
                return accepted(
                    await http(
                        `/api/v2/strategy-freezes/commands/${intent.command}/resume`,
                        freezeSchema,
                        intent.request,
                        intent.command
                    )
                );
            } catch {
                throw new Pending(observe);
            }
        }
        throw new Pending(observe);
    };
    if (retained !== null) return observe();
    try {
        return accepted(
            await http("/api/v2/strategy-freezes", freezeSchema, intent.request, intent.command)
        );
    } catch (error) {
        try {
            return await observe();
        } catch {
            if (definitive(error)) throw new Error("当前策略尚未获准冻结，请重新查看完整证据。");
            throw new Pending(observe);
        }
    }
}
