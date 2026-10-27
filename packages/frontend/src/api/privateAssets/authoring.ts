import { z } from "zod";
import { revision } from "./client";
import type { LocalReadCredentials } from "../marketData/localReadCredentials";
import type { components } from "../research/generated";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
export const factorDraftSchema = revision
    .omit({ revision_fingerprint: true, parent_revision_fingerprint: true, source_sha256: true })
    .extend({ base_revision_fingerprint: sha.nullable() });
export const displayFieldsSchema = z.strictObject({
    display_name: z.string().min(1),
    usage_summary: z.string().min(1)
});
export const factorDisplaySchema = displayFieldsSchema.extend({
    schema_version: z.literal(1),
    factor_id: z.string(),
    edit_number: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER)
});
const published = z.strictObject({ display_version: z.number().int().min(1).max(200), revision });
const result = z.strictObject({
    draft: factorDraftSchema.nullable(),
    draft_fingerprint: sha.nullable(),
    revision: revision.nullable(),
    display: factorDisplaySchema,
    display_fingerprint: sha,
    display_version: z.number().int().min(1).max(200).nullable()
});
const receipt = z.strictObject({
    schema_version: z.literal(1),
    command_id: z.uuid(),
    factor_id: z.string(),
    result
});
const state = z.strictObject({
    schema_version: z.literal(1),
    factor_id: z.string(),
    current_revision_fingerprint: sha.nullable(),
    draft: factorDraftSchema.nullable(),
    draft_fingerprint: sha.nullable(),
    revisions: z.array(published).max(200),
    display: factorDisplaySchema,
    display_fingerprint: sha
});
const inventory = z.strictObject({
    schema_version: z.literal(1),
    factor_api_version: z.literal(1),
    factor_api_contract_fingerprint: sha,
    new_factor_defaults: displayFieldsSchema,
    entries: z
        .array(
            z.strictObject({
                factor_id: z.string(),
                display: factorDisplaySchema,
                display_fingerprint: sha,
                has_draft: z.boolean(),
                current_revision_fingerprint: sha.nullable(),
                current_display_version: z.number().int().min(1).max(200).nullable()
            })
        )
        .max(200)
});
export type FactorDisplayFields = z.infer<typeof displayFieldsSchema>;
export type FactorCommandKind = "SAVE" | "PUBLISH" | "DISPLAY";
export type FactorDraft = components["schemas"]["PrivateFactorDraftDto"];
export type FactorAuthoringState = components["schemas"]["PrivateFactorAuthoringStateDto"];
export type FactorAuthoringReceipt = components["schemas"]["PrivateFactorAuthoringReceiptDto"];
export type FactorAuthoringInventory = z.infer<typeof inventory>;
export class FactorAuthoringError extends Error {
    constructor(
        readonly code: string,
        readonly definitive: boolean
    ) {
        super(
            code === "PRIVATE_FACTOR_DISPLAY_UNAVAILABLE"
                ? "因子名称和用途信息不可用，暂不能编辑。"
                : code
        );
    }
}
export class FactorAuthoringClient {
    constructor(private readonly credentials: LocalReadCredentials) {}
    private async request(path: string, init: RequestInit = {}) {
        const captured = this.credentials.capture();
        if (!this.credentials.localSession || captured.bearer !== null)
            throw new FactorAuthoringError("PRIVATE_FACTOR_OWNER_REQUIRED", true);
        const headers = new Headers(init.headers);
        headers.set("Accept", "application/json");
        if (init.body !== undefined) headers.set("Content-Type", "application/json");
        try {
            const response = await fetch(`/api/v2/private-assets/factors${path}`, {
                ...init,
                cache: "no-store",
                credentials: "same-origin",
                headers
            });
            const body: unknown = await response.json();
            if (!this.credentials.isCurrent(captured.generation))
                throw new FactorAuthoringError("PRIVATE_FACTOR_SESSION_CHANGED", false);
            if (!response.ok) {
                const parsed = z.object({ error: z.object({ code: z.string() }) }).safeParse(body);
                throw new FactorAuthoringError(
                    parsed.success ? parsed.data.error.code : "PRIVATE_FACTOR_UNAVAILABLE",
                    response.status >= 400 && response.status < 500
                );
            }
            if (response.headers.get("cache-control") !== "no-store")
                throw new FactorAuthoringError("PRIVATE_FACTOR_REPLY_INVALID", false);
            return body;
        } catch (error) {
            if (error instanceof FactorAuthoringError) throw error;
            throw new FactorAuthoringError("PRIVATE_FACTOR_COMMAND_UNKNOWN", false);
        }
    }
    async list() {
        return inventory.parse(await this.request(""));
    }
    async read(id: string): Promise<FactorAuthoringState> {
        const value = state.parse(await this.request(`/${encodeURIComponent(id)}`));
        if (value.factor_id !== id)
            throw new FactorAuthoringError("PRIVATE_FACTOR_REPLY_INVALID", false);
        return value;
    }
    private accepted(
        body: unknown,
        id: string,
        command: string,
        kind: FactorCommandKind
    ): FactorAuthoringReceipt {
        const parsed = receipt.safeParse(body);
        if (
            !parsed.success ||
            parsed.data.factor_id !== id ||
            parsed.data.command_id !== command ||
            parsed.data.result.display.factor_id !== id ||
            (parsed.data.result.draft !== null && parsed.data.result.draft.factor_id !== id) ||
            (parsed.data.result.revision?.factor_id && parsed.data.result.revision.factor_id !== id)
        )
            throw new FactorAuthoringError("PRIVATE_FACTOR_REPLY_INVALID", false);
        const value = parsed.data.result;
        if (
            kind === "DISPLAY"
                ? value.draft !== null ||
                  value.draft_fingerprint !== null ||
                  value.revision !== null ||
                  value.display_version !== null
                : value.draft === null ||
                  value.draft_fingerprint === null ||
                  (kind === "SAVE"
                      ? value.revision !== null || value.display_version !== null
                      : value.revision === null || value.display_version === null)
        )
            throw new FactorAuthoringError("PRIVATE_FACTOR_REPLY_INVALID", false);
        return parsed.data;
    }
    async save(
        id: string,
        command: string,
        expected: string | null,
        rawDraft: string,
        initialDisplay: FactorDisplayFields | null
    ) {
        const body = await this.request(`/${encodeURIComponent(id)}/draft`, {
            method: "PUT",
            headers: { "Idempotency-Key": command },
            body: `{"draft":${rawDraft},"expected_draft_fingerprint":${JSON.stringify(expected)},"initial_display":${JSON.stringify(initialDisplay)}}`
        });
        const value = this.accepted(body, id, command, "SAVE");
        if (value.result.revision !== null)
            throw new FactorAuthoringError("PRIVATE_FACTOR_REPLY_INVALID", false);
        return value;
    }
    async publish(id: string, command: string, expected: string) {
        const value = this.accepted(
            await this.request(`/${encodeURIComponent(id)}/revisions`, {
                method: "POST",
                headers: { "Idempotency-Key": command },
                body: JSON.stringify({ expected_draft_fingerprint: expected })
            }),
            id,
            command,
            "PUBLISH"
        );
        if (value.result.draft_fingerprint !== expected || value.result.revision === null)
            throw new FactorAuthoringError("PRIVATE_FACTOR_REPLY_INVALID", false);
        return value;
    }
    async updateDisplay(id: string, command: string, expected: string, names: FactorDisplayFields) {
        return this.accepted(
            await this.request(`/${encodeURIComponent(id)}/display`, {
                method: "PUT",
                headers: { "Idempotency-Key": command },
                body: JSON.stringify({ ...names, expected_display_fingerprint: expected })
            }),
            id,
            command,
            "DISPLAY"
        );
    }
    async command(id: string, command: string, kind: FactorCommandKind) {
        const body = await this.request(`/${encodeURIComponent(id)}/commands/${command}`);
        return body === null ? null : this.accepted(body, id, command, kind);
    }
}
