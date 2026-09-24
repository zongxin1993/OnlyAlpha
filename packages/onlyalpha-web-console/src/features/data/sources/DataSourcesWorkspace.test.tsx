import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { IntegrationApiClient } from "../../../api/integrations/client";
import { IntegrationWebError } from "../../../api/integrations/client";
import type {
    Integration,
    IntegrationDraft,
    IntegrationOperationalStatus,
    IntegrationProbeAttempt,
    IntegrationSummary,
    IntegrationType
} from "../../../api/integrations/model";
import { AppProviders } from "../../../app/providers";
import { researchClient } from "../../../test/researchClient";
import { DataSourceDetailPage } from "./DataSourceDetailPage";
import { DataSourcesPage } from "./DataSourcesPage";
import { NewDataSourcePage } from "./NewDataSourcePage";

const ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SECOND_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const REVISION = "a".repeat(64);

const configFields: IntegrationType["configuration_contract"]["fields"] = [
    {
        field_id: "timeout_seconds",
        display_name: "Timeout seconds",
        description: "Bounded request timeout",
        value_kind: "DURATION",
        required: true,
        secret: false,
        advanced: false,
        default: 5,
        enum_values: [],
        minimum: 1,
        maximum: 60,
        exclusive_minimum: false
    },
    {
        field_id: "api_key",
        display_name: "API key",
        description: "Credential",
        value_kind: "STRING",
        required: false,
        secret: true,
        advanced: true,
        default: null,
        enum_values: [],
        minimum: null,
        maximum: null,
        exclusive_minimum: false
    }
];

const probeContract: IntegrationType["probe_contract"] = {
    probe_version: 1,
    probe_mode: "DEFAULT_INSTRUMENT",
    default_probe_instrument: "TEST",
    user_selectable_probe_instrument: true,
    probe_checks: ["CONNECTIVITY", "AUTHENTICATION", "HISTORICAL_DATA", "REALTIME_DATA"],
    fingerprint: "d".repeat(64)
};

const descriptor: IntegrationType = {
    schema_version: 1,
    type_id: "test.market_data",
    category: "DATA_SOURCE",
    display_name: "Test Source",
    description: "Fixture",
    provider_id: "test",
    implementation_id: "test",
    implementation_version: "1",
    public_api_version: "1.1",
    capabilities: ["HISTORICAL_BARS", "INSTRUMENTS"],
    fingerprint: "b".repeat(64),
    configuration_contract: {
        schema_version: 1,
        fingerprint: "c".repeat(64),
        fields: configFields
    },
    probe_contract: probeContract
};

const untestableDescriptor: IntegrationType = {
    ...descriptor,
    type_id: "test.untestable",
    display_name: "Untestable Source",
    provider_id: "untestable",
    fingerprint: "9".repeat(64),
    capabilities: ["HISTORICAL_BARS"],
    probe_contract: null
};

const integration: Integration = {
    schema_version: 1,
    integration_id: ID,
    type_id: descriptor.type_id,
    display_name: "Fixture Source",
    lifecycle_state: "ACTIVE",
    current_revision_fingerprint: REVISION,
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z"
};
const untestableIntegration: Integration = {
    ...integration,
    integration_id: SECOND_ID,
    type_id: untestableDescriptor.type_id,
    display_name: "Untestable Fixture"
};
const summary: IntegrationSummary = {
    ...integration,
    category: "DATA_SOURCE",
    draft_version: 4,
    pinned_type_descriptor_fingerprint: descriptor.fingerprint
};
const draft: IntegrationDraft = {
    schema_version: 1,
    integration_id: ID,
    base_revision_fingerprint: REVISION,
    pinned_type_descriptor_fingerprint: descriptor.fingerprint,
    type_descriptor: descriptor,
    public_configuration: { timeout_seconds: 5 },
    probe_configuration: { instrument: "TEST" },
    draft_version: 4,
    draft_fingerprint: "e".repeat(64),
    secret_statuses: [{ field_id: "api_key", configured: true, generation: 2 }],
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z"
};
const untestableDraft: IntegrationDraft = {
    ...draft,
    integration_id: SECOND_ID,
    pinned_type_descriptor_fingerprint: untestableDescriptor.fingerprint,
    type_descriptor: untestableDescriptor,
    public_configuration: {},
    probe_configuration: null,
    secret_statuses: []
};
const operational: IntegrationOperationalStatus = {
    schema_version: 1,
    integration_id: ID,
    revision_fingerprint: REVISION,
    status: "UNKNOWN",
    probe_attempt_id: null,
    checked_at: null,
    probe_supported: true
};
const attempt: IntegrationProbeAttempt = {
    schema_version: 1,
    probe_attempt_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    integration_id: ID,
    revision_fingerprint: REVISION,
    type_id: descriptor.type_id,
    type_descriptor_fingerprint: descriptor.fingerprint,
    probe_contract_fingerprint: "d".repeat(64),
    probe_configuration_fingerprint: "f".repeat(64),
    runtime_configuration_fingerprint: "1".repeat(64),
    started_at: "2026-09-21T00:00:00Z",
    completed_at: "2026-09-21T00:00:00.140Z",
    overall_status: "DEGRADED",
    probe_instrument: "TEST",
    checks: [
        {
            check: "CONNECTIVITY",
            status: "PASS",
            latency_ms: 12,
            failure_kind: null,
            error_code: null,
            detail: "",
            observations: []
        },
        {
            check: "AUTHENTICATION",
            status: "SKIPPED",
            latency_ms: 0,
            failure_kind: null,
            error_code: null,
            detail: "",
            observations: []
        },
        {
            check: "REALTIME_DATA",
            status: "FAIL",
            latency_ms: 5000,
            failure_kind: "OFFLINE",
            error_code: "REALTIME_STREAM_UNAVAILABLE",
            detail: "WebSocket connection timeout",
            observations: []
        }
    ]
};

const unused = (): Promise<never> => Promise.reject(new Error("unused Integration API method"));

function integrationClient(overrides: Partial<IntegrationApiClient> = {}): IntegrationApiClient {
    return {
        listTypes: () => Promise.resolve([descriptor, untestableDescriptor]),
        listDataSources: () => Promise.resolve([summary]),
        createIntegration: unused,
        getIntegration: (id) =>
            Promise.resolve(id === SECOND_ID ? untestableIntegration : integration),
        getDraft: (id) => Promise.resolve(id === SECOND_ID ? untestableDraft : draft),
        updateDraft: unused,
        setSecret: unused,
        clearSecret: unused,
        resetDraftContract: unused,
        publish: unused,
        setLifecycle: unused,
        getOperationalStatus: (id) =>
            Promise.resolve(
                id === SECOND_ID
                    ? { ...operational, integration_id: SECOND_ID, probe_supported: false }
                    : operational
            ),
        probe: () => Promise.resolve(attempt),
        listProbeAttempts: () => Promise.resolve([]),
        getProbeAttempt: () => Promise.resolve(attempt),
        listRevisions: () => Promise.resolve([]),
        ...overrides
    };
}

function renderDataSources(path: string, client: IntegrationApiClient) {
    const router = createMemoryRouter(
        [
            { path: "/data/sources", element: <DataSourcesPage /> },
            { path: "/data/sources/new", element: <NewDataSourcePage /> },
            { path: "/data/sources/:integrationId", element: <DataSourceDetailPage /> }
        ],
        { initialEntries: [path] }
    );
    render(
        <AppProviders client={researchClient()} integrationClient={client}>
            <RouterProvider router={router} />
        </AppProviders>
    );
    return router;
}

it("lists configured sources with status, capabilities and non-primary archive", async () => {
    renderDataSources("/data/sources", integrationClient());
    const card = await screen.findByRole("article", { name: /Fixture Source/ });
    expect(within(card).getByText("未验证")).toBeInTheDocument();
    expect(within(card).getByText("历史")).toBeInTheDocument();
    expect(within(card).getByText("参考")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "测试连接" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "归档（删除）" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /更多操作/ }));
    expect(screen.getByRole("button", { name: "归档（删除）" })).toBeInTheDocument();
});

it("excludes disabled and archived sources from the unverified count", async () => {
    renderDataSources(
        "/data/sources",
        integrationClient({
            listDataSources: () => Promise.resolve([{ ...summary, lifecycle_state: "DISABLED" }]),
            getOperationalStatus: () => Promise.resolve({ ...operational, status: "FAILED" })
        })
    );
    expect(await screen.findByRole("article", { name: /Fixture Source/ })).toBeInTheDocument();
    expect(screen.getByText("已禁用")).toBeInTheDocument();
    expect(screen.queryByText(/异常/)).not.toBeInTheDocument();
    expect(screen.queryByText(/未验证/)).not.toBeInTheDocument();
});

it("offers the empty state before anything is configured", async () => {
    renderDataSources(
        "/data/sources",
        integrationClient({ listDataSources: () => Promise.resolve([]) })
    );
    expect(await screen.findByText("尚未配置数据源")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "添加第一个数据源" }));
    expect(screen.getByRole("tab", { name: /添加数据源/ })).toHaveAttribute(
        "aria-selected",
        "true"
    );
    expect(screen.getByRole("tabpanel", { name: /添加数据源/ })).toBeInTheDocument();
});

it("closes the overflow menu on Escape without closing the manager", async () => {
    renderDataSources("/data/sources", integrationClient());
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /更多操作/ }));
    expect(screen.getByRole("button", { name: "归档（删除）" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "归档（删除）" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /更多操作/ })).toHaveFocus();
});

it("shows the in-flight Probe state while the command is pending", async () => {
    const probe = vi.fn(() => new Promise<never>(() => undefined));
    renderDataSources("/data/sources", integrationClient({ probe }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "测试连接" }));
    expect(await screen.findByText("正在测试连接…")).toBeInTheDocument();
    expect(document.querySelector(".state-mark--probing")).not.toBeNull();
});

it("bounds a very long configured list instead of rendering every source", async () => {
    const many = Array.from({ length: 60 }, (_, index) => ({
        ...summary,
        integration_id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(index).padStart(12, "0")}`,
        display_name: `源 ${String(index)}`
    }));
    renderDataSources(
        "/data/sources",
        integrationClient({ listDataSources: () => Promise.resolve(many) })
    );
    const user = userEvent.setup();
    expect(await screen.findByText(/已显示 50 \/ 60 个数据源/)).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(50);
    await user.click(screen.getByRole("button", { name: "显示更多" }));
    expect(screen.getAllByRole("article")).toHaveLength(60);
});

it("distinguishes an empty catalog from an empty search result", async () => {
    renderDataSources(
        "/data/sources/new",
        integrationClient({ listTypes: () => Promise.resolve([]) })
    );
    expect(await screen.findByText("服务端尚未发布任何 DATA_SOURCE 类型。")).toBeInTheDocument();
});

it("drives the provider catalog from the Product API and stays on one route", async () => {
    const listTypes = vi.fn().mockResolvedValue([descriptor, untestableDescriptor]);
    const router = renderDataSources("/data/sources", integrationClient({ listTypes }));
    await userEvent.click(await screen.findByRole("tab", { name: /添加数据源/ }));
    expect(await screen.findByRole("button", { name: /Test Source/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Untestable Source/ })).toBeInTheDocument();
    expect(listTypes).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("tab", { name: /数据源绑定/ }));
    expect(screen.getByRole("tab", { name: /数据源绑定/ })).toHaveAttribute(
        "aria-selected",
        "true"
    );
    expect(router.state.location.pathname).toBe("/data/sources");
});

it.each(["UNKNOWN_OUTCOME", "TRANSPORT_ERROR"])(
    "retries an indeterminate Create %s with the same Integration and command identities",
    async (code) => {
        const createIntegration = vi
            .fn<IntegrationApiClient["createIntegration"]>()
            .mockRejectedValueOnce(new IntegrationWebError(code, "indeterminate"))
            .mockImplementationOnce((request, commandId) =>
                Promise.resolve({
                    schema_version: 1,
                    command_id: commandId,
                    integration_id: request.integration_id,
                    replayed: true,
                    outcome_kind: "DRAFT",
                    outcome_id: "1"
                })
            );
        renderDataSources("/data/sources/new", integrationClient({ createIntegration }));
        const user = userEvent.setup();
        await user.click(await screen.findByRole("button", { name: /Test Source/ }));
        await user.clear(screen.getByLabelText("显示名称"));
        await user.type(screen.getByLabelText("显示名称"), "Retry source");
        await user.click(screen.getByRole("button", { name: "创建数据源" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("indeterminate");
        await user.click(screen.getByRole("button", { name: "创建数据源" }));
        await waitFor(() => {
            expect(createIntegration).toHaveBeenCalledTimes(2);
        });
        expect(createIntegration.mock.calls[0]?.[0].integration_id).toBe(
            createIntegration.mock.calls[1]?.[0].integration_id
        );
        expect(createIntegration.mock.calls[0]?.[1]).toBe(createIntegration.mock.calls[1]?.[1]);
    }
);

it("releases Create identities after a definitive domain failure", async () => {
    const createIntegration = vi
        .fn<IntegrationApiClient["createIntegration"]>()
        .mockRejectedValue(
            new IntegrationWebError("INTEGRATION_TYPE_UNAVAILABLE", "definitive", 409)
        );
    renderDataSources("/data/sources/new", integrationClient({ createIntegration }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Test Source/ }));
    await user.clear(screen.getByLabelText("显示名称"));
    await user.type(screen.getByLabelText("显示名称"), "Rejected source");
    await user.click(screen.getByRole("button", { name: "创建数据源" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("definitive");
    await user.click(screen.getByRole("button", { name: "创建数据源" }));
    await waitFor(() => {
        expect(createIntegration).toHaveBeenCalledTimes(2);
    });
    expect(createIntegration.mock.calls[0]?.[0].integration_id).not.toBe(
        createIntegration.mock.calls[1]?.[0].integration_id
    );
    expect(createIntegration.mock.calls[0]?.[1]).not.toBe(createIntegration.mock.calls[1]?.[1]);
});

it("opens the configuration view for the created Integration", async () => {
    const createIntegration = vi.fn<IntegrationApiClient["createIntegration"]>(
        (request, commandId) =>
            Promise.resolve({
                schema_version: 1 as const,
                command_id: commandId,
                integration_id: request.integration_id,
                replayed: false,
                outcome_kind: "INTEGRATION",
                outcome_id: request.integration_id
            })
    );
    renderDataSources("/data/sources/new", integrationClient({ createIntegration }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Test Source/ }));
    await user.click(screen.getByRole("button", { name: "创建数据源" }));
    expect(await screen.findByLabelText("Timeout seconds")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeInTheDocument();
});

it("keeps Save, Publish, Contract Reset and exact-Revision Probe explicit", async () => {
    const updateDraft = vi.fn().mockResolvedValue({});
    const publish = vi.fn().mockResolvedValue({});
    const probe = vi.fn().mockResolvedValue(attempt);
    renderDataSources(`/data/sources/${ID}`, integrationClient({ updateDraft, publish, probe }));
    const user = userEvent.setup();
    expect(await screen.findByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发布 Revision" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重置契约" })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Timeout seconds"));
    await user.type(screen.getByLabelText("Timeout seconds"), "9");
    await user.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => {
        expect(updateDraft).toHaveBeenCalled();
    });
    expect(updateDraft.mock.calls[0]?.[1]).toMatchObject({
        expected_draft_version: 4,
        public_configuration: { timeout_seconds: 9 }
    });
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    await waitFor(() => {
        expect(probe).toHaveBeenCalledWith(ID, REVISION);
    });
});

it("renders every Probe capability level including skipped and undeclared", async () => {
    renderDataSources(
        `/data/sources/${ID}`,
        integrationClient({ listProbeAttempts: () => Promise.resolve([attempt]) })
    );
    const checks = await screen.findByRole("list", { name: "连接测试检查项" });
    const row = (name: string) => within(checks).getByText(name).closest("li");
    expect(row("连接")).toHaveTextContent("通过");
    expect(row("认证")).toHaveTextContent("未验证");
    expect(row("实时数据")).toHaveTextContent("失败");
    expect(row("实时数据")).toHaveTextContent("WebSocket connection timeout");
    expect(row("参考数据")).toHaveTextContent("不适用");
    expect(screen.queryByText("跳过")).not.toBeInTheDocument();
});

it("loads an exact Probe Attempt from bounded history for inspection", async () => {
    const getProbeAttempt = vi.fn().mockResolvedValue(attempt);
    renderDataSources(
        `/data/sources/${ID}`,
        integrationClient({
            listProbeAttempts: () => Promise.resolve([attempt]),
            getProbeAttempt
        })
    );
    await userEvent.click(await screen.findByRole("button", { name: "查看" }));
    expect(await screen.findByLabelText("精确 Probe Attempt")).toHaveTextContent(
        attempt.probe_attempt_id
    );
    expect(getProbeAttempt).toHaveBeenCalledWith(
        ID,
        attempt.probe_attempt_id,
        expect.any(AbortSignal)
    );
});

it("does not offer Probe for a type that declares no probe contract", async () => {
    renderDataSources(`/data/sources/${SECOND_ID}`, integrationClient());
    expect(await screen.findByText("该类型未提供连接测试")).toBeInTheDocument();
    expect(screen.queryByTestId("probe-action")).not.toBeInTheDocument();
});

it("surfaces a descriptor and server Probe-support disagreement instead of probing", async () => {
    renderDataSources(
        `/data/sources/${ID}`,
        integrationClient({
            getOperationalStatus: () => Promise.resolve({ ...operational, probe_supported: false })
        })
    );
    expect(
        await screen.findByText(/类型声明了连接测试，但服务端未报告该类型支持连接测试/)
    ).toBeInTheDocument();
    expect(screen.queryByTestId("probe-action")).not.toBeInTheDocument();
});

it("explains that Probe requires a published Revision", async () => {
    renderDataSources(
        `/data/sources/${ID}`,
        integrationClient({
            getIntegration: () =>
                Promise.resolve({ ...integration, current_revision_fingerprint: null }),
            getDraft: () => Promise.resolve({ ...draft, base_revision_fingerprint: null })
        })
    );
    expect(await screen.findByText("需要先发布一个 Revision 才能测试连接")).toBeInTheDocument();
    expect(screen.getByTestId("probe-action")).toBeDisabled();
});

it("retries an indeterminate Draft response with the same command UUID and exposes CAS conflict", async () => {
    const updateDraft = vi
        .fn()
        .mockRejectedValueOnce(new IntegrationWebError("UNKNOWN_OUTCOME", "response unreadable"))
        .mockRejectedValueOnce(
            new IntegrationWebError("INTEGRATION_DRAFT_VERSION_CONFLICT", "Refresh required", 409)
        );
    renderDataSources(`/data/sources/${ID}`, integrationClient({ updateDraft }));
    const user = userEvent.setup();
    const save = await screen.findByRole("button", { name: "保存草稿" });
    await user.click(save);
    expect(await screen.findByRole("alert")).toHaveTextContent("UNKNOWN_OUTCOME");
    expect(screen.getByRole("alert")).toHaveTextContent("结果未确认");
    await user.click(save);
    expect(await screen.findByRole("alert")).toHaveTextContent(
        "INTEGRATION_DRAFT_VERSION_CONFLICT"
    );
    expect(updateDraft.mock.calls[0]?.[2]).toBe(updateDraft.mock.calls[1]?.[2]);
});

it("retains Secret and Publish command identity across an indeterminate response", async () => {
    const setSecret = vi
        .fn()
        .mockRejectedValueOnce(new IntegrationWebError("UNKNOWN_OUTCOME", "response unreadable"))
        .mockResolvedValueOnce({});
    const publish = vi
        .fn()
        .mockRejectedValueOnce(new IntegrationWebError("UNKNOWN_OUTCOME", "response unreadable"))
        .mockResolvedValueOnce({});
    renderDataSources(`/data/sources/${ID}`, integrationClient({ setSecret, publish }));
    const user = userEvent.setup();
    const secret = await screen.findByLabelText("更换 API key");
    await user.type(secret, "transient-secret");
    await user.click(screen.getByRole("button", { name: "更换凭据" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("UNKNOWN_OUTCOME");
    expect(secret).toHaveValue("transient-secret");
    await user.click(screen.getByRole("button", { name: "更换凭据" }));
    await waitFor(() => {
        expect(setSecret).toHaveBeenCalledTimes(2);
    });
    expect(setSecret.mock.calls[0]?.[4]).toBe(setSecret.mock.calls[1]?.[4]);
    expect(secret).toHaveValue("");

    const publishButton = screen.getByRole("button", { name: "发布 Revision" });
    await user.click(publishButton);
    expect(await screen.findByRole("alert")).toHaveTextContent("UNKNOWN_OUTCOME");
    await user.click(publishButton);
    await waitFor(() => {
        expect(publish).toHaveBeenCalledTimes(2);
    });
    expect(publish.mock.calls[0]?.[2]).toBe(publish.mock.calls[1]?.[2]);
});

it("keeps an archived Integration historically readable and mutation controls disabled", async () => {
    renderDataSources(
        `/data/sources/${ID}`,
        integrationClient({
            getIntegration: () => Promise.resolve({ ...integration, lifecycle_state: "ARCHIVED" }),
            getOperationalStatus: () => Promise.resolve({ ...operational, status: "READY" }),
            listProbeAttempts: () => Promise.resolve([attempt])
        })
    );
    expect(await screen.findByText(/已归档的数据源为只读/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "发布 Revision" })).toBeDisabled();
    expect(screen.getByTestId("probe-action")).toBeDisabled();
    expect(screen.getByText("READY")).toBeInTheDocument();
});

it("exposes the Binding gap without storing a browser-local default", async () => {
    const setLifecycle = vi.fn();
    const updateDraft = vi.fn();
    renderDataSources("/data/sources", integrationClient({ setLifecycle, updateDraft }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: /数据源绑定/ }));
    expect(screen.getByText(/此 Tab 目前没有 canonical 事实/)).toBeInTheDocument();
    expect(screen.getByText(/Web 不在本地存储或推导默认来源/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /保存绑定/ })).not.toBeInTheDocument();
    expect(setLifecycle).not.toHaveBeenCalled();
    expect(updateDraft).not.toHaveBeenCalled();
});

it("switches lifecycle without turning UNKNOWN into an abnormal state", async () => {
    const setLifecycle = vi.fn().mockResolvedValue({});
    renderDataSources("/data/sources", integrationClient({ setLifecycle }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "禁用" }));
    await waitFor(() => {
        expect(setLifecycle).toHaveBeenCalledWith(ID, "ACTIVE", "DISABLED", expect.any(String));
    });
    expect(screen.queryByText("失败")).not.toBeInTheDocument();
});
