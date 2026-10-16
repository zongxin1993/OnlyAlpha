import { act, renderHook, waitFor } from "@testing-library/react";
import { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import { useWatchlists } from "./useWatchlists";
import { FIXTURE_REFERENCE } from "../../test/marketDataClient";

afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
});
const member = {
    source: { ...FIXTURE_REFERENCE, expected_type_id: "test.market_data" },
    instrument_id: "BTCUSDT.TEST"
};

it("creates the default list on the first star and toggles exact source membership", async () => {
    let book = { schema_version: 2, version: 0, lists: [] as unknown[] };
    const writes: unknown[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn(async (_url: string, init?: RequestInit) => {
            await Promise.resolve();
            if (init?.method === "PUT") {
                const body = JSON.parse(typeof init.body === "string" ? init.body : "") as {
                    lists: unknown[];
                };
                writes.push(body);
                book = { ...book, version: book.version + 1, lists: body.lists };
            }
            return new Response(JSON.stringify(book));
        })
    );
    const credentials = new LocalReadCredentials(true);
    const { result } = renderHook(() => useWatchlists(credentials));
    await waitFor(() => {
        expect(result.current.book).not.toBeNull();
    });
    await act(() => result.current.toggle(member));
    expect(result.current.active?.name).toBe("自选");
    expect(result.current.active?.members).toEqual([member]);
    const second = {
        ...member,
        source: { ...member.source, integration_revision_fingerprint: "b".repeat(64) }
    };
    await act(() => result.current.toggle(second));
    expect(result.current.active?.members).toEqual([member, second]);
    await act(() => result.current.toggle(member));
    expect(result.current.active?.members).toEqual([second]);
    expect(writes).toHaveLength(3);
});

it("retains UNKNOWN across remount, blocks another star and resolves the original command", async () => {
    let book = { schema_version: 2, version: 0, lists: [] as unknown[] };
    let submits = 0;
    const requests: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string, init?: RequestInit) => {
            await Promise.resolve();
            requests.push(url);
            if (init?.method === "PUT") {
                submits++;
                const body = JSON.parse(typeof init.body === "string" ? init.body : "") as {
                    lists: unknown[];
                };
                book = { ...book, version: 1, lists: body.lists };
                throw new TypeError("response lost after commit");
            }
            return new Response(JSON.stringify(book));
        })
    );
    const credentials = new LocalReadCredentials(true);
    const first = renderHook(() => useWatchlists(credentials));
    await waitFor(() => {
        expect(first.result.current.book).not.toBeNull();
    });
    await act(() => first.result.current.toggle(member));
    const command = first.result.current.pending;
    expect(command).not.toBeNull();
    first.unmount();
    const second = renderHook(() => useWatchlists(credentials));
    await waitFor(() => {
        expect(second.result.current.book).not.toBeNull();
    });
    await act(() => second.result.current.toggle(member));
    expect(submits).toBe(1);
    await act(() => second.result.current.resolvePending());
    expect(requests).toContain(`/api/v2/watchlists/commands/${command ?? ""}`);
    expect(second.result.current.pending).toBeNull();
    expect(second.result.current.active?.members).toEqual([member]);
});
