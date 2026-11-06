import { FactorAuthoringClient } from "./authoring";
import { LocalReadCredentials } from "../marketData/localReadCredentials";

const factor = "private.factor.momentum";
const command = "d21599a3-abcd-41bf-989b-ce44a1b4dc44";
const fingerprint = "a".repeat(64);
const draft = {
    schema_version: 1,
    factor_id: factor,
    semantic_version: "1",
    base_revision_fingerprint: null,
    source_text: "def calculate(api, inputs, parameters):\n    return inputs\n",
    factor_api_version: 1,
    factor_api_contract_fingerprint: "b".repeat(64),
    input_contract: {},
    parameter_contract: {},
    output_contract: {},
    description: "观察价格动量",
    economic_rationale: "检验持续性假设",
    category: "momentum",
    tags: ["daily"]
};
const display = {
    schema_version: 1,
    factor_id: factor,
    display_name: "价格动量",
    usage_summary: "观察价格变化",
    edit_number: 1
};
const { base_revision_fingerprint: parentRevision, ...revisionFields } = draft;
const publishedRevision = {
    ...revisionFields,
    revision_fingerprint: "c".repeat(64),
    parent_revision_fingerprint: parentRevision,
    source_sha256: "d".repeat(64)
};
function saved() {
    return {
        schema_version: 1,
        command_id: command,
        factor_id: factor,
        result: {
            draft,
            draft_fingerprint: fingerprint,
            revision: null,
            display,
            display_fingerprint: "e".repeat(64),
            display_version: null
        }
    };
}
function published() {
    return {
        ...saved(),
        result: { ...saved().result, revision: publishedRevision, display_version: 1 }
    };
}
function reply(body: unknown, status = 200) {
    return Response.json(body, { status, headers: { "cache-control": "no-store" } });
}
afterEach(() => vi.unstubAllGlobals());

it("requires the Owner session before sending a write, including when a read bearer exists", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>();
    vi.stubGlobal("fetch", fetch);
    for (const credentials of [new LocalReadCredentials(), new LocalReadCredentials(true)]) {
        if (credentials.localSession) credentials.replace("f".repeat(64));
        await expect(
            new FactorAuthoringClient(credentials).save(
                factor,
                command,
                null,
                JSON.stringify(draft),
                null
            )
        ).rejects.toMatchObject({ code: "PRIVATE_FACTOR_OWNER_REQUIRED", definitive: true });
    }
    expect(fetch).not.toHaveBeenCalled();
});

it.each([
    {
        status: 409,
        body: { error: { code: "PRIVATE_FACTOR_DRAFT_STALE" } },
        code: "PRIVATE_FACTOR_DRAFT_STALE",
        definitive: true
    },
    {
        status: 503,
        body: { error: { code: "PRIVATE_FACTOR_STORE_UNAVAILABLE" } },
        code: "PRIVATE_FACTOR_STORE_UNAVAILABLE",
        definitive: false
    },
    {
        status: 502,
        body: { unexpected: "proxy response" },
        code: "PRIVATE_FACTOR_UNAVAILABLE",
        definitive: false
    },
    {
        status: 403,
        body: { error: { code: "PRIVATE_FACTOR_DISPLAY_UNAVAILABLE" } },
        code: "PRIVATE_FACTOR_DISPLAY_UNAVAILABLE",
        definitive: true
    }
])(
    "preserves the command outcome classification for HTTP $status / $code",
    async ({ status, body, code, definitive }) => {
        const fetch = vi.fn().mockResolvedValue(reply(body, status));
        vi.stubGlobal("fetch", fetch);
        await expect(
            new FactorAuthoringClient(new LocalReadCredentials(true)).save(
                factor,
                command,
                null,
                JSON.stringify(draft),
                null
            )
        ).rejects.toMatchObject({
            code,
            definitive,
            ...(code === "PRIVATE_FACTOR_DISPLAY_UNAVAILABLE"
                ? { message: "因子名称和用途信息不可用，暂不能编辑。" }
                : {})
        });
        expect(fetch).toHaveBeenCalledTimes(1);
    }
);

it.each(["transport", "malformed-json", "session-changed"] as const)(
    "keeps %s writes uncertain and recovers only through the original Command",
    async (failure) => {
        const credentials = new LocalReadCredentials(true);
        const api = new FactorAuthoringClient(credentials);
        const fetch = vi.fn<typeof globalThis.fetch>();
        if (failure === "transport") fetch.mockRejectedValueOnce(new TypeError("connection lost"));
        else if (failure === "malformed-json") fetch.mockResolvedValueOnce(new Response("{"));
        else
            fetch.mockImplementationOnce(() => {
                credentials.replace(null);
                return Promise.resolve(reply(saved()));
            });
        fetch.mockResolvedValueOnce(reply(null));
        vi.stubGlobal("fetch", fetch);
        await expect(
            api.save(factor, command, null, JSON.stringify(draft), null)
        ).rejects.toMatchObject({
            code:
                failure === "session-changed"
                    ? "PRIVATE_FACTOR_SESSION_CHANGED"
                    : "PRIVATE_FACTOR_COMMAND_UNKNOWN",
            definitive: false
        });
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(await api.command(factor, command, "SAVE")).toBeNull();
        expect(fetch).toHaveBeenCalledTimes(2);
        expect(fetch.mock.calls[0]?.[0]).toBe(`/api/v2/private-assets/factors/${factor}/draft`);
        expect(fetch.mock.calls[0]?.[1]?.method).toBe("PUT");
        expect(new Headers(fetch.mock.calls[0]?.[1]?.headers).get("Idempotency-Key")).toBe(command);
        expect(fetch.mock.calls[1]?.[0]).toBe(
            `/api/v2/private-assets/factors/${factor}/commands/${command}`
        );
        expect(fetch.mock.calls[1]?.[1]?.method).toBeUndefined();
    }
);

it.each(["cacheable", "wrong-factor"] as const)(
    "rejects %s authoring state without accepting it as this Factor",
    async (failure) => {
        const state = {
            schema_version: 1,
            factor_id: failure === "wrong-factor" ? "another.factor" : factor,
            current_revision_fingerprint: null,
            draft: null,
            draft_fingerprint: null,
            revisions: [],
            display,
            display_fingerprint: "e".repeat(64)
        };
        const fetch = vi
            .fn()
            .mockResolvedValue(failure === "cacheable" ? Response.json(state) : reply(state));
        vi.stubGlobal("fetch", fetch);
        await expect(
            new FactorAuthoringClient(new LocalReadCredentials(true)).read(factor)
        ).rejects.toMatchObject({ code: "PRIVATE_FACTOR_REPLY_INVALID", definitive: false });
        expect(fetch).toHaveBeenCalledTimes(1);
    }
);

it.each([
    { name: "malformed receipt", body: () => ({ schema_version: 1 }) },
    { name: "wrong Factor", body: () => ({ ...published(), factor_id: "another.factor" }) },
    {
        name: "wrong Command",
        body: () => ({ ...published(), command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" })
    },
    {
        name: "wrong display owner",
        body: () => ({
            ...published(),
            result: { ...published().result, display: { ...display, factor_id: "another.factor" } }
        })
    },
    {
        name: "wrong draft owner",
        body: () => ({
            ...published(),
            result: { ...published().result, draft: { ...draft, factor_id: "another.factor" } }
        })
    },
    {
        name: "wrong revision owner",
        body: () => ({
            ...published(),
            result: {
                ...published().result,
                revision: { ...publishedRevision, factor_id: "another.factor" }
            }
        })
    },
    {
        name: "missing published revision",
        body: () => ({ ...published(), result: { ...published().result, revision: null } })
    },
    {
        name: "missing published display version",
        body: () => ({ ...published(), result: { ...published().result, display_version: null } })
    },
    {
        name: "wrong draft pin",
        body: () => ({
            ...published(),
            result: { ...published().result, draft_fingerprint: "f".repeat(64) }
        })
    },
    { name: "matching published receipt", body: published }
])("binds publish acceptance to the exact original request: $name", async ({ name, body }) => {
    const fetch = vi.fn().mockResolvedValue(reply(body()));
    vi.stubGlobal("fetch", fetch);
    const result = new FactorAuthoringClient(new LocalReadCredentials(true)).publish(
        factor,
        command,
        fingerprint
    );
    if (name === "matching published receipt") await expect(result).resolves.toEqual(published());
    else
        await expect(result).rejects.toMatchObject({
            code: "PRIVATE_FACTOR_REPLY_INVALID",
            definitive: false
        });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]?.[0]).toBe(`/api/v2/private-assets/factors/${factor}/revisions`);
    const request = fetch.mock.calls[0]?.[1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(request.credentials).toBe("same-origin");
    expect(request.cache).toBe("no-store");
    expect(new Headers(request.headers).get("Idempotency-Key")).toBe(command);
    expect(JSON.parse(request.body as string)).toEqual({ expected_draft_fingerprint: fingerprint });
});
