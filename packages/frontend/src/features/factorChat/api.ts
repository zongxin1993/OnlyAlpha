import { z } from "zod";
import { factorDraftSchema } from "../../api/privateAssets/authoring";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
const sourceChoice = z.strictObject({
    integration_id: z.uuid(),
    integration_revision_fingerprint: sha,
    expected_type_id: z.string(),
    source_id: z.string(),
    environment: z.string()
});
const utc = z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)$/);
export const studyAdviceSchema = z.strictObject({
    source: sourceChoice.extend({ instrument_id: z.string().min(1) }),
    timeframe_minutes: z.number().int().positive(),
    start_at: utc,
    development_end_at: utc,
    end_at: utc,
    protected_start_at: utc,
    protected_end_at: utc,
    horizon_bars: z.number().int().positive(),
    expected_block_length: z.number().int().positive(),
    replicates: z.number().int().positive(),
    confidence_bps: z.number().int().positive(),
    seed: sha,
    rationale: z.string().min(1)
});
const referenceSchema = z.strictObject({
    command: z.uuid(),
    head: sha,
    fingerprint: sha.nullable(),
    abandoned: z.boolean().optional()
});
export const previewSchema = z.strictObject({
    name: z.string(),
    purpose: z.string(),
    hypothesis: z.string(),
    formula: z.string(),
    expression: z.unknown(),
    dependencies: z.record(z.string(), z.unknown()),
    draft: factorDraftSchema,
    draft_fingerprint: sha,
    execution_admitted: z.literal(false)
});
export const sessionSchema = z.strictObject({
    id: z.uuid(),
    workflow: sha,
    current_workflow: sha.optional(),
    successor: z.uuid().nullable().optional(),
    model_revision: sha,
    head: sha.nullable(),
    consumed: z.number().int(),
    model_call_limit: z.number().int(),
    messages: z.array(z.strictObject({ role: z.enum(["user", "assistant"]), content: z.string() })),
    status: z.enum(["READY", "FAILED", "OUTCOME_UNKNOWN", "WORKFLOW_UNAVAILABLE"]),
    candidate: z.record(z.string(), z.unknown()).nullable(),
    factor_reference: referenceSchema.nullable(),
    study_reference: referenceSchema.nullable(),
    topic: z.enum(["FACTOR", "STUDY"]),
    study: studyAdviceSchema.nullable(),
    execution_admitted: z.literal(false),
    continuation: z
        .strictObject({ parent_session: z.uuid(), parent_head: sha, backend_command: z.uuid() })
        .nullable()
        .optional()
});
export type Chat = z.infer<typeof sessionSchema>;
export const conversationSchema = z.strictObject({
    id: z.uuid(),
    head: sha.nullable(),
    model_revision: sha,
    model: z.strictObject({ name: z.string(), model_id: z.string(), model_version: z.string() }),
    turns: z.array(
        z.strictObject({
            head: sha,
            topic: z.enum(["FACTOR", "STUDY"]),
            user: z.string(),
            assistant: z.string().nullable(),
            status: z.enum(["READY", "FAILED", "OUTCOME_UNKNOWN"]),
            candidate: z.record(z.string(), z.unknown()).nullable(),
            study: studyAdviceSchema.nullable(),
            factor_reference: referenceSchema.nullable(),
            study_reference: referenceSchema.nullable()
        })
    )
});
export type Conversation = z.infer<typeof conversationSchema>;
export const sessionsSchema = z.strictObject({ items: z.array(sessionSchema) });
export const modelSchema = z.strictObject({
    id: z.uuid(),
    owner: z.string(),
    name: z.string(),
    base_url: z.string(),
    model_id: z.string(),
    model_version: z.string(),
    credential_generation: z.string(),
    parent: sha.nullable(),
    revision: sha
});
export type Model = z.infer<typeof modelSchema>;
export const modelsSchema = z.strictObject({ items: z.array(modelSchema) });
export const receiptSchema = z.strictObject({
    schema_version: z.literal(1),
    command_id: z.uuid(),
    operation_fingerprint: sha,
    effect: z.union([
        z.looseObject({ proposal_fingerprint: sha }),
        z.strictObject({ registration_abandoned: z.literal(true) })
    ])
});
export const proposalSchema = z.strictObject({
    schema_version: z.literal(1),
    fingerprint: sha,
    is_current: z.boolean(),
    withdrawn: z.boolean(),
    snapshot: z.looseObject({
        schema_version: z.literal(1),
        owner: z.string(),
        factor_id: z.string(),
        origin: z.looseObject({ session_id: z.uuid(), event_fingerprint: sha }),
        preview: previewSchema
    }),
    confirmation: receiptSchema.nullable()
});
export type Proposal = z.infer<typeof proposalSchema>;
export const studySchema = z.strictObject({
    schema_version: z.literal(1),
    fingerprint: sha,
    is_current: z.boolean(),
    withdrawn: z.boolean(),
    snapshot: z.looseObject({
        schema_version: z.literal(1),
        owner: z.string(),
        factor_proposal_fingerprint: sha,
        origin: z.looseObject({ session_id: z.uuid(), event_fingerprint: sha }),
        advice: studyAdviceSchema
    })
});
export type Study = z.infer<typeof studySchema>;
export const studyContextSchema = z.strictObject({
    schema_version: z.literal(1),
    owner: z.string(),
    service_subject: z.string(),
    factor_proposal_fingerprint: sha,
    factor: previewSchema,
    study_proposal_fingerprint: sha.nullable(),
    sources: z.array(sourceChoice),
    supported_profile: z.looseObject({
        study_grant_id: z.uuid().nullable(),
        study_grant_state: z.enum(["ABSENT", "ACTIVE", "EXPIRED", "REVOKED"]),
        remaining_proposals: z.number().int().nonnegative()
    })
});
export const registrationSchema = z.strictObject({
    status: z.enum([
        "REGISTERED",
        "ABANDONED",
        "OUTCOME_UNKNOWN",
        "BINDING_UNAVAILABLE",
        "REJECTED"
    ]),
    backend_command: z.uuid(),
    receipt: receiptSchema.nullable()
});
export const commandSchema = z.strictObject({
    status: z.enum(["UNKNOWN", "ACCEPTED", "ABANDONED"]),
    outcome: z.record(z.string(), z.unknown()).nullable()
});
export const connectionSchema = z.strictObject({
    schema_version: z.literal(1),
    connection: z.strictObject({
        schema_version: z.literal(1),
        agent_url: z.url(),
        grant_id: z.uuid(),
        service_subject: z.string(),
        credential_sha256: sha
    }),
    grant_state: z.enum(["ABSENT", "ACTIVE", "EXPIRED", "REVOKED"])
});
const accessSchema = z.strictObject({
    schema_version: z.literal(1),
    token: z.string(),
    expires_at: z.number().int(),
    subject: z.string(),
    agent_url: z.url(),
    binding: sha
});
export const accessKey = "onlyalpha.agent.browser-access";
export type Access = z.infer<typeof accessSchema>;
export function savedAccess(): Access | null {
    try {
        return accessSchema.parse(JSON.parse(sessionStorage.getItem(accessKey) ?? "null"));
    } catch {
        return null;
    }
}
export async function connect(): Promise<Access> {
    const access = await request("/api/v2/agent-browser-access", accessSchema, {});
    sessionStorage.setItem(accessKey, JSON.stringify(access));
    return access;
}
export class ChatRequestError extends Error {}

export async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    body?: object,
    command?: string,
    access?: Access,
    method?: "PUT" | "POST"
): Promise<T> {
    const r = await fetch(
        access === undefined ? path : access.agent_url.replace(/\/$/, "") + path,
        {
            method: body === undefined ? "GET" : (method ?? "POST"),
            credentials: access === undefined ? "same-origin" : "omit",
            cache: "no-store",
            headers: {
                "Content-Type": "application/json",
                ...(access === undefined ? {} : { Authorization: "Bearer " + access.token }),
                ...(command === undefined ? {} : { "Idempotency-Key": command })
            },
            ...(body === undefined ? {} : { body: JSON.stringify(body) })
        }
    );
    const data: unknown = await r.json();
    if (!r.ok) {
        const code = z
            .union([
                z.object({ error: z.object({ code: z.string() }) }).transform((v) => v.error.code),
                z.object({ error: z.string() }).transform((v) => v.error),
                z.object({ detail: z.string() }).transform((v) => v.detail)
            ])
            .safeParse(data);
        throw new ChatRequestError(code.success ? code.data : "服务响应不可用，请核对原操作");
    }
    return schema.parse(data);
}
