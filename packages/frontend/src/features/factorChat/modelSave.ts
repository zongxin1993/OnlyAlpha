import { z } from "zod";
import { commandSchema, modelSchema, request, type Access, type Model } from "./api";

const key = "onlyalpha.agent.model-save";
const legacyKey = "onlyalpha.agent.chat.pending";
const locatorSchema = z.strictObject({
    kind: z.literal("model"),
    resource: z.uuid(),
    command: z.uuid(),
    binding: z.string().regex(/^[0-9a-f]{64}$/)
});
const unavailable = "模型设置暂时无法完成，请检查连接后重试。";

// Move only model metadata; research/chat commands keep their original lifecycle.
export function migrateModelSave() {
    const raw = sessionStorage.getItem(legacyKey);
    if (raw === null) return;
    let value: unknown;
    try {
        value = JSON.parse(raw);
    } catch {
        return;
    }
    if (!locatorSchema.safeParse(value).success) return;
    const current = sessionStorage.getItem(key);
    if (current !== null && current !== raw) throw new Error(unavailable);
    sessionStorage.setItem(key, raw);
    if (sessionStorage.getItem(legacyKey) === raw) sessionStorage.removeItem(legacyKey);
}
// A reopened editor continues its unresolved model identity, even when the
// settings list was unavailable. A later explicit Save may change its values.
export function pendingModelResource(access: Access): string | null {
    try {
        migrateModelSave();
        const p = locatorSchema.parse(JSON.parse(sessionStorage.getItem(key) ?? "null"));
        return p.binding === access.binding ? p.resource : null;
    } catch {
        return null;
    }
}
export function beginModelSave(access: Access, resource: string, command: string) {
    migrateModelSave();
    if (sessionStorage.getItem(key) !== null) throw new Error(unavailable);
    sessionStorage.setItem(
        key,
        JSON.stringify({ kind: "model", resource, command, binding: access.binding })
    );
}
export function acceptModelSave(saved: Model, access: Access, resource: string, command: string) {
    if (
        saved.id !== resource ||
        saved.credential_generation !== command ||
        saved.owner !== access.subject
    )
        throw new Error(unavailable);
    const raw = sessionStorage.getItem(key);
    if (raw === null) return;
    const p = locatorSchema.parse(JSON.parse(raw));
    if (p.binding !== access.binding || p.resource !== resource || p.command !== command)
        throw new Error(unavailable);
    sessionStorage.removeItem(key);
}
export async function finishModelSave(access: Access): Promise<Model | null> {
    migrateModelSave();
    const raw = sessionStorage.getItem(key);
    if (raw === null) return null;
    const p = locatorSchema.parse(JSON.parse(raw));
    if (p.binding !== access.binding) throw new Error(unavailable);
    // The owning transaction waits for an in-flight save, returns an accepted
    // receipt, or fences a request that never committed. UNKNOWN is never erased.
    const result = await request(
        `/api/v1/agent/commands/${p.command}/abandon`,
        commandSchema,
        {},
        undefined,
        access
    );
    let saved: Model | null = null;
    if (result.status === "ACCEPTED") {
        saved = modelSchema.parse(result.outcome);
        if (
            saved.id !== p.resource ||
            saved.credential_generation !== p.command ||
            saved.owner !== access.subject
        )
            throw new Error(unavailable);
    } else if (
        result.status !== "ABANDONED" ||
        !z.strictObject({ abandoned: z.literal(true) }).safeParse(result.outcome).success
    ) {
        throw new Error(unavailable);
    }
    const current = sessionStorage.getItem(key);
    if (current !== null && current !== raw) throw new Error(unavailable);
    if (current === raw) sessionStorage.removeItem(key);
    return saved;
}
