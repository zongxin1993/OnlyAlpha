import { z } from "zod";
import { factorDraftSchema } from "../../../api/privateAssets/authoring";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AppProviders } from "../../../app/providers";
import { PrivateFactorAuthoring } from "./PrivateFactorAuthoring";
const inventory = {
    schema_version: 1,
    factor_api_version: 1,
    factor_api_contract_fingerprint:
        "3265e2397f581705b67c1372483b6629671b68af71f69575c7bd602816d63be9",
    entries: []
};
beforeEach(() => {
    sessionStorage.clear();
    vi.stubEnv("VITE_ONLYALPHA_LOCAL_SESSION", "true");
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
        configurable: true,
        value: function (this: HTMLDialogElement) {
            this.setAttribute("open", "");
        }
    });
    Object.defineProperty(HTMLDialogElement.prototype, "close", {
        configurable: true,
        value: function (this: HTMLDialogElement) {
            this.removeAttribute("open");
        }
    });
});
afterEach(() => vi.unstubAllGlobals());
async function open() {
    const view = render(
        <AppProviders>
            <PrivateFactorAuthoring onChanged={vi.fn()} />
        </AppProviders>
    );
    fireEvent.click(screen.getByRole("button", { name: "创建 / 编辑私有因子" }));
    fireEvent.click(await screen.findByRole("button", { name: "新建因子" }));
    fireEvent.change(screen.getByLabelText("因子名称"), { target: { value: "动量因子" } });
    return view;
}
it("retains a lost save as UNKNOWN and only queries the original Command on recovery", async () => {
    const fetch = vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "PUT") return Promise.reject(new TypeError("connection lost"));
        return Promise.resolve(
            Response.json(url.includes("/commands/") ? null : inventory, {
                headers: { "cache-control": "no-store" }
            })
        );
    });
    vi.stubGlobal("fetch", fetch);
    await open();
    expect(screen.getByRole("button", { name: "发布 Revision" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByText(/结果不明/)).toBeVisible();
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "查询原命令结果" }));
    expect(await screen.findByText(/未被接纳/)).toBeVisible();
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
    const mutation = fetch.mock.calls.find(([, init]) => init?.method === "PUT")?.[1];
    const id = new Headers(mutation?.headers).get("Idempotency-Key");
    expect(fetch.mock.calls.some(([url]) => url.endsWith(`/commands/${id ?? ""}`))).toBe(true);
});
it("keeps invalid contract input editable without submitting a normalized financial float", async () => {
    const fetch = vi.fn(() =>
        Promise.resolve(Response.json(inventory, { headers: { "cache-control": "no-store" } }))
    );
    vi.stubGlobal("fetch", fetch);
    await open();
    fireEvent.change(screen.getByLabelText("输入契约 JSON"), {
        target: { value: '{"close":{"default":1.0000000000000001}}' }
    });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/整数|integer/);
    expect(screen.getByLabelText("输入契约 JSON")).toHaveValue(
        '{"close":{"default":1.0000000000000001}}'
    );
    await waitFor(() => {
        expect(fetch).toHaveBeenCalledTimes(1);
    });
});
it("does not infer current Draft or history from an accepted Command when authoritative refresh is unavailable", async () => {
    const fetch = vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "PUT") {
            const raw: unknown = JSON.parse(typeof init.body === "string" ? init.body : "");
            const body = z.object({ draft: factorDraftSchema }).parse(raw);
            return Promise.resolve(
                Response.json(
                    {
                        schema_version: 1,
                        command_id: new Headers(init.headers).get("Idempotency-Key"),
                        factor_id: body.draft.factor_id,
                        result: {
                            draft: body.draft,
                            draft_fingerprint: "a".repeat(64),
                            revision: null
                        }
                    },
                    { headers: { "cache-control": "no-store" } }
                )
            );
        }
        if (url !== "/api/v2/private-assets/factors")
            return Promise.resolve(
                Response.json(
                    { error: { code: "PRIVATE_ASSET_AUTHORITY_UNAVAILABLE" } },
                    { status: 503 }
                )
            );
        return Promise.resolve(
            Response.json(inventory, { headers: { "cache-control": "no-store" } })
        );
    });
    vi.stubGlobal("fetch", fetch);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/已确认|载入/);
    expect(sessionStorage.getItem("onlyalpha.private-factor.pending-command")).toBeNull();
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新载入已保存内容" })).toBeEnabled();
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
});

it("retains the original uncertain Command across remount without issuing another mutation", async () => {
    const fetch = vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "PUT") return Promise.reject(new TypeError("connection lost"));
        return Promise.resolve(
            Response.json(url.includes("/commands/") ? null : inventory, {
                headers: { "cache-control": "no-store" }
            })
        );
    });
    vi.stubGlobal("fetch", fetch);
    const first = await open();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByText(/结果不明/)).toBeVisible();
    const mutation = fetch.mock.calls.find(([, init]) => init?.method === "PUT")?.[1];
    const command = new Headers(mutation?.headers).get("Idempotency-Key");
    first.unmount();
    render(
        <AppProviders>
            <PrivateFactorAuthoring onChanged={vi.fn()} />
        </AppProviders>
    );
    fireEvent.click(screen.getByRole("button", { name: "创建 / 编辑私有因子" }));
    fireEvent.click(await screen.findByRole("button", { name: "查询原命令结果" }));
    expect(await screen.findByText(/未被接纳/)).toBeVisible();
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
    expect(fetch.mock.calls.some(([url]) => url.endsWith(`/commands/${command ?? ""}`))).toBe(true);
});
it("does not submit when the browser cannot retain its Command identity", async () => {
    const fetch = vi.fn(() =>
        Promise.resolve(Response.json(inventory, { headers: { "cache-control": "no-store" } }))
    );
    vi.stubGlobal("fetch", fetch);
    await open();
    const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("storage denied");
    });
    try {
        fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/保留|未提交/);
        expect(fetch).toHaveBeenCalledTimes(1);
    } finally {
        storage.mockRestore();
    }
});
it("initializes the first draft on an existing empty Asset without replacing its identity", async () => {
    const factor = "private.factor.empty";
    const fetch = vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "PUT") return Promise.reject(new TypeError("connection lost"));
        return Promise.resolve(
            Response.json(
                url.endsWith(factor)
                    ? {
                          schema_version: 1,
                          factor_id: factor,
                          current_revision_fingerprint: null,
                          draft: null,
                          draft_fingerprint: null,
                          revisions: []
                      }
                    : {
                          ...inventory,
                          entries: [
                              {
                                  factor_id: factor,
                                  description: "",
                                  has_draft: false,
                                  current_revision_fingerprint: null
                              }
                          ]
                      },
                { headers: { "cache-control": "no-store" } }
            )
        );
    });
    vi.stubGlobal("fetch", fetch);
    render(
        <AppProviders>
            <PrivateFactorAuthoring onChanged={vi.fn()} />
        </AppProviders>
    );
    fireEvent.click(screen.getByRole("button", { name: "创建 / 编辑私有因子" }));
    fireEvent.click(await screen.findByRole("button", { name: "未命名因子 · 草稿" }));
    fireEvent.change(await screen.findByLabelText("因子名称"), { target: { value: "已有因子" } });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await screen.findByText(/结果不明/);
    const mutation = fetch.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(mutation?.[0]).toBe(`/api/v2/private-assets/factors/${factor}/draft`);
});
