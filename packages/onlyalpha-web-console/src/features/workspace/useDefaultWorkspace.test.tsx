import { act, renderHook, waitFor } from "@testing-library/react";
import { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import { marketDataBarSemantic } from "../../api/marketData/model";
import { useDefaultWorkspace } from "./useDefaultWorkspace";
const configuration = {
    source: {
        integration_id: "source",
        integration_revision_fingerprint: "a".repeat(64),
        expected_type_id: "test.source"
    },
    instrument_id: "BTCUSDT.BINANCE",
    bar_semantic: marketDataBarSemantic(7),
    studies: []
};
afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
});
it("explicitly saves configuration with CAS and never restores the active chart from its save response", async () => {
    let book = { schema_version: 2, version: 0, configuration: null as unknown };
    const writes: unknown[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((_url: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (init?.method === "PUT") {
                    if (typeof init.body !== "string") throw new Error("Expected JSON save intent");
                    const body = JSON.parse(init.body) as { configuration: unknown };
                    writes.push(body);
                    book = { ...book, version: 1, configuration: body.configuration };
                }
                return new Response(JSON.stringify(book));
            })
        )
    );
    const credentials = new LocalReadCredentials(true);
    const { result } = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(result.current.book?.version).toBe(0);
    });
    const restore = result.current.restoration;
    await act(() => result.current.save(configuration));
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({ expected_version: 0, configuration });
    expect(result.current.book?.version).toBe(1);
    expect(result.current.restoration).toBe(restore);
});
it("retains UNKNOWN across remount and resolves the original command without another save", async () => {
    let book = { schema_version: 2, version: 0, configuration: null as unknown };
    let writes = 0;
    const urls: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                urls.push(url);
                if (init?.method === "PUT") {
                    writes++;
                    book = { ...book, version: 1, configuration };
                    throw new TypeError("lost commit response");
                }
                return new Response(JSON.stringify(book));
            })
        )
    );
    const credentials = new LocalReadCredentials(true);
    const first = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(first.result.current.book).not.toBeNull();
    });
    await act(() => first.result.current.save(configuration));
    const id = first.result.current.pending;
    expect(id).not.toBeNull();
    first.unmount();
    const next = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(next.result.current.book).not.toBeNull();
    });
    await act(() => next.result.current.save(configuration));
    expect(writes).toBe(1);
    await act(() => next.result.current.resolvePending());
    expect(urls).toContain(`/api/v2/workspace/commands/${id ?? ""}`);
    expect(next.result.current.pending).toBeNull();
    expect(writes).toBe(1);
});
it("keeps the draft after a version conflict until an explicit reload", async () => {
    let book = { schema_version: 2, version: 1, configuration };
    vi.stubGlobal(
        "fetch",
        vi.fn((_url: string, init?: RequestInit) =>
            Promise.resolve(
                init?.method === "PUT"
                    ? new Response(
                          JSON.stringify({ error: { code: "WORKSPACE_VERSION_CONFLICT" } }),
                          {
                              status: 409
                          }
                      )
                    : new Response(JSON.stringify(book))
            )
        )
    );
    const credentials = new LocalReadCredentials(true);
    const { result } = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(result.current.book?.version).toBe(1);
    });
    const restore = result.current.restoration;
    await act(() => result.current.save(configuration));
    expect(result.current.pending).toBeNull();
    expect(result.current.restoration).toBe(restore);
    expect(result.current.message).toContain("其他窗口");
    book = { ...book, version: 2 };
    await act(() => result.current.reload());
    expect(result.current.book?.version).toBe(2);
    expect(result.current.restoration).not.toBe(restore);
});
it("does not treat unavailable or invalid saved configuration as an empty workspace", async () => {
    vi.stubGlobal(
        "fetch",
        vi.fn(() =>
            Promise.resolve(
                new Response(
                    JSON.stringify({
                        schema_version: 2,
                        version: 1,
                        configuration: { ...configuration, bars: [] }
                    })
                )
            )
        )
    );
    const credentials = new LocalReadCredentials(true);
    const { result } = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(result.current.message).not.toBeNull();
    });
    expect(result.current.book).toBeNull();
    expect(result.current.restoration).toBeNull();
});
