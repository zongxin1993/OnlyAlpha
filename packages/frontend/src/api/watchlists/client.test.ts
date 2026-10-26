import { LocalReadCredentials } from "../marketData/localReadCredentials";
import { FetchWatchlistApiClient, WatchlistWebError, watchlistBookSchema } from "./client";

const empty = { schema_version: 2, version: 0, lists: [] };
const member = {
    source: {
        integration_id: "source",
        integration_revision_fingerprint: "a".repeat(64),
        expected_type_id: "test.market_data"
    },
    instrument_id: "BTCUSDT.TEST"
};
const list = {
    list_id: "0926c6a2-0cb8-47a5-8d94-cdb89b336182",
    name: "日常",
    members: [member]
};
const intent = {
    schema_version: 2 as const,
    command_id: "d21599a3-abcd-41bf-989b-ce44a1b4dc44",
    expected_version: 0,
    lists: [list]
};
afterEach(() => vi.unstubAllGlobals());

it("requires an explicitly configured Owner session and never promotes a read bearer", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
        new FetchWatchlistApiClient(new LocalReadCredentials()).read()
    ).rejects.toMatchObject({ code: "WATCHLIST_OWNER_REQUIRED", definitive: true });
    const credentials = new LocalReadCredentials(true);
    credentials.replace("a".repeat(64));
    await expect(new FetchWatchlistApiClient(credentials).save(intent)).rejects.toMatchObject({
        code: "WATCHLIST_OWNER_REQUIRED",
        definitive: true
    });
    expect(fetch).not.toHaveBeenCalled();
});

it("uses the formal exact save and command-result query without retries", async () => {
    const fetch = vi
        .fn()
        .mockResolvedValueOnce(new Response(JSON.stringify(empty)))
        .mockResolvedValueOnce(
            new Response(JSON.stringify({ ...empty, version: 1, lists: [list] }))
        )
        .mockResolvedValueOnce(new Response("null"));
    vi.stubGlobal("fetch", fetch);
    const api = new FetchWatchlistApiClient(new LocalReadCredentials(true));
    expect(await api.read()).toEqual(empty);
    expect((await api.save(intent)).lists).toEqual([list]);
    expect(await api.command(intent.command_id)).toBeNull();
    expect(fetch.mock.calls[1]).toEqual([
        "/api/v2/watchlists",
        {
            method: "PUT",
            body: JSON.stringify(intent),
            credentials: "same-origin",
            headers: { Accept: "application/json", "Content-Type": "application/json" }
        }
    ]);
    expect(fetch.mock.calls[2]?.[0]).toBe(`/api/v2/watchlists/commands/${intent.command_id}`);
});

it.each([
    [409, true],
    [403, true],
    [503, false]
] as const)(
    "preserves definitive versus uncertain HTTP outcomes: %i",
    async (status, definitive) => {
        const fetch = vi
            .fn()
            .mockResolvedValue(
                new Response(JSON.stringify({ error: { code: "CONTROLLED_FAILURE" } }), { status })
            );
        vi.stubGlobal("fetch", fetch);
        const api = new FetchWatchlistApiClient(new LocalReadCredentials(true));
        await expect(api.save(intent)).rejects.toMatchObject({
            code: "CONTROLLED_FAILURE",
            definitive
        });
        expect(fetch).toHaveBeenCalledTimes(1);
    }
);

it("keeps a transport failure UNKNOWN and never resubmits", async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError("offline"));
    vi.stubGlobal("fetch", fetch);
    await expect(
        new FetchWatchlistApiClient(new LocalReadCredentials(true)).save(intent)
    ).rejects.toMatchObject({ code: "WATCHLIST_COMMAND_UNKNOWN", definitive: false });
    expect(fetch).toHaveBeenCalledTimes(1);
});

it("rejects malformed JSON and a withdrawn authentication generation", async () => {
    const credentials = new LocalReadCredentials(true);
    const api = new FetchWatchlistApiClient(credentials);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("invalid")));
    await expect(api.save(intent)).rejects.toBeInstanceOf(WatchlistWebError);
    vi.stubGlobal(
        "fetch",
        vi.fn(() => {
            credentials.replace(null);
            return Promise.resolve(new Response(JSON.stringify(empty)));
        })
    );
    await expect(api.read()).rejects.toMatchObject({
        code: "WATCHLIST_SESSION_CHANGED",
        definitive: false
    });
});

it.each([
    { version: 0, lists: [list] },
    { version: 1, lists: [list, list] },
    { version: 1, lists: [{ ...list, members: [member, member] }] },
    { version: 1, lists: [{ ...list, name: " 日常 " }] },
    {
        version: 1,
        lists: [
            {
                ...list,
                members: [
                    {
                        ...member,
                        source: {
                            ...member.source,
                            integration_revision_fingerprint: "invalid"
                        }
                    }
                ]
            }
        ]
    }
])("refuses malformed or competing response identities: %j", (body) => {
    expect(watchlistBookSchema.safeParse({ schema_version: 2, ...body }).success).toBe(false);
});

it("allows the same canonical instrument from different exact Sources", () => {
    const other = {
        ...member,
        source: { ...member.source, integration_revision_fingerprint: "b".repeat(64) }
    };
    expect(
        watchlistBookSchema.parse({
            schema_version: 2,
            version: 1,
            lists: [{ ...list, members: [member, other] }]
        }).lists[0]?.members
    ).toHaveLength(2);
    expect(
        watchlistBookSchema.safeParse({ schema_version: 1, version: 0, lists: [] }).success
    ).toBe(false);
});
