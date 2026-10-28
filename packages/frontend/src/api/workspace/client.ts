import { z } from "zod";
import type { LocalReadCredentials } from "../marketData/localReadCredentials";
import { workspaceBookSchema, type WorkspaceBook } from "./http.generated";
export type { WorkspaceBook, WorkspaceConfiguration, WorkspaceStudy } from "./http.generated";
export interface WorkspaceSave {
    readonly schema_version: 3;
    readonly command_id: string;
    readonly expected_version: number;
    readonly active_workspace_id: string | null;
    readonly workspaces: WorkspaceBook["workspaces"];
}
export class WorkspaceWebError extends Error {
    constructor(
        readonly code: string,
        readonly definitive: boolean
    ) {
        super(code);
    }
}
export class FetchWorkspaceApiClient {
    constructor(private readonly credentials: LocalReadCredentials) {}
    async read(signal?: AbortSignal): Promise<WorkspaceBook> {
        return workspaceBookSchema.parse(
            await this.request("/api/v2/workspace", signal === undefined ? {} : { signal })
        );
    }
    async save(intent: WorkspaceSave): Promise<WorkspaceBook> {
        return workspaceBookSchema.parse(
            await this.request("/api/v2/workspace", {
                method: "PUT",
                body: JSON.stringify(intent)
            })
        );
    }
    async command(commandId: string): Promise<WorkspaceBook> {
        return workspaceBookSchema.parse(
            await this.request(`/api/v2/workspace/commands/${commandId}`)
        );
    }
    private async request(url: string, init: RequestInit = {}): Promise<unknown> {
        const captured = this.credentials.capture();
        // The bearer is strictly read-only. It is never forwarded as Owner authorization.
        if (!this.credentials.localSession || captured.bearer !== null)
            throw new WorkspaceWebError("WORKSPACE_OWNER_REQUIRED", true);
        let response: Response;
        try {
            response = await fetch(url, {
                ...init,
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    ...(init.body === undefined ? {} : { "Content-Type": "application/json" })
                }
            });
        } catch {
            throw new WorkspaceWebError("WORKSPACE_COMMAND_UNKNOWN", false);
        }
        let body: unknown;
        try {
            body = await response.json();
        } catch {
            throw new WorkspaceWebError("WORKSPACE_REPLY_INVALID", false);
        }
        if (!this.credentials.isCurrent(captured.generation))
            throw new WorkspaceWebError("WORKSPACE_SESSION_CHANGED", false);
        if (!response.ok) {
            const error = z.object({ error: z.object({ code: z.string() }) }).safeParse(body);
            throw new WorkspaceWebError(
                error.success ? error.data.error.code : "WORKSPACE_UNAVAILABLE",
                response.status >= 400 && response.status < 500
            );
        }
        return body;
    }
}
