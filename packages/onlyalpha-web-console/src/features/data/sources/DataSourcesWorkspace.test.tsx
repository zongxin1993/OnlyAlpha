import { render, screen, waitFor } from "@testing-library/react";
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
const REVISION = "a".repeat(64);
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
    capabilities: ["HISTORICAL_BARS"],
    fingerprint: "b".repeat(64),
    configuration_contract: {
        schema_version: 1,
        fingerprint: "c".repeat(64),
        fields: [
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
        ]
    },
    probe_contract: {
        probe_version: 1,
        probe_mode: "DEFAULT_INSTRUMENT",
        default_probe_instrument: "TEST",
        user_selectable_probe_instrument: true,
        probe_checks: ["CONNECTIVITY"],
        fingerprint: "d".repeat(64)
    }
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
    probe_attempt_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    integration_id: ID,
    revision_fingerprint: REVISION,
    type_id: descriptor.type_id,
    type_descriptor_fingerprint: descriptor.fingerprint,
    probe_contract_fingerprint: "d".repeat(64),
    probe_configuration_fingerprint: "f".repeat(64),
    runtime_configuration_fingerprint: "1".repeat(64),
    started_at: "2026-09-21T00:00:00Z",
    completed_at: "2026-09-21T00:00:00.012Z",
    overall_status: "READY",
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
        }
    ]
};

const unused = (): Promise<never> => Promise.reject(new Error("unused Integration API method"));
function integrationClient(overrides: Partial<IntegrationApiClient> = {}): IntegrationApiClient {
    return {
        listTypes: () => Promise.resolve([descriptor]),
        listDataSources: () => Promise.resolve([summary]),
        createIntegration: unused,
        getIntegration: () => Promise.resolve(integration),
        getDraft: () => Promise.resolve(draft),
        updateDraft: unused,
        setSecret: unused,
        clearSecret: unused,
        resetDraftContract: unused,
        publish: unused,
        setLifecycle: unused,
        getOperationalStatus: () => Promise.resolve(operational),
        probe: () => Promise.resolve(attempt),
        listProbeAttempts: () => Promise.resolve([]),
        getProbeAttempt: () => Promise.resolve(attempt),
        listRevisions: () => Promise.resolve([]),
        ...overrides
    };
}

function renderPage(path: string, client: IntegrationApiClient) {
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

it("lists configured Data Sources with exact operational scope", async () => {
    renderPage("/data/sources", integrationClient());
    expect(await screen.findByRole("link", { name: "Fixture Source" })).toHaveAttribute(
        "href",
        `/data/sources/${ID}`
    );
    expect(await screen.findByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add Data Source" })).toHaveAttribute(
        "href",
        "/data/sources/new"
    );
});

it("loads server-published DataSource types on the Add page", async () => {
    const listTypes = vi.fn().mockResolvedValue([descriptor]);
    renderPage("/data/sources/new", integrationClient({ listTypes }));
    expect(await screen.findByRole("option", { name: "Test Source · test" })).toBeInTheDocument();
    expect(listTypes).toHaveBeenCalled();
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
        renderPage("/data/sources/new", integrationClient({ createIntegration }));
        const user = userEvent.setup();
        await user.selectOptions(
            await screen.findByLabelText("Data Source type"),
            descriptor.type_id
        );
        await user.type(screen.getByLabelText("Display name"), "Retry source");
        await user.click(screen.getByRole("button", { name: "Create Data Source" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("indeterminate");
        await user.click(screen.getByRole("button", { name: "Create Data Source" }));
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
    renderPage("/data/sources/new", integrationClient({ createIntegration }));
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Data Source type"), descriptor.type_id);
    await user.type(screen.getByLabelText("Display name"), "Rejected source");
    await user.click(screen.getByRole("button", { name: "Create Data Source" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("definitive");
    await user.click(screen.getByRole("button", { name: "Create Data Source" }));
    await waitFor(() => {
        expect(createIntegration).toHaveBeenCalledTimes(2);
    });
    expect(createIntegration.mock.calls[0]?.[0].integration_id).not.toBe(
        createIntegration.mock.calls[1]?.[0].integration_id
    );
    expect(createIntegration.mock.calls[0]?.[1]).not.toBe(createIntegration.mock.calls[1]?.[1]);
});

it("uses new Create identities when the logical intent changes after an unknown outcome", async () => {
    const createIntegration = vi
        .fn<IntegrationApiClient["createIntegration"]>()
        .mockRejectedValue(new IntegrationWebError("UNKNOWN_OUTCOME", "indeterminate"));
    renderPage("/data/sources/new", integrationClient({ createIntegration }));
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Data Source type"), descriptor.type_id);
    const displayName = screen.getByLabelText("Display name");
    await user.type(displayName, "First source");
    await user.click(screen.getByRole("button", { name: "Create Data Source" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("indeterminate");
    await user.clear(displayName);
    await user.type(displayName, "Second source");
    await user.click(screen.getByRole("button", { name: "Create Data Source" }));
    await waitFor(() => {
        expect(createIntegration).toHaveBeenCalledTimes(2);
    });
    expect(createIntegration.mock.calls[0]?.[0].integration_id).not.toBe(
        createIntegration.mock.calls[1]?.[0].integration_id
    );
    expect(createIntegration.mock.calls[0]?.[1]).not.toBe(createIntegration.mock.calls[1]?.[1]);
});

it("does not revive a stale Create command when a previous logical intent returns", async () => {
    const createIntegration = vi
        .fn<IntegrationApiClient["createIntegration"]>()
        .mockRejectedValue(new IntegrationWebError("UNKNOWN_OUTCOME", "indeterminate"));
    renderPage("/data/sources/new", integrationClient({ createIntegration }));
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Data Source type"), descriptor.type_id);
    const displayName = screen.getByLabelText("Display name");
    for (const [index, name] of ["First source", "Second source", "First source"].entries()) {
        await user.clear(displayName);
        await user.type(displayName, name);
        await user.click(screen.getByRole("button", { name: "Create Data Source" }));
        await waitFor(() => {
            expect(createIntegration).toHaveBeenCalledTimes(index + 1);
        });
    }
    expect(createIntegration.mock.calls[0]?.[0].integration_id).not.toBe(
        createIntegration.mock.calls[2]?.[0].integration_id
    );
    expect(createIntegration.mock.calls[0]?.[1]).not.toBe(createIntegration.mock.calls[2]?.[1]);
});

it("keeps Save, Publish, Contract Reset and exact-Revision Probe explicit", async () => {
    const updateDraft = vi.fn().mockResolvedValue({});
    const publish = vi.fn().mockResolvedValue({});
    const probe = vi.fn().mockResolvedValue(attempt);
    renderPage(`/data/sources/${ID}`, integrationClient({ updateDraft, publish, probe }));
    const user = userEvent.setup();
    expect(await screen.findByText("UNKNOWN", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Draft" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Contract Reset" })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Timeout seconds"));
    await user.type(screen.getByLabelText("Timeout seconds"), "9");
    await user.click(screen.getByRole("button", { name: "Save Draft" }));
    await waitFor(() => {
        expect(updateDraft).toHaveBeenCalled();
    });
    expect(updateDraft.mock.calls[0]?.[1]).toMatchObject({
        expected_draft_version: 4,
        public_configuration: { timeout_seconds: 9 }
    });
    await user.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => {
        expect(probe).toHaveBeenCalledWith(ID, REVISION);
    });
});

it("retries an indeterminate Draft response with the same command UUID and exposes CAS conflict", async () => {
    const updateDraft = vi
        .fn()
        .mockRejectedValueOnce(new IntegrationWebError("UNKNOWN_OUTCOME", "response unreadable"))
        .mockRejectedValueOnce(
            new IntegrationWebError("INTEGRATION_DRAFT_VERSION_CONFLICT", "Refresh required", 409)
        );
    renderPage(`/data/sources/${ID}`, integrationClient({ updateDraft }));
    const user = userEvent.setup();
    const save = await screen.findByRole("button", { name: "Save Draft" });
    await user.click(save);
    expect(await screen.findByRole("alert")).toHaveTextContent("UNKNOWN_OUTCOME");
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
    renderPage(`/data/sources/${ID}`, integrationClient({ setSecret, publish }));
    const user = userEvent.setup();
    const secret = await screen.findByLabelText("Replace API key");
    await user.type(secret, "transient-secret");
    await user.click(screen.getByRole("button", { name: "Replace API key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("UNKNOWN_OUTCOME");
    expect(secret).toHaveValue("transient-secret");
    await user.click(screen.getByRole("button", { name: "Replace API key" }));
    await waitFor(() => {
        expect(setSecret).toHaveBeenCalledTimes(2);
    });
    expect(setSecret.mock.calls[0]?.[4]).toBe(setSecret.mock.calls[1]?.[4]);
    expect(secret).toHaveValue("");

    const publishButton = screen.getByRole("button", { name: "Publish" });
    await user.click(publishButton);
    expect(await screen.findByRole("alert")).toHaveTextContent("UNKNOWN_OUTCOME");
    await user.click(publishButton);
    await waitFor(() => {
        expect(publish).toHaveBeenCalledTimes(2);
    });
    expect(publish.mock.calls[0]?.[2]).toBe(publish.mock.calls[1]?.[2]);
});

it("keeps an archived Integration historically readable and mutation controls disabled", async () => {
    renderPage(
        `/data/sources/${ID}`,
        integrationClient({
            getIntegration: () => Promise.resolve({ ...integration, lifecycle_state: "ARCHIVED" }),
            listProbeAttempts: () => Promise.resolve([attempt])
        })
    );
    expect(await screen.findByText(/Archived Integration is read-only/)).toBeInTheDocument();
    expect(screen.getByText("READY", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Test connection" })).toBeDisabled();
});

it("loads an exact Probe Attempt from bounded history for inspection", async () => {
    const getProbeAttempt = vi.fn().mockResolvedValue(attempt);
    renderPage(
        `/data/sources/${ID}`,
        integrationClient({
            listProbeAttempts: () => Promise.resolve([attempt]),
            getProbeAttempt
        })
    );

    await userEvent.click(await screen.findByRole("button", { name: "Inspect" }));

    expect(await screen.findByLabelText("Exact Probe Attempt")).toHaveTextContent(
        attempt.probe_attempt_id
    );
    expect(getProbeAttempt).toHaveBeenCalledWith(
        ID,
        attempt.probe_attempt_id,
        expect.any(AbortSignal)
    );
});

it("projects a new Revision as UNKNOWN without hiding prior READY evidence", async () => {
    const revision2 = "2".repeat(64);
    let current = REVISION;
    const publish = vi.fn(() => {
        current = revision2;
        return Promise.resolve({
            schema_version: 1 as const,
            command_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            integration_id: ID,
            replayed: false,
            outcome_kind: "REVISION",
            outcome_id: revision2
        });
    });
    renderPage(
        `/data/sources/${ID}`,
        integrationClient({
            getIntegration: () =>
                Promise.resolve({ ...integration, current_revision_fingerprint: current }),
            getOperationalStatus: () =>
                Promise.resolve({
                    ...operational,
                    revision_fingerprint: current,
                    status: current === REVISION ? "READY" : "UNKNOWN"
                }),
            listProbeAttempts: () => Promise.resolve([attempt]),
            publish
        })
    );
    expect(await screen.findByText(REVISION, { selector: "dd" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText(revision2, { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("UNKNOWN", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("READY", { selector: "td" })).toBeInTheDocument();
});
