import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ResearchApiClient } from "../../api/research/client";
import { ResearchWebError } from "../../api/research/errors";
import type {
    ResearchDatasetFieldCatalogTransport,
    ResearchUniverseCatalogTransport
} from "../../api/research/schemas";
import { AppProviders } from "../../app/providers";
import { researchClient } from "../../test/researchClient";
import { ResearchInputsPage } from "./ResearchInputsPage";

const universeCatalog: ResearchUniverseCatalogTransport = {
    schema_version: 2,
    selection_kinds: ["SINGLE_INSTRUMENT", "EXPLICIT_INSTRUMENT_SET"],
    registered_universes: [
        {
            registered_id: "core-equities",
            kind: "EXPLICIT_INSTRUMENT_SET",
            display_metadata: {
                label: "Core equities",
                description: "<img src=x onerror=alert(1)>",
                structured: { hidden: "Not presentation text" }
            }
        },
        {
            registered_id: "growth-equities",
            kind: "EXPLICIT_INSTRUMENT_SET",
            display_metadata: { label: "Growth equities" }
        }
    ]
};
const fieldCatalog: ResearchDatasetFieldCatalogTransport = {
    schema_version: 2,
    dataset_fields: [
        {
            source: "bar.close",
            field_name: "close",
            data_type: "DECIMAL",
            semantic_roles: ["PRICE"],
            dimensions: ["INSTRUMENT", "TIME"],
            unit: "PRICE"
        },
        {
            source: "bar.volume",
            field_name: "volume",
            data_type: "DECIMAL",
            semantic_roles: ["VOLUME"],
            dimensions: ["INSTRUMENT", "TIME"],
            unit: null
        }
    ]
};

function renderInputs(overrides: Partial<ResearchApiClient> = {}) {
    const client = researchClient({
        getUniverseCatalog: () => Promise.resolve(universeCatalog),
        getDatasetFieldCatalog: () => Promise.resolve(fieldCatalog),
        ...overrides
    });
    const router = createMemoryRouter(
        [
            { path: "/data/inputs", element: <ResearchInputsPage /> },
            { path: "/research/new", element: <h1>Research Builder</h1> }
        ],
        { initialEntries: ["/data/inputs"] }
    );
    return render(
        <AppProviders client={client}>
            <RouterProvider router={router} />
        </AppProviders>
    );
}

it("renders admitted input capabilities and safely treats metadata as text", async () => {
    const getUniverseCatalog = vi.fn(() => Promise.resolve(universeCatalog));
    const getDatasetFieldCatalog = vi.fn(() => Promise.resolve(fieldCatalog));
    const { container } = renderInputs({ getUniverseCatalog, getDatasetFieldCatalog });
    expect(screen.getByRole("heading", { name: "Research Inputs" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "core-equities" })).toBeInTheDocument();
    expect(screen.getByText("bar.close")).toBeInTheDocument();
    expect(screen.getByText("SINGLE_INSTRUMENT")).toBeInTheDocument();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryByText("Not presentation text")).not.toBeInTheDocument();
    expect(screen.getByText(/do not prove stored data availability/)).toBeInTheDocument();
    expect(getUniverseCatalog).toHaveBeenCalledTimes(1);
    expect(getDatasetFieldCatalog).toHaveBeenCalledTimes(1);
});

it("filters only visible catalog rows and restores them when cleared", async () => {
    const getUniverseCatalog = vi.fn(() => Promise.resolve(universeCatalog));
    const getDatasetFieldCatalog = vi.fn(() => Promise.resolve(fieldCatalog));
    renderInputs({ getUniverseCatalog, getDatasetFieldCatalog });
    await screen.findByText("bar.close");
    const user = userEvent.setup();
    const filter = screen.getByRole("searchbox", { name: "Filter research inputs" });
    await user.type(filter, "price");
    expect(screen.getByText("bar.close")).toBeInTheDocument();
    expect(screen.queryByText("bar.volume")).not.toBeInTheDocument();
    expect(screen.getByText("No registered universes match this filter.")).toBeInTheDocument();
    await user.clear(filter);
    await user.type(filter, "missing-capability");
    expect(screen.getByText("No dataset fields match this filter.")).toBeInTheDocument();
    await user.clear(filter);
    expect(screen.getByText("bar.volume")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "growth-equities" })).toBeInTheDocument();
    expect(getUniverseCatalog).toHaveBeenCalledTimes(1);
    expect(getDatasetFieldCatalog).toHaveBeenCalledTimes(1);
});

it("shows honest empty catalogs without inventing data records", async () => {
    renderInputs({
        getUniverseCatalog: () =>
            Promise.resolve({ schema_version: 2, selection_kinds: [], registered_universes: [] }),
        getDatasetFieldCatalog: () => Promise.resolve({ schema_version: 2, dataset_fields: [] })
    });
    expect(await screen.findByText("No registered universes are published.")).toBeInTheDocument();
    expect(screen.getByText("No Universe selection kinds are published.")).toBeInTheDocument();
    expect(screen.getByText("No dataset-field capabilities are published.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("bar.close")).not.toBeInTheDocument();
});

it("keeps pending and unavailable panels separate and retries only the failed query", async () => {
    let resolveUniverses!: (value: ResearchUniverseCatalogTransport) => void;
    const pendingUniverses = new Promise<ResearchUniverseCatalogTransport>((resolve) => {
        resolveUniverses = resolve;
    });
    const getDatasetFieldCatalog = vi
        .fn<ResearchApiClient["getDatasetFieldCatalog"]>()
        .mockRejectedValueOnce(new ResearchWebError("TRANSPORT_ERROR", "Input API is unavailable"))
        .mockResolvedValue(fieldCatalog);
    renderInputs({
        getUniverseCatalog: () => pendingUniverses,
        getDatasetFieldCatalog
    });
    expect(screen.getByText("Loading authoritative Universe catalog…")).toHaveAttribute(
        "role",
        "status"
    );
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Input API is unavailable");
    expect(screen.queryByText("bar.close")).not.toBeInTheDocument();
    await userEvent.click(within(error).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("bar.close")).toBeInTheDocument();
    resolveUniverses(universeCatalog);
    expect(await screen.findByRole("heading", { name: "core-equities" })).toBeInTheDocument();
    expect(getDatasetFieldCatalog).toHaveBeenCalledTimes(2);
});

it("links back into the existing Research authoring workflow", async () => {
    renderInputs();
    await userEvent.click(screen.getByRole("link", { name: "New Research →" }));
    expect(screen.getByRole("heading", { name: "Research Builder" })).toBeInTheDocument();
});
