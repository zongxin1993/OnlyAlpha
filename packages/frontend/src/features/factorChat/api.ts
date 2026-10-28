import { z } from "zod";
import { factorDraftSchema } from "../../api/privateAssets/authoring";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
export const providerRef = z.strictObject({ integration_id: z.uuid(), revision_fingerprint: sha });
const preview = z.strictObject({
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
export const chatSchema = z.strictObject({
    schema_version: z.literal(1),
    conversation_id: z.uuid(),
    factor_id: z.string(),
    head: sha.nullable(),
    event_count: z.number().int().min(0).max(101),
    provider: providerRef.nullable(),
    messages: z.array(z.strictObject({ role: z.enum(["user", "assistant"]), content: z.string() })),
    preview: preview.nullable(),
    preview_fingerprint: sha.nullable(),
    confirmed: z.boolean(),
    display_confirmed: z.boolean(),
    saved_draft_fingerprint: sha.nullable(),
    saved_display_fingerprint: sha.nullable(),
    status: z.enum(["READY", "OUTCOME_UNKNOWN", "FAILED"])
});
export type Chat = z.infer<typeof chatSchema>;
export const providersSchema = z.strictObject({
    items: z.array(
        z.strictObject({
            integration_id: z.uuid(),
            name: z.string(),
            revision_fingerprint: sha.nullable(),
            lifecycle: z.enum(["ACTIVE", "DISABLED", "ARCHIVED"])
        })
    )
});
export const chatsSchema = z.strictObject({ items: z.array(chatSchema) });
export class ChatRequestError extends Error {
    constructor(
        message: string,
        readonly definitive: boolean
    ) {
        super(message);
    }
}
export async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    body?: object,
    command?: string
): Promise<T> {
    const r = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
            "Content-Type": "application/json",
            ...(command === undefined ? {} : { "Idempotency-Key": command })
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    const data: unknown = await r.json();
    if (!r.ok) {
        const error = z.object({ error: z.object({ code: z.string() }) }).safeParse(data);
        throw new ChatRequestError(
            error.success ? error.data.error.code : "响应不可用，请核对原操作",
            error.success && [400, 401, 403, 404, 409].includes(r.status)
        );
    }
    return schema.parse(data);
}

export const observationSchema = z.strictObject({ accepted: z.boolean(), abandoned: z.boolean() });
export const commandSchema = z.strictObject({
    schema_version: z.literal(1),
    operation: z.enum(["CREATE", "MESSAGE", "CONFIRM"]),
    expected: sha.nullable(),
    provider: providerRef.nullable(),
    text: z.string().nullable(),
    preview_fingerprint: sha.nullable()
});
