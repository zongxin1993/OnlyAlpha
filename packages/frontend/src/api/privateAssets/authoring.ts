import { z } from "zod";
import { revision } from "./client";
import type { LocalReadCredentials } from "../marketData/localReadCredentials";
import type { components } from "../research/generated";
const sha = z.string().regex(/^[0-9a-f]{64}$/);
export const factorDraftSchema = revision
    .omit({ revision_fingerprint: true, parent_revision_fingerprint: true, source_sha256: true })
    .extend({ base_revision_fingerprint: sha.nullable() });
const result = z.strictObject({
    draft: factorDraftSchema,
    draft_fingerprint: sha,
    revision: revision.nullable()
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
    revisions: z.array(revision).max(200)
});
const inventory = z.strictObject({
    schema_version: z.literal(1),
    factor_api_version: z.literal(1),
    factor_api_contract_fingerprint: sha,
    entries: z
        .array(
            z.strictObject({
                factor_id: z.string(),
                description: z.string(),
                has_draft: z.boolean(),
                current_revision_fingerprint: sha.nullable()
            })
        )
        .max(200)
});
export type FactorDraft = components["schemas"]["PrivateFactorDraftDto"];
export type FactorAuthoringState = components["schemas"]["PrivateFactorAuthoringStateDto"];
export type FactorAuthoringReceipt = components["schemas"]["PrivateFactorAuthoringReceiptDto"];
export type FactorAuthoringInventory = z.infer<typeof inventory>;
export class FactorAuthoringError extends Error {
    constructor(
        readonly code: string,
        readonly definitive: boolean
    ) {
        super(code);
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
    private accepted(body: unknown, id: string, command: string): FactorAuthoringReceipt {
        const parsed = receipt.safeParse(body);
        if (
            !parsed.success ||
            parsed.data.factor_id !== id ||
            parsed.data.command_id !== command ||
            parsed.data.result.draft.factor_id !== id ||
            (parsed.data.result.revision?.factor_id && parsed.data.result.revision.factor_id !== id)
        )
            throw new FactorAuthoringError("PRIVATE_FACTOR_REPLY_INVALID", false);
        return parsed.data;
    }
    async save(id: string, command: string, expected: string | null, rawDraft: string) {
        const body = await this.request(`/${encodeURIComponent(id)}/draft`, {
            method: "PUT",
            headers: { "Idempotency-Key": command },
            body: `{"draft":${rawDraft},"expected_draft_fingerprint":${JSON.stringify(expected)}}`
        });
        const value = this.accepted(body, id, command);
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
            command
        );
        if (value.result.draft_fingerprint !== expected || value.result.revision === null)
            throw new FactorAuthoringError("PRIVATE_FACTOR_REPLY_INVALID", false);
        return value;
    }
    async command(id: string, command: string) {
        const body = await this.request(`/${encodeURIComponent(id)}/commands/${command}`);
        return body === null ? null : this.accepted(body, id, command);
    }
}
