import { FetchIntegrationApiClient } from "./client";
import type { IntegrationWebError } from "./client";

const ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const summary = (category: "DATA_SOURCE" | "BROKER") => ({
    schema_version: 1,
    integration_id: ID,
    type_id: category === "DATA_SOURCE" ? "test.market_data" : "test.broker",
    display_name: category,
    lifecycle_state: "ACTIVE",
    current_revision_fingerprint: null,
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z",
    category,
    draft_version: 1,
    pinned_type_descriptor_fingerprint: "a".repeat(64)
});
const commandResponse = {
    schema_version: 1,
    command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    integration_id: ID,
    replayed: false,
    outcome_kind: "DRAFT",
    outcome_id: "1"
};

afterEach(() => vi.restoreAllMocks());

it("strictly admits and filters the configured Integration list to DATA_SOURCE", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(JSON.stringify({ items: [summary("DATA_SOURCE"), summary("BROKER")] }), {
            status: 200,
            headers: { "Content-Type": "application/json" }
        })
    );
    const items = await new FetchIntegrationApiClient().listDataSources();
    expect(items.map((item) => item.category)).toEqual(["DATA_SOURCE"]);
});

it("fails closed on a malformed success contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(JSON.stringify({ items: [{ category: "DATA_SOURCE" }] }), { status: 200 })
    );
    await expect(new FetchIntegrationApiClient().listDataSources()).rejects.toMatchObject({
        code: "CONTRACT_ERROR"
    } satisfies Partial<IntegrationWebError>);
});

it("submits a Secret only in the request body and never browser persistence", async () => {
    const browserFetch = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(new Response(JSON.stringify(commandResponse), { status: 200 }));
    const local = vi.spyOn(Storage.prototype, "setItem");
    await new FetchIntegrationApiClient().setSecret(
        ID,
        "api_key",
        4,
        "transient-secret",
        commandResponse.command_id
    );
    const init = browserFetch.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe(commandResponse.command_id);
    expect(init?.body).toContain("transient-secret");
    expect(local).not.toHaveBeenCalled();
});
