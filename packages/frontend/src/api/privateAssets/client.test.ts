import { FetchPrivateAssetsApiClient } from "./client";
import { LocalReadCredentials } from "../marketData/localReadCredentials";

const selected = {
    private_asset_kind: "FACTOR" as const,
    private_asset_id: "private.factor.momentum",
    revision_fingerprint: "a".repeat(64),
    content_fingerprint: "b".repeat(64)
};
const revision = {
    schema_version: 1,
    factor_id: selected.private_asset_id,
    semantic_version: "1",
    revision_fingerprint: selected.revision_fingerprint,
    parent_revision_fingerprint: null,
    source_text: "def calculate(api, inputs, parameters):\n    return inputs\n",
    source_sha256: selected.content_fingerprint,
    factor_api_version: 1,
    factor_api_contract_fingerprint: "c".repeat(64),
    input_contract: {},
    parameter_contract: {},
    output_contract: {},
    description: "观察价格动量",
    economic_rationale: "检验持续性假设",
    category: "momentum",
    tags: ["daily"]
};
const empty = {
    schema_version: 1,
    registry_fingerprint: "d".repeat(64),
    entries: [],
    factor_presentations: []
};
function reply(body: unknown, status = 200) {
    return Response.json(body, { status, headers: { "cache-control": "no-store" } });
}
afterEach(() => vi.unstubAllGlobals());

it("refuses unauthenticated reads and unsupported asset kinds before transport", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const api = new FetchPrivateAssetsApiClient(new LocalReadCredentials());
    await expect(api.current()).rejects.toMatchObject({
        code: "UNAUTHORIZED",
        status: 401,
        phase: "QUERY"
    });
    await expect(api.factor({ ...selected, private_asset_kind: "STRATEGY" })).rejects.toThrow(
        "PRIVATE_ASSET_KIND_UNSUPPORTED"
    );
    expect(fetch).not.toHaveBeenCalled();
});

it("uses an explicit read bearer and cancellation signal for one exact immutable revision request", async () => {
    const credentials = new LocalReadCredentials();
    credentials.replace("e".repeat(64));
    const controller = new AbortController();
    const fetch = vi.fn().mockResolvedValue(reply(revision));
    vi.stubGlobal("fetch", fetch);
    await expect(
        new FetchPrivateAssetsApiClient(credentials).factor(selected, controller.signal)
    ).resolves.toEqual(revision);
    expect(fetch).toHaveBeenCalledExactlyOnceWith(
        `/api/v2/private-assets/factors/${selected.private_asset_id}/revisions/${selected.revision_fingerprint}?content_fingerprint=${selected.content_fingerprint}`,
        {
            cache: "no-store",
            credentials: "omit",
            headers: { Accept: "application/json", Authorization: `Bearer ${"e".repeat(64)}` },
            signal: controller.signal
        }
    );
});

it.each([
    "session-before-json",
    "session-during-json",
    "abort-before-json",
    "abort-during-json"
] as const)("discards stale private metadata at %s", async (boundary) => {
    const credentials = new LocalReadCredentials(true);
    const controller = new AbortController();
    const response = reply(empty);
    const invalidate = () => {
        if (boundary.startsWith("session")) credentials.replace(null);
        else controller.abort();
    };
    const json = vi.spyOn(response, "json");
    if (boundary.endsWith("during-json"))
        json.mockImplementationOnce(() => {
            invalidate();
            return Promise.resolve(empty);
        });
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementationOnce(() => {
        if (boundary.endsWith("before-json")) invalidate();
        return Promise.resolve(response);
    });
    vi.stubGlobal("fetch", fetch);
    await expect(
        new FetchPrivateAssetsApiClient(credentials).current(controller.signal)
    ).rejects.toMatchObject({ code: "STALE", status: 409, phase: "QUERY" });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(json).toHaveBeenCalledTimes(boundary.endsWith("before-json") ? 0 : 1);
});

it.each([
    {
        name: "native refusal",
        response: () =>
            reply(
                {
                    schema_version: 1,
                    error: {
                        code: "PRIVATE_ASSET_UNAVAILABLE",
                        detail: "Owning fact is unreadable",
                        phase: "QUERY"
                    }
                },
                503
            ),
        code: "PRIVATE_ASSET_UNAVAILABLE",
        message: "Owning fact is unreadable",
        status: 503
    },
    {
        name: "malformed refusal",
        response: () => reply({ error: "proxy failure" }, 502),
        code: "CONTRACT_ERROR",
        message: "Metadata is unavailable.",
        status: 502
    },
    {
        name: "cacheable reply",
        response: () => Response.json(empty),
        code: "CONTRACT_ERROR",
        message: "Metadata response is not admissible.",
        status: 200
    },
    {
        name: "invalid registry",
        response: () => reply({ ...empty, schema_version: 99 }),
        code: "CONTRACT_ERROR",
        message: "Metadata response is invalid.",
        status: 200
    }
])("does not admit $name as private metadata", async ({ response, code, message, status }) => {
    const fetch = vi.fn().mockResolvedValue(response());
    vi.stubGlobal("fetch", fetch);
    await expect(
        new FetchPrivateAssetsApiClient(new LocalReadCredentials(true)).current()
    ).rejects.toMatchObject({ code, message, status, phase: "QUERY" });
    expect(fetch).toHaveBeenCalledTimes(1);
});

it.each([
    { name: "different Factor", body: { ...revision, factor_id: "another.factor" } },
    { name: "different revision", body: { ...revision, revision_fingerprint: "e".repeat(64) } },
    { name: "different content", body: { ...revision, source_sha256: "f".repeat(64) } }
])("rejects a schema-valid $name without substituting a current revision", async ({ body }) => {
    const fetch = vi.fn().mockResolvedValue(reply(body));
    vi.stubGlobal("fetch", fetch);
    await expect(
        new FetchPrivateAssetsApiClient(new LocalReadCredentials(true)).factor(selected)
    ).rejects.toMatchObject({
        code: "PRIVATE_ASSET_EXACT_READ_MISMATCH",
        status: 409,
        phase: "QUERY"
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]?.[0]).toBe(
        `/api/v2/private-assets/factors/${selected.private_asset_id}/revisions/${selected.revision_fingerprint}?content_fingerprint=${selected.content_fingerprint}`
    );
});
