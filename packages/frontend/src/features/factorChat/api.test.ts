import { describe, it, expect } from "vitest";
import { sessionSchema } from "./api";
describe("conversation admission", () => {
    it("rejects fabricated numeric reports, executable previews and invalid identities", () => {
        expect(
            sessionSchema.safeParse({ conversation_id: "latest", confirmed: true }).success
        ).toBe(false);
        expect(
            sessionSchema.safeParse({ schema_version: 1, research_result: { ic: 0.9 } }).success
        ).toBe(false);
    });
});

import { afterEach, vi } from "vitest";
import { z } from "zod";
import { request } from "./api";
afterEach(() => {
    vi.unstubAllGlobals();
});
it("uses separate Agent bearer with no cookies and backend Human cookies with no bearer", async () => {
    const fetch = vi
        .fn<typeof globalThis.fetch>()
        .mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetch);
    const access = {
        schema_version: 1 as const,
        token: "agent-only",
        expires_at: 1,
        subject: "owner",
        agent_url: "https://agent.example/",
        binding: "a".repeat(64)
    };
    await request(
        "/api/v1/agent/models",
        z.object({ ok: z.boolean() }),
        undefined,
        undefined,
        access
    );
    const first = fetch.mock.calls[0];
    expect(first?.[0]).toBe("https://agent.example/api/v1/agent/models");
    expect(first?.[1]?.credentials).toBe("omit");
    expect(first?.[1]?.headers).toEqual({
        "Content-Type": "application/json",
        Authorization: "Bearer agent-only"
    });
    fetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    await request("/api/v2/agent-connection", z.object({ ok: z.boolean() }));
    const args = fetch.mock.calls.at(-1);
    if (args === undefined) throw new Error("fetch required");
    expect(args[1]?.credentials).toBe("same-origin");
    expect(args[1]?.headers).not.toHaveProperty("Authorization");
});
