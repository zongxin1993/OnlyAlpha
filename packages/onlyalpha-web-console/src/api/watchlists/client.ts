import { z } from "zod";
import type { components } from "../research/generated";
import type { LocalReadCredentials } from "../marketData/localReadCredentials";

export const watchlistMemberSchema = z.strictObject({
    source: z.strictObject({
        integration_id: z.string().min(1),
        integration_revision_fingerprint: z.string().regex(/^[0-9a-f]{64}$/),
        expected_type_id: z.string().min(1)
    }),
    instrument_id: z.string().min(1)
});
export const watchlistSchema = z.strictObject({
    list_id: z
        .string()
        .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/),
    name: z
        .string()
        .min(1)
        .max(64)
        .refine((value) => value === value.trim()),
    members: z.array(watchlistMemberSchema).max(100)
});
const memberIdentity = (member: z.infer<typeof watchlistMemberSchema>): string =>
    JSON.stringify([
        member.source.integration_id,
        member.source.integration_revision_fingerprint,
        member.source.expected_type_id,
        member.instrument_id
    ]);
export const watchlistBookSchema = z
    .strictObject({
        schema_version: z.literal(2),
        version: z.number().int().nonnegative(),
        lists: z.array(watchlistSchema).max(20)
    })
    .refine(
        (book) =>
            (book.version !== 0 || book.lists.length === 0) &&
            new Set(book.lists.map((item) => item.list_id)).size === book.lists.length &&
            new Set(book.lists.map((item) => item.name)).size === book.lists.length &&
            book.lists.every(
                (item) => new Set(item.members.map(memberIdentity)).size === item.members.length
            ) &&
            book.lists.reduce((count, item) => count + item.members.length, 0) <= 200
    );

export type WatchlistMember = components["schemas"]["WatchlistMemberDto"];
export type Watchlist = components["schemas"]["WatchlistDto"];
export type WatchlistBook = components["schemas"]["WatchlistBookDto"];
export interface WatchlistSave {
    readonly schema_version: 2;
    readonly command_id: string;
    readonly expected_version: number;
    readonly lists: readonly Watchlist[];
}
export class WatchlistWebError extends Error {
    constructor(
        readonly code: string,
        readonly definitive: boolean
    ) {
        super(code);
    }
}
export class FetchWatchlistApiClient {
    constructor(private readonly credentials: LocalReadCredentials) {}
    async read(signal?: AbortSignal): Promise<WatchlistBook> {
        return watchlistBookSchema.parse(
            await this.request("/api/v2/watchlists", signal === undefined ? {} : { signal })
        );
    }
    async save(intent: WatchlistSave): Promise<WatchlistBook> {
        return watchlistBookSchema.parse(
            await this.request("/api/v2/watchlists", {
                method: "PUT",
                body: JSON.stringify(intent)
            })
        );
    }
    async command(commandId: string): Promise<WatchlistBook | null> {
        return watchlistBookSchema
            .nullable()
            .parse(await this.request(`/api/v2/watchlists/commands/${commandId}`));
    }
    private async request(url: string, init: RequestInit = {}): Promise<unknown> {
        const captured = this.credentials.capture();
        // The bearer is strictly read-only. It is never forwarded as Owner authorization.
        if (!this.credentials.localSession || captured.bearer !== null)
            throw new WatchlistWebError("WATCHLIST_OWNER_REQUIRED", true);
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
            throw new WatchlistWebError("WATCHLIST_COMMAND_UNKNOWN", false);
        }
        let body: unknown;
        try {
            body = await response.json();
        } catch {
            throw new WatchlistWebError("WATCHLIST_REPLY_INVALID", false);
        }
        if (!this.credentials.isCurrent(captured.generation))
            throw new WatchlistWebError("WATCHLIST_SESSION_CHANGED", false);
        if (!response.ok) {
            const error = z.object({ error: z.object({ code: z.string() }) }).safeParse(body);
            throw new WatchlistWebError(
                error.success ? error.data.error.code : "WATCHLIST_UNAVAILABLE",
                response.status >= 400 && response.status < 500
            );
        }
        return body;
    }
}
