import type { z } from "zod";
import type {
    Integration,
    IntegrationCommandResponse,
    IntegrationDraft,
    IntegrationOperationalStatus,
    IntegrationProbeAttempt,
    IntegrationRevisionSummary,
    IntegrationSummary,
    IntegrationType
} from "./model";
import { schemas } from "./model";

export class IntegrationWebError extends Error {
    constructor(
        readonly code: string,
        message: string,
        readonly status?: number
    ) {
        super(message);
        this.name = "IntegrationWebError";
    }
}

export interface IntegrationApiClient {
    listTypes(signal?: AbortSignal): Promise<readonly IntegrationType[]>;
    listDataSources(signal?: AbortSignal): Promise<readonly IntegrationSummary[]>;
    createIntegration(
        value: { integration_id: string; type_id: string; display_name: string },
        commandId: string
    ): Promise<IntegrationCommandResponse>;
    getIntegration(id: string, signal?: AbortSignal): Promise<Integration>;
    getDraft(id: string, signal?: AbortSignal): Promise<IntegrationDraft>;
    updateDraft(
        id: string,
        value: {
            expected_draft_version: number;
            public_configuration: Record<string, unknown>;
            probe_configuration: Record<string, unknown> | null;
        },
        commandId: string
    ): Promise<IntegrationCommandResponse>;
    setSecret(
        id: string,
        fieldId: string,
        draftVersion: number,
        secret: string,
        commandId: string
    ): Promise<IntegrationCommandResponse>;
    clearSecret(
        id: string,
        fieldId: string,
        draftVersion: number,
        commandId: string
    ): Promise<IntegrationCommandResponse>;
    resetDraftContract(
        id: string,
        draftVersion: number,
        commandId: string
    ): Promise<IntegrationCommandResponse>;
    publish(
        id: string,
        draftVersion: number,
        commandId: string
    ): Promise<IntegrationCommandResponse>;
    setLifecycle(
        id: string,
        current: string,
        next: string,
        commandId: string
    ): Promise<IntegrationCommandResponse>;
    getOperationalStatus(id: string, signal?: AbortSignal): Promise<IntegrationOperationalStatus>;
    probe(id: string, revision: string): Promise<IntegrationProbeAttempt>;
    listProbeAttempts(
        id: string,
        signal?: AbortSignal
    ): Promise<readonly IntegrationProbeAttempt[]>;
    listRevisions(id: string, signal?: AbortSignal): Promise<readonly IntegrationRevisionSummary[]>;
}

async function request<T>(schema: z.ZodType<T>, url: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
        const headers = new Headers(init.headers);
        headers.set("Accept", "application/json");
        headers.set("Content-Type", "application/json");
        response = await fetch(url, {
            ...init,
            headers
        });
    } catch {
        throw new IntegrationWebError("TRANSPORT_ERROR", "Integration API is unavailable");
    }
    let body: unknown;
    try {
        body = await response.json();
    } catch {
        throw new IntegrationWebError(
            "CONTRACT_ERROR",
            "Integration API returned invalid JSON",
            response.status
        );
    }
    if (!response.ok) {
        const admitted = schemas.error.safeParse(body);
        if (!admitted.success)
            throw new IntegrationWebError(
                "CONTRACT_ERROR",
                "Integration error response violates contract",
                response.status
            );
        throw new IntegrationWebError(
            admitted.data.error.code,
            admitted.data.error.detail,
            response.status
        );
    }
    const admitted = schema.safeParse(body);
    if (!admitted.success)
        throw new IntegrationWebError(
            "CONTRACT_ERROR",
            "Integration success response violates contract",
            response.status
        );
    return admitted.data;
}

const body = (value: object): string => JSON.stringify({ schema_version: 1, ...value });
const command = (commandId: string): HeadersInit => ({ "Idempotency-Key": commandId });
const base = (id: string) => `/api/v2/integrations/${encodeURIComponent(id)}`;
const read = (signal?: AbortSignal): RequestInit => (signal === undefined ? {} : { signal });

export class FetchIntegrationApiClient implements IntegrationApiClient {
    async listTypes(signal?: AbortSignal) {
        const value = await request(
            schemas.types,
            "/api/v2/integration-types?category=DATA_SOURCE",
            read(signal)
        );
        return value.items;
    }
    async listDataSources(signal?: AbortSignal) {
        const value = await request(schemas.integrations, "/api/v2/integrations", read(signal));
        return value.items.filter((item) => item.category === "DATA_SOURCE");
    }
    createIntegration(
        value: { integration_id: string; type_id: string; display_name: string },
        commandId: string
    ) {
        return request(schemas.command, "/api/v2/integrations", {
            method: "POST",
            headers: command(commandId),
            body: body(value)
        });
    }
    getIntegration(id: string, signal?: AbortSignal) {
        return request(schemas.integration, base(id), read(signal));
    }
    getDraft(id: string, signal?: AbortSignal) {
        return request(schemas.draft, `${base(id)}/draft`, read(signal));
    }
    updateDraft(
        id: string,
        value: {
            expected_draft_version: number;
            public_configuration: Record<string, unknown>;
            probe_configuration: Record<string, unknown> | null;
        },
        commandId: string
    ) {
        return request(schemas.command, `${base(id)}/draft`, {
            method: "PUT",
            headers: command(commandId),
            body: body(value)
        });
    }
    setSecret(
        id: string,
        fieldId: string,
        draftVersion: number,
        secret: string,
        commandId: string
    ) {
        return request(
            schemas.command,
            `${base(id)}/draft/secrets/${encodeURIComponent(fieldId)}`,
            {
                method: "PUT",
                headers: command(commandId),
                body: body({ expected_draft_version: draftVersion, secret })
            }
        );
    }
    clearSecret(id: string, fieldId: string, draftVersion: number, commandId: string) {
        return request(
            schemas.command,
            `${base(id)}/draft/secrets/${encodeURIComponent(fieldId)}?expected_draft_version=${String(draftVersion)}`,
            { method: "DELETE", headers: command(commandId) }
        );
    }
    resetDraftContract(id: string, draftVersion: number, commandId: string) {
        return request(schemas.command, `${base(id)}/draft/contract-reset`, {
            method: "POST",
            headers: command(commandId),
            body: body({ expected_draft_version: draftVersion })
        });
    }
    publish(id: string, draftVersion: number, commandId: string) {
        return request(schemas.command, `${base(id)}/revisions`, {
            method: "POST",
            headers: command(commandId),
            body: body({ expected_draft_version: draftVersion })
        });
    }
    setLifecycle(id: string, current: string, next: string, commandId: string) {
        return request(schemas.command, `${base(id)}/lifecycle`, {
            method: "PUT",
            headers: command(commandId),
            body: body({ expected_lifecycle_state: current, lifecycle_state: next })
        });
    }
    getOperationalStatus(id: string, signal?: AbortSignal) {
        return request(schemas.operational, `${base(id)}/operational-status`, read(signal));
    }
    probe(id: string, revision: string) {
        return request(schemas.attempt, `${base(id)}/probe`, {
            method: "POST",
            body: body({ expected_revision_fingerprint: revision })
        });
    }
    async listProbeAttempts(id: string, signal?: AbortSignal) {
        const value = await request(schemas.attempts, `${base(id)}/probe-attempts`, read(signal));
        return value.items;
    }
    async listRevisions(id: string, signal?: AbortSignal) {
        const value = await request(schemas.revisions, `${base(id)}/revisions`, read(signal));
        return value.items;
    }
}
