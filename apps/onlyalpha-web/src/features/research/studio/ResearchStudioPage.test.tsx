import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ResearchApiClient } from "../../../api/research/client";
import type {
    ResearchCalculationCatalogTransport,
    ResearchDefinitionResolutionTransport
} from "../../../api/research/schemas";
import { AppProviders } from "../../../app/providers";
import type { ResearchSubmissionKey } from "../../../domain/research/identity";
import { researchClient } from "../../../test/researchClient";
import { ResearchStudioPage } from "./ResearchStudioPage";

const exactSpecification = { schema_version: 2, exact: "server-authority" } as const;
const resolution: ResearchDefinitionResolutionTransport = {
    schema_version: 2,
    authoring_definition_fingerprint: "a".repeat(64),
    resolved_definition_fingerprint: "b".repeat(64),
    dataset_snapshot_fingerprint: "c".repeat(64),
    specification_fingerprint: "d".repeat(64),
    resolved_dataset_definition: {},
    instrument_count: 1,
    candidate_count: 1,
    candidates: [],
    published_variables: [
        {
            instance_key: "factor_1",
            output_name: "score",
            data_type: "DECIMAL",
            semantic_type: "FACTOR_SCORE"
        }
    ],
    exact_specification: exactSpecification,
    diagnostics: []
};

const catalog: ResearchCalculationCatalogTransport = {
    schema_version: 2 as const,
    calculations: [
        {
            kind: "FACTOR",
            type_reference: {
                kind: "FACTOR" as const,
                type_id: "test.factor",
                semantic_version: "1"
            },
            parameters: [],
            inputs: [],
            outputs: [
                {
                    name: "score",
                    data_type: "DECIMAL",
                    nullable: true,
                    semantic_type: "FACTOR_SCORE",
                    dimensions: ["INSTRUMENT", "TIME"],
                    unit: null
                }
            ],
            parameter_sweep_allowed: true
        },
        {
            kind: "TARGET",
            type_reference: {
                kind: "TARGET" as const,
                type_id: "test.target",
                semantic_version: "1"
            },
            parameters: [],
            inputs: [
                {
                    name: "price",
                    data_type: "DECIMAL",
                    nullable: false,
                    semantic_type: "PRICE",
                    dimensions: ["INSTRUMENT", "TIME"],
                    unit: null
                }
            ],
            outputs: [
                {
                    name: "target_value",
                    data_type: "DECIMAL",
                    nullable: true,
                    semantic_type: "TARGET_VALUE",
                    dimensions: ["INSTRUMENT", "TIME"],
                    unit: null
                }
            ],
            parameter_sweep_allowed: false
        }
    ]
};

function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((done) => {
        resolve = done;
    });
    return { promise, resolve };
}

function renderStudio(
    resolveDefinition: () => Promise<ResearchDefinitionResolutionTransport>,
    submitRun: ResearchApiClient["submitRun"] = () => Promise.reject(new Error("hold navigation"))
) {
    const client = researchClient({
        getCalculationCatalog: () => Promise.resolve(catalog),
        getUniverseCatalog: () =>
            Promise.resolve({
                schema_version: 2,
                selection_kinds: ["SINGLE_INSTRUMENT", "EXPLICIT_INSTRUMENT_SET"],
                registered_universes: []
            }),
        getStatisticsCapabilityCatalog: () =>
            Promise.resolve({
                schema_version: 2,
                statistics: [
                    {
                        statistic_type: "IC",
                        variable_kinds: ["FACTOR"],
                        variable_semantic_roles: ["FACTOR_SCORE"],
                        target_semantic_roles: ["TARGET_VALUE"],
                        target_required: true,
                        executable: true
                    }
                ]
            }),
        getDatasetFieldCatalog: () =>
            Promise.resolve({
                schema_version: 2,
                dataset_fields: [
                    {
                        source: "bar.close",
                        field_name: "close",
                        data_type: "DECIMAL",
                        semantic_roles: ["PRICE"],
                        dimensions: ["INSTRUMENT", "TIME"],
                        unit: "PRICE"
                    }
                ]
            }),
        resolveDefinition,
        submitRun
    });
    const router = createMemoryRouter(
        [
            { path: "/research/new", element: <ResearchStudioPage /> },
            { path: "/research/runs/:runId", element: <p>Run accepted</p> }
        ],
        { initialEntries: ["/research/new"] }
    );
    return render(
        <AppProviders client={client}>
            <RouterProvider router={router} />
        </AppProviders>
    );
}

async function completeMinimalDraft() {
    const user = userEvent.setup();
    await screen.findByText("Universe & Data");
    await user.type(screen.getByLabelText("Instrument IDs"), "A.XNAS");
    await user.type(screen.getByLabelText("Start"), "2026-01-01T00:00");
    await user.type(screen.getByLabelText("End"), "2026-06-01T00:00");
    const calculationsSection = screen.getByLabelText("Add Calculations").closest("section");
    if (calculationsSection === null) throw new Error("Calculations section missing");
    await user.click(within(calculationsSection).getByRole("button", { name: "Add" }));
    const targetSection = screen.getByLabelText("Add Targets").closest("section");
    if (targetSection === null) throw new Error("Targets section missing");
    await user.click(within(targetSection).getByRole("button", { name: "Add" }));
    await user.selectOptions(screen.getByLabelText("Input · price"), "bar.close");
    await user.click(screen.getByRole("button", { name: "Add Statistics" }));
    return user;
}

it("invalidates a successful Resolution after any semantic edit", async () => {
    renderStudio(() => Promise.resolve(resolution));
    const user = await completeMinimalDraft();
    await user.click(screen.getByRole("button", { name: "Resolve" }));
    expect(await screen.findByText("RESOLVED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run" })).toBeEnabled();
    await user.type(screen.getByLabelText("Instrument IDs"), ", B.XNAS");
    expect(screen.getByText("UNRESOLVED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
});

it("ignores a stale Resolution response that arrives after an edit", async () => {
    const pending = deferred<ResearchDefinitionResolutionTransport>();
    renderStudio(() => pending.promise);
    const user = await completeMinimalDraft();
    await user.click(screen.getByRole("button", { name: "Resolve" }));
    expect(screen.getByText("RESOLVING")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Instrument IDs"), ", B.XNAS");
    pending.resolve(resolution);
    await waitFor(() => {
        expect(screen.getByText("UNRESOLVED")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
});

it("submits the exact Specification object returned by the latest Resolution", async () => {
    const submit = vi.fn(
        (specification: Readonly<Record<string, unknown>>, key: ResearchSubmissionKey) => {
            void specification;
            void key;
            return Promise.reject(new Error("uncertain transport"));
        }
    );
    renderStudio(() => Promise.resolve(resolution), submit);
    const user = await completeMinimalDraft();
    await user.click(screen.getByRole("button", { name: "Resolve" }));
    await screen.findByText("RESOLVED");
    await user.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => {
        expect(submit).toHaveBeenCalledTimes(1);
    });
    expect(submit.mock.calls[0]?.[0]).toBe(exactSpecification);
});
