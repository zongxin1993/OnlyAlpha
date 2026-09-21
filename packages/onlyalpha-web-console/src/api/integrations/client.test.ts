import { FetchIntegrationApiClient } from "./client";
import type { IntegrationWebError } from "./client";

const ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const COMMAND_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const REVISION = "a".repeat(64);
const TYPE = {
    schema_version: 1,
    type_id: "test.market_data",
    category: "DATA_SOURCE",
    display_name: "Test source",
    description: "Fixture",
    provider_id: "test",
    implementation_id: "test",
    implementation_version: "1",
    public_api_version: "1.1",
    capabilities: ["HISTORICAL_BARS"],
    configuration_contract: {
        schema_version: 1,
        fingerprint: "b".repeat(64),
        fields: []
    },
    probe_contract: null,
    fingerprint: "c".repeat(64)
};
const INTEGRATION = {
    schema_version: 1,
    integration_id: ID,
    type_id: TYPE.type_id,
    display_name: "Test source",
    lifecycle_state: "ACTIVE",
    current_revision_fingerprint: REVISION,
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z"
};
const summary = (category: "DATA_SOURCE" | "BROKER") => ({
    ...INTEGRATION,
    type_id: category === "DATA_SOURCE" ? TYPE.type_id : "test.broker",
    display_name: category,
    category,
    draft_version: 4,
    pinned_type_descriptor_fingerprint: TYPE.fingerprint
});
const DRAFT = {
    schema_version: 1,
    integration_id: ID,
    base_revision_fingerprint: REVISION,
    pinned_type_descriptor_fingerprint: TYPE.fingerprint,
    type_descriptor: TYPE,
    public_configuration: {},
    probe_configuration: null,
    draft_version: 4,
    draft_fingerprint: "d".repeat(64),
    secret_statuses: [],
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z"
};
const COMMAND_RESPONSE = {
    schema_version: 1,
    command_id: COMMAND_ID,
    integration_id: ID,
    replayed: false,
    outcome_kind: "DRAFT",
    outcome_id: "4"
};
const OPERATIONAL = {
    schema_version: 1,
    integration_id: ID,
    revision_fingerprint: REVISION,
    status: "READY",
    probe_attempt_id: COMMAND_ID,
    checked_at: "2026-09-21T00:00:00Z",
    probe_supported: true
};
const ATTEMPT = {
    schema_version: 1,
    probe_attempt_id: COMMAND_ID,
    integration_id: ID,
    revision_fingerprint: REVISION,
    type_id: TYPE.type_id,
    type_descriptor_fingerprint: TYPE.fingerprint,
    probe_contract_fingerprint: "e".repeat(64),
    probe_configuration_fingerprint: null,
    runtime_configuration_fingerprint: "f".repeat(64),
    started_at: "2026-09-21T00:00:00Z",
    completed_at: "2026-09-21T00:00:01Z",
    overall_status: "READY",
    probe_instrument: "TEST",
    checks: []
};
const REVISION_SUMMARY = {
    revision_fingerprint: REVISION,
    revision_sequence: 1,
    type_id: TYPE.type_id,
    type_descriptor_fingerprint: TYPE.fingerprint,
    configuration_fingerprint: "1".repeat(64),
    runtime_configuration_fingerprint: "2".repeat(64),
    probe_configuration_fingerprint: null,
    secret_binding_fingerprint: "3".repeat(64),
    created_at: "2026-09-21T00:00:00Z"
};

const response = (value: unknown, status = 200) =>
    new Response(JSON.stringify(value), {
        status,
        headers: { "Content-Type": "application/json" }
    });
const parsedBody = (init: RequestInit | undefined): unknown =>
    typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;

type ClientCase = readonly [
    string,
    (client: FetchIntegrationApiClient) => Promise<unknown>,
    string,
    unknown,
    unknown
];

afterEach(() => vi.restoreAllMocks());

it.each<ClientCase>([
    [
        "listTypes",
        (client: FetchIntegrationApiClient) => client.listTypes(),
        "/api/v2/integration-types?category=DATA_SOURCE",
        { items: [TYPE] },
        [TYPE]
    ],
    [
        "getIntegration with an encoded identity",
        (client: FetchIntegrationApiClient) => client.getIntegration("source/id"),
        "/api/v2/integrations/source%2Fid",
        INTEGRATION,
        INTEGRATION
    ],
    [
        "getDraft",
        (client: FetchIntegrationApiClient) => client.getDraft(ID),
        `/api/v2/integrations/${ID}/draft`,
        DRAFT,
        DRAFT
    ],
    [
        "getOperationalStatus",
        (client: FetchIntegrationApiClient) => client.getOperationalStatus(ID),
        `/api/v2/integrations/${ID}/operational-status`,
        OPERATIONAL,
        OPERATIONAL
    ],
    [
        "listProbeAttempts",
        (client: FetchIntegrationApiClient) => client.listProbeAttempts(ID),
        `/api/v2/integrations/${ID}/probe-attempts`,
        { items: [ATTEMPT] },
        [ATTEMPT]
    ],
    [
        "getProbeAttempt with an encoded identity",
        (client: FetchIntegrationApiClient) => client.getProbeAttempt(ID, "attempt/id"),
        `/api/v2/integrations/${ID}/probe-attempts/attempt%2Fid`,
        ATTEMPT,
        ATTEMPT
    ],
    [
        "listRevisions",
        (client: FetchIntegrationApiClient) => client.listRevisions(ID),
        `/api/v2/integrations/${ID}/revisions`,
        { items: [REVISION_SUMMARY] },
        [REVISION_SUMMARY]
    ]
])("calls the %s read contract", async (_name, run, url, payload, expected) => {
    const browserFetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response(payload));
    await expect(run(new FetchIntegrationApiClient())).resolves.toEqual(expected);
    const [actualUrl, init] = browserFetch.mock.calls[0] ?? [];
    expect(actualUrl).toBe(url);
    expect(init?.headers).toBeInstanceOf(Headers);
});

it("strictly filters the configured Integration list to DATA_SOURCE", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
        response({ items: [summary("DATA_SOURCE"), summary("BROKER")] })
    );
    const items = await new FetchIntegrationApiClient().listDataSources();
    expect(items.map((item) => item.category)).toEqual(["DATA_SOURCE"]);
});

it.each([
    [
        "createIntegration",
        (client: FetchIntegrationApiClient) =>
            client.createIntegration(
                { integration_id: ID, type_id: TYPE.type_id, display_name: "Test source" },
                COMMAND_ID
            ),
        "POST",
        "/api/v2/integrations",
        {
            schema_version: 1,
            integration_id: ID,
            type_id: TYPE.type_id,
            display_name: "Test source"
        }
    ],
    [
        "updateDraft",
        (client: FetchIntegrationApiClient) =>
            client.updateDraft(
                ID,
                {
                    expected_draft_version: 4,
                    public_configuration: { timeout_seconds: 5 },
                    probe_configuration: null
                },
                COMMAND_ID
            ),
        "PUT",
        `/api/v2/integrations/${ID}/draft`,
        {
            schema_version: 1,
            expected_draft_version: 4,
            public_configuration: { timeout_seconds: 5 },
            probe_configuration: null
        }
    ],
    [
        "setSecret",
        (client: FetchIntegrationApiClient) =>
            client.setSecret(ID, "api/key", 4, "transient-secret", COMMAND_ID),
        "PUT",
        `/api/v2/integrations/${ID}/draft/secrets/api%2Fkey`,
        { schema_version: 1, expected_draft_version: 4, secret: "transient-secret" }
    ],
    [
        "clearSecret",
        (client: FetchIntegrationApiClient) => client.clearSecret(ID, "api/key", 4, COMMAND_ID),
        "DELETE",
        `/api/v2/integrations/${ID}/draft/secrets/api%2Fkey?expected_draft_version=4`,
        undefined
    ],
    [
        "resetDraftContract",
        (client: FetchIntegrationApiClient) => client.resetDraftContract(ID, 4, COMMAND_ID),
        "POST",
        `/api/v2/integrations/${ID}/draft/contract-reset`,
        { schema_version: 1, expected_draft_version: 4 }
    ],
    [
        "publish",
        (client: FetchIntegrationApiClient) => client.publish(ID, 4, COMMAND_ID),
        "POST",
        `/api/v2/integrations/${ID}/revisions`,
        { schema_version: 1, expected_draft_version: 4 }
    ],
    [
        "setLifecycle",
        (client: FetchIntegrationApiClient) =>
            client.setLifecycle(ID, "ACTIVE", "DISABLED", COMMAND_ID),
        "PUT",
        `/api/v2/integrations/${ID}/lifecycle`,
        { schema_version: 1, expected_lifecycle_state: "ACTIVE", lifecycle_state: "DISABLED" }
    ]
])("calls the %s Product Command contract", async (_name, run, method, url, expectedBody) => {
    const browserFetch = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(response(COMMAND_RESPONSE));
    await expect(run(new FetchIntegrationApiClient())).resolves.toEqual(COMMAND_RESPONSE);
    const [actualUrl, init] = browserFetch.mock.calls[0] ?? [];
    expect(actualUrl).toBe(url);
    expect(init?.method).toBe(method);
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe(COMMAND_ID);
    expect(parsedBody(init)).toEqual(expectedBody);
});

it("submits Probe without Product Command identity", async () => {
    const browserFetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response(ATTEMPT));
    await expect(new FetchIntegrationApiClient().probe(ID, REVISION)).resolves.toEqual(ATTEMPT);
    const [url, init] = browserFetch.mock.calls[0] ?? [];
    expect(url).toBe(`/api/v2/integrations/${ID}/probe`);
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).has("Idempotency-Key")).toBe(false);
    expect(parsedBody(init)).toEqual({
        schema_version: 1,
        expected_revision_fingerprint: REVISION
    });
});

it("classifies a fetch failure as TRANSPORT_ERROR", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network down"));
    await expect(new FetchIntegrationApiClient().listTypes()).rejects.toMatchObject({
        code: "TRANSPORT_ERROR"
    } satisfies Partial<IntegrationWebError>);
});

it.each([
    ["read", () => new FetchIntegrationApiClient().listTypes(), "CONTRACT_ERROR"],
    ["command", () => new FetchIntegrationApiClient().publish(ID, 4, COMMAND_ID), "UNKNOWN_OUTCOME"]
])("classifies invalid JSON on a %s request as %s", async (_name, run, code) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{", { status: 200 }));
    await expect(run()).rejects.toMatchObject({ code } satisfies Partial<IntegrationWebError>);
});

it.each([
    ["read", () => new FetchIntegrationApiClient().listTypes(), "CONTRACT_ERROR"],
    ["command", () => new FetchIntegrationApiClient().publish(ID, 4, COMMAND_ID), "UNKNOWN_OUTCOME"]
])("classifies a malformed %s error envelope as %s", async (_name, run, code) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ error: "bad" }, 503));
    await expect(run()).rejects.toMatchObject({
        code,
        status: 503
    } satisfies Partial<IntegrationWebError>);
});

it("preserves an admitted Product error code, detail and status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
        response(
            { schema_version: 1, error: { code: "INTEGRATION_NOT_FOUND", detail: "missing" } },
            404
        )
    );
    await expect(new FetchIntegrationApiClient().getIntegration(ID)).rejects.toMatchObject({
        code: "INTEGRATION_NOT_FOUND",
        message: "missing",
        status: 404
    } satisfies Partial<IntegrationWebError>);
});

it.each([
    ["read", () => new FetchIntegrationApiClient().listTypes(), "CONTRACT_ERROR"],
    ["command", () => new FetchIntegrationApiClient().publish(ID, 4, COMMAND_ID), "UNKNOWN_OUTCOME"]
])("classifies an invalid %s success schema as %s", async (_name, run, code) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({}));
    await expect(run()).rejects.toMatchObject({ code } satisfies Partial<IntegrationWebError>);
});

it.each([
    [
        "integration_id",
        { ...COMMAND_RESPONSE, integration_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd" }
    ],
    ["command_id", { ...COMMAND_RESPONSE, command_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" }]
])("classifies a mismatched command %s as UNKNOWN_OUTCOME", async (_field, payload) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response(payload));
    await expect(new FetchIntegrationApiClient().publish(ID, 4, COMMAND_ID)).rejects.toMatchObject({
        code: "UNKNOWN_OUTCOME"
    } satisfies Partial<IntegrationWebError>);
});

it("submits a Secret only in the request body and never browser persistence", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response(COMMAND_RESPONSE));
    const local = vi.spyOn(Storage.prototype, "setItem");
    await new FetchIntegrationApiClient().setSecret(
        ID,
        "api_key",
        4,
        "transient-secret",
        COMMAND_ID
    );
    expect(local).not.toHaveBeenCalled();
});
