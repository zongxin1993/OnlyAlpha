import { z } from "zod";
import { factorDraftSchema } from "../../../api/privateAssets/authoring";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AppProviders } from "../../../app/providers";
import { PrivateFactorAuthoring } from "./PrivateFactorAuthoring";
const inventory = {
    new_factor_defaults: { display_name: "私有因子 1", usage_summary: "自定义计算；用途待完善。" },
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
    expect(screen.getByRole("button", { name: "发布内容版本" })).toBeDisabled();
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
    fireEvent.click(screen.getByRole("button", { name: "所需数据高级 JSON" }));
    fireEvent.change(screen.getByLabelText("输入契约 JSON"), {
        target: { value: '{"close":{"default":1.0000000000000001}}' }
    });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByText(/契约数值只支持安全范围内的整数/)).toBeVisible();
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
                            revision: null,
                            display: {
                                schema_version: 1,
                                factor_id: body.draft.factor_id,
                                display_name: "动量因子",
                                usage_summary: "自定义计算；用途待完善。",
                                edit_number: 1
                            },
                            display_fingerprint: "b".repeat(64),
                            display_version: null
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
                          revisions: [],
                          display: {
                              schema_version: 1,
                              factor_id: factor,
                              ...inventory.new_factor_defaults,
                              edit_number: 1
                          },
                          display_fingerprint: "b".repeat(64)
                      }
                    : {
                          ...inventory,
                          entries: [
                              {
                                  factor_id: factor,
                                  display: {
                                      schema_version: 1,
                                      factor_id: factor,
                                      ...inventory.new_factor_defaults,
                                      edit_number: 1
                                  },
                                  display_fingerprint: "b".repeat(64),
                                  current_display_version: null,
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
    fireEvent.click(await screen.findByRole("button", { name: "私有因子 1 · 草稿" }));
    fireEvent.change(await screen.findByLabelText("因子名称"), { target: { value: "已有因子" } });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await screen.findByText(/结果不明/);
    const mutation = fetch.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(mutation?.[0]).toBe(`/api/v2/private-assets/factors/${factor}/draft`);
});

it("shows a meaningful default name and a separate editable usage summary", async () => {
    vi.stubGlobal(
        "fetch",
        vi.fn(() =>
            Promise.resolve(Response.json(inventory, { headers: { "cache-control": "no-store" } }))
        )
    );
    render(
        <AppProviders>
            <PrivateFactorAuthoring onChanged={vi.fn()} />
        </AppProviders>
    );
    fireEvent.click(screen.getByRole("button", { name: "创建 / 编辑私有因子" }));
    fireEvent.click(await screen.findByRole("button", { name: "新建因子" }));
    expect(screen.getByLabelText("因子名称")).toHaveValue("私有因子 1");
    expect(screen.getByLabelText("用途说明")).toHaveValue("自定义计算；用途待完善。");
    expect(screen.queryByLabelText("版本内容说明")).toBeInTheDocument();
});

it("preserves unsaved content and its original CAS token while saving display metadata", async () => {
    let saved: z.infer<typeof factorDraftSchema> | null = null;
    let renamed = false;
    const requests: string[] = [];
    const reply = (value: unknown) =>
        Promise.resolve(Response.json(value, { headers: { "cache-control": "no-store" } }));
    const fetch = vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "PUT" && url.endsWith("/draft")) {
            const body = z
                .object({
                    draft: factorDraftSchema,
                    expected_draft_fingerprint: z.string().nullable()
                })
                .parse(JSON.parse(typeof init.body === "string" ? init.body : ""));
            requests.push(body.expected_draft_fingerprint ?? "first");
            if (saved !== null)
                return Promise.resolve(
                    Response.json(
                        { error: { code: "PRIVATE_FACTOR_DRAFT_CONFLICT" } },
                        { status: 409 }
                    )
                );
            saved = body.draft;
            return reply({
                schema_version: 1,
                command_id: new Headers(init.headers).get("Idempotency-Key"),
                factor_id: saved.factor_id,
                result: {
                    draft: saved,
                    draft_fingerprint: "a".repeat(64),
                    revision: null,
                    display: {
                        schema_version: 1,
                        factor_id: saved.factor_id,
                        ...inventory.new_factor_defaults,
                        edit_number: 1
                    },
                    display_fingerprint: "b".repeat(64),
                    display_version: null
                }
            });
        }
        if (saved === null) return reply(inventory);
        const display = {
            schema_version: 1,
            factor_id: saved.factor_id,
            display_name: renamed ? "新名称" : inventory.new_factor_defaults.display_name,
            usage_summary: inventory.new_factor_defaults.usage_summary,
            edit_number: renamed ? 2 : 1
        };
        if (init?.method === "PUT" && url.endsWith("/display")) {
            renamed = true;
            return reply({
                schema_version: 1,
                command_id: new Headers(init.headers).get("Idempotency-Key"),
                factor_id: saved.factor_id,
                result: {
                    draft: null,
                    draft_fingerprint: null,
                    revision: null,
                    display: { ...display, display_name: "新名称", edit_number: 2 },
                    display_fingerprint: "d".repeat(64),
                    display_version: null
                }
            });
        }
        if (url === "/api/v2/private-assets/factors") return reply(inventory);
        return reply({
            schema_version: 1,
            factor_id: saved.factor_id,
            current_revision_fingerprint: null,
            draft: renamed ? { ...saved, description: "changed elsewhere" } : saved,
            draft_fingerprint: (renamed ? "c" : "a").repeat(64),
            revisions: [],
            display,
            display_fingerprint: (renamed ? "d" : "b").repeat(64)
        });
    });
    vi.stubGlobal("fetch", fetch);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await screen.findByText("草稿已保存");
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "保存名称和用途" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "所需数据高级 JSON" }));
    fireEvent.change(screen.getByLabelText("输入契约 JSON"), { target: { value: "{" } });
    fireEvent.change(screen.getByLabelText("因子名称"), { target: { value: "新名称" } });
    fireEvent.click(screen.getByRole("button", { name: "保存名称和用途" }));
    await screen.findByText(/名称和用途已保存/);
    await waitFor(() => {
        expect(screen.getByRole("button", { name: "保存草稿" })).toBeEnabled();
    });
    expect(screen.getByLabelText("输入契约 JSON")).toHaveValue("{");
    fireEvent.change(screen.getByLabelText("输入契约 JSON"), { target: { value: "{}" } });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/其他操作修改/);
    expect(requests).toEqual(["first", "a".repeat(64)]);
});

it("recovers an uncertain display edit after remount by querying its original Command only", async () => {
    const factor = "private.factor.pending_display";
    let recovered = false;
    const display = () => ({
        schema_version: 1,
        factor_id: factor,
        display_name: recovered ? "改名后" : "原名称",
        usage_summary: "用途说明",
        edit_number: recovered ? 2 : 1
    });
    const reply = (value: unknown) =>
        Promise.resolve(Response.json(value, { headers: { "cache-control": "no-store" } }));
    const fetch = vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "PUT") return Promise.reject(new TypeError("ack lost"));
        if (url.includes("/commands/")) {
            recovered = true;
            return reply({
                schema_version: 1,
                command_id: url.split("/").at(-1),
                factor_id: factor,
                result: {
                    draft: null,
                    draft_fingerprint: null,
                    revision: null,
                    display: display(),
                    display_fingerprint: "d".repeat(64),
                    display_version: null
                }
            });
        }
        if (url.endsWith(factor))
            return reply({
                schema_version: 1,
                factor_id: factor,
                current_revision_fingerprint: null,
                draft: null,
                draft_fingerprint: null,
                revisions: [],
                display: display(),
                display_fingerprint: (recovered ? "d" : "b").repeat(64)
            });
        return reply({
            ...inventory,
            entries: [
                {
                    factor_id: factor,
                    display: display(),
                    display_fingerprint: "b".repeat(64),
                    has_draft: false,
                    current_revision_fingerprint: null,
                    current_display_version: null
                }
            ]
        });
    });
    vi.stubGlobal("fetch", fetch);
    const mount = () =>
        render(
            <AppProviders>
                <PrivateFactorAuthoring onChanged={vi.fn()} />
            </AppProviders>
        );
    const first = mount();
    fireEvent.click(screen.getByRole("button", { name: "创建 / 编辑私有因子" }));
    fireEvent.click(await screen.findByRole("button", { name: "原名称 · 草稿" }));
    fireEvent.change(await screen.findByLabelText("因子名称"), { target: { value: "改名后" } });
    fireEvent.click(screen.getByRole("button", { name: "保存名称和用途" }));
    await screen.findByText(/结果不明/);
    expect(sessionStorage.getItem("onlyalpha.private-factor.pending-command")).toContain(
        '"kind":"DISPLAY"'
    );
    first.unmount();
    mount();
    fireEvent.click(screen.getByRole("button", { name: "创建 / 编辑私有因子" }));
    fireEvent.click(await screen.findByRole("button", { name: "查询原命令结果" }));
    await screen.findByText(/名称和用途已保存/);
    await waitFor(() => {
        expect(screen.getByLabelText("因子名称")).toHaveValue("改名后");
    });
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
    expect(sessionStorage.getItem("onlyalpha.private-factor.pending-command")).toBeNull();
});

it("offers ordinary contract forms and independent advanced modes without hidden writes", async () => {
    const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
        Promise.resolve(Response.json(inventory, { headers: { "cache-control": "no-store" } }))
    );
    vi.stubGlobal("fetch", fetch);
    await open();
    expect(screen.getByRole("region", { name: "所需数据" })).toBeVisible();
    expect(screen.getByLabelText("所需数据第 1 项代码中的名称")).toHaveValue("close");
    expect(screen.getByText("没有可调参数")).toBeVisible();
    expect(screen.queryByLabelText("输入契约 JSON")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "所需数据高级 JSON" }));
    const raw = ' { "close" : {"type":"DECIMAL","extra":{"a":[1,"1",null]}} } ';
    fireEvent.change(screen.getByLabelText("输入契约 JSON"), { target: { value: raw } });
    fireEvent.click(screen.getByRole("button", { name: "切换到所需数据表单" }));
    expect(screen.getByLabelText("输入契约 JSON")).toHaveValue(raw);
    expect(screen.getByText(/无法无损转换/)).toBeVisible();
    expect(screen.getByLabelText("计算结果第 1 项结果字段名")).toHaveValue("value");
    fireEvent.click(screen.getByRole("button", { name: "添加参数" }));
    fireEvent.change(screen.getByLabelText("可调参数第 1 项代码中的名称"), {
        target: { value: "period" }
    });
    expect(screen.getByLabelText("可调参数第 1 项使用时必须填写")).toBeChecked();
    expect(screen.getByLabelText("可调参数第 1 项设置默认值")).not.toBeChecked();
    expect(
        fetch.mock.calls.filter(([, init]) => init?.method === "PUT" || init?.method === "POST")
    ).toHaveLength(0);
});
