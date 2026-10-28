import { act, renderHook, waitFor } from "@testing-library/react";
import { LocalReadCredentials } from "../../api/marketData/localReadCredentials";
import { marketDataBarSemantic } from "../../api/marketData/model";
import type { WorkspaceBook } from "../../api/workspace/client";
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
    let book: WorkspaceBook = {
        schema_version: 3,
        version: 0,
        active_workspace_id: null,
        workspaces: []
    };
    const writes: unknown[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((_url: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (init?.method === "PUT") {
                    if (typeof init.body !== "string") throw new Error("Expected JSON save intent");
                    const body = JSON.parse(init.body) as WorkspaceBook;
                    writes.push(body);
                    book = {
                        schema_version: 3,
                        version: 1,
                        active_workspace_id: body.active_workspace_id,
                        workspaces: body.workspaces
                    };
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
    await act(() => result.current.save(configuration, "观察", null));
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
        expected_version: 0,
        workspaces: [expect.objectContaining({ name: "观察", configuration })]
    });
    expect(result.current.book?.version).toBe(1);
    expect(result.current.message).toBeNull();
    expect(result.current.restoration).toBe(restore);
});
it("retains UNKNOWN across remount and resolves the original command without another save", async () => {
    let book: WorkspaceBook = {
        schema_version: 3,
        version: 0,
        active_workspace_id: null,
        workspaces: []
    };
    let writes = 0;
    const urls: string[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                urls.push(url);
                if (init?.method === "PUT") {
                    writes++;
                    if (typeof init.body !== "string") throw new Error("Expected intent");
                    const body = JSON.parse(init.body) as WorkspaceBook;
                    book = {
                        schema_version: 3,
                        version: 1,
                        active_workspace_id: body.active_workspace_id,
                        workspaces: body.workspaces
                    };
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
    await act(() => first.result.current.save(configuration, "观察", null));
    const id = first.result.current.pending;
    expect(id).not.toBeNull();
    first.unmount();
    const next = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(next.result.current.book).not.toBeNull();
    });
    await act(() => next.result.current.save(configuration, "观察", null));
    expect(writes).toBe(1);
    await act(() => next.result.current.resolvePending());
    expect(urls).toContain(`/api/v2/workspace/commands/${id ?? ""}`);
    expect(next.result.current.pending).toBeNull();
    expect(writes).toBe(1);
});
it("keeps the draft after a version conflict until an explicit reload", async () => {
    let book: WorkspaceBook = {
        schema_version: 3,
        version: 1,
        active_workspace_id: "00000000-0000-4000-8000-000000000002",
        workspaces: [
            { workspace_id: "00000000-0000-4000-8000-000000000002", name: "观察", configuration }
        ]
    };
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
    await act(() => result.current.save(configuration, "观察", null));
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
                        schema_version: 3,
                        version: 1,
                        active_workspace_id: "00000000-0000-4000-8000-000000000002",
                        workspaces: [
                            {
                                workspace_id: "00000000-0000-4000-8000-000000000002",
                                name: "观察",
                                configuration: { ...configuration, bars: [] }
                            }
                        ]
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

it("saves two named choices, loads the exact ID, and restores only the explicitly selected configuration", async () => {
    let book: WorkspaceBook = {
        schema_version: 3,
        version: 0,
        active_workspace_id: null,
        workspaces: []
    };
    const writes: unknown[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn((_url: string, init?: RequestInit) =>
            Promise.resolve().then(() => {
                if (init?.method === "PUT") {
                    if (typeof init.body !== "string") throw new Error("JSON intent required");
                    const body = JSON.parse(init.body) as WorkspaceBook;
                    writes.push(body);
                    book = {
                        schema_version: 3,
                        version: book.version + 1,
                        active_workspace_id: body.active_workspace_id,
                        workspaces: body.workspaces
                    };
                }
                return new Response(JSON.stringify(book));
            })
        )
    );
    const credentials = new LocalReadCredentials(true);
    const hook = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(hook.result.current.book).not.toBeNull();
    });
    const initial = hook.result.current.restoration;
    await act(() => hook.result.current.save(configuration, "比特币观察", null));
    const firstId = book.active_workspace_id;
    if (firstId === null) throw new Error("Saved workspace ID missing");
    const second = { ...configuration, bar_semantic: marketDataBarSemantic(15) };
    await act(() => hook.result.current.save(second, "十五分钟", null));
    expect(book.workspaces).toHaveLength(2);
    expect(hook.result.current.restoration).toBe(initial);
    await act(() => hook.result.current.reload(undefined, false));
    expect(hook.result.current.restoration).toBe(initial);
    await act(() => hook.result.current.load(firstId));
    expect(hook.result.current.restoration?.configuration).toEqual(configuration);
    expect(book.active_workspace_id).toBe(firstId);
    expect(hook.result.current.message).toBeNull();
    expect(writes).toHaveLength(3);
    hook.unmount();
    const restarted = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(restarted.result.current.restoration?.configuration).toEqual(configuration);
    });
    expect(writes).toHaveLength(3);
});

it("accepts 120 supplementary-plane characters but rejects a 121-character workspace name", async () => {
    const id = "00000000-0000-4000-8000-000000000002";
    let name = "😀".repeat(120);
    vi.stubGlobal(
        "fetch",
        vi.fn(() =>
            Promise.resolve(
                new Response(
                    JSON.stringify({
                        schema_version: 3,
                        version: 1,
                        active_workspace_id: id,
                        workspaces: [{ workspace_id: id, name, configuration }]
                    })
                )
            )
        )
    );
    const credentials = new LocalReadCredentials(true);
    const first = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(first.result.current.book?.workspaces[0]?.name).toBe(name);
    });
    first.unmount();
    name = "😀".repeat(121);
    const invalid = renderHook(() => useDefaultWorkspace(credentials));
    await waitFor(() => {
        expect(invalid.result.current.message).not.toBeNull();
    });
    expect(invalid.result.current.book).toBeNull();
});
