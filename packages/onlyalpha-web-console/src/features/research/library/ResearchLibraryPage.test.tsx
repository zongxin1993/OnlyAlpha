import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ResearchApiClient } from "../../../api/research/client";
import { ResearchWebError } from "../../../api/research/errors";
import type {
    ResearchCalculationCatalogTransport,
    ResearchStatisticsCapabilityCatalogTransport
} from "../../../api/research/schemas";
import { AppProviders } from "../../../app/providers";
import { researchClient } from "../../../test/researchClient";
import { ResearchLibraryPage } from "./ResearchLibraryPage";

const calculations: ResearchCalculationCatalogTransport = {
    schema_version: 2,
    calculations: [
        {
            kind: "INDICATOR",
            type_reference: {
                kind: "INDICATOR",
                type_id: "test.indicator.rsi",
                semantic_version: "1.2.3"
            },
            parameters: [
                {
                    name: "period",
                    type: "INTEGER",
                    required: false,
                    default: { type: "INTEGER", value: 14 },
                    minimum: { type: "INTEGER", value: 2 },
                    maximum: { type: "INTEGER", value: 100 },
                    enum_values: [],
                    uppercase: false
                }
            ],
            inputs: [
                {
                    name: "price",
                    data_type: "DECIMAL",
                    nullable: false,
                    semantic_type: "PRICE",
                    dimensions: ["INSTRUMENT", "TIME"],
                    unit: "PRICE"
                }
            ],
            outputs: [
                {
                    name: "rsi",
                    data_type: "DECIMAL",
                    nullable: true,
                    semantic_type: "INDICATOR_VALUE",
                    dimensions: ["INSTRUMENT", "TIME"],
                    unit: null
                }
            ],
            parameter_sweep_allowed: true
        },
        {
            kind: "TARGET",
            type_reference: {
                kind: "TARGET",
                type_id: "test.target.forward",
                semantic_version: "1"
            },
            parameters: [],
            inputs: [],
            outputs: [],
            parameter_sweep_allowed: false
        }
    ]
};
const statistics: ResearchStatisticsCapabilityCatalogTransport = {
    schema_version: 2,
    statistics: [
        {
            statistic_type: "IC",
            variable_kinds: ["FACTOR"],
            variable_semantic_roles: ["FACTOR_SCORE"],
            target_semantic_roles: ["TARGET_VALUE"],
            target_required: true,
            executable: true
        },
        {
            statistic_type: "REFERENCE_STATISTIC",
            variable_kinds: ["INDICATOR"],
            variable_semantic_roles: ["INDICATOR_VALUE"],
            target_semantic_roles: [],
            target_required: false,
            executable: false
        }
    ]
};

function renderLibrary(overrides: Partial<ResearchApiClient> = {}) {
    const client = researchClient({
        getCalculationCatalog: () => Promise.resolve(calculations),
        getStatisticsCapabilityCatalog: () => Promise.resolve(statistics),
        ...overrides
    });
    const router = createMemoryRouter(
        [
            { path: "/research/library", element: <ResearchLibraryPage /> },
            { path: "/research/new", element: <h1>Research Builder</h1> }
        ],
        { initialEntries: ["/research/library"] }
    );
    return render(
        <AppProviders client={client}>
            <RouterProvider router={router} />
        </AppProviders>
    );
}

it("renders exact catalog versions, constraints, ports, and executable capability facts", async () => {
    const getCalculationCatalog = vi.fn(() => Promise.resolve(calculations));
    const getStatisticsCapabilityCatalog = vi.fn(() => Promise.resolve(statistics));
    renderLibrary({ getCalculationCatalog, getStatisticsCapabilityCatalog });
    expect(screen.getByRole("heading", { name: "Research Library" })).toBeInTheDocument();
    const indicator = (await screen.findByRole("heading", { name: "test.indicator.rsi" })).closest(
        "article"
    );
    if (indicator === null) throw new Error("Indicator card missing");
    expect(indicator).toHaveTextContent("Semantic version 1.2.3 · Parameter sweep allowed");
    await userEvent.click(within(indicator).getByText("Inspect parameters and ports"));
    expect(within(indicator).getByText("INTEGER · 14")).toBeInTheDocument();
    expect(within(indicator).getByText("INTEGER · 2")).toBeInTheDocument();
    expect(within(indicator).getByText("INTEGER · 100")).toBeInTheDocument();
    expect(within(indicator).getByRole("cell", { name: "rsi" })).toBeInTheDocument();
    expect(screen.getByText("Executable in the published catalog")).toBeInTheDocument();
    expect(screen.getByText("Not executable in the published catalog")).toBeInTheDocument();
    expect(screen.getByText(/does not install assets/)).toBeInTheDocument();
    expect(getCalculationCatalog).toHaveBeenCalledTimes(1);
    expect(getStatisticsCapabilityCatalog).toHaveBeenCalledTimes(1);
});

it("filters presentation without resolving or executing Research", async () => {
    const resolveDefinition = vi.fn<ResearchApiClient["resolveDefinition"]>();
    const submitRun = vi.fn<ResearchApiClient["submitRun"]>();
    const getCalculationCatalog = vi.fn(() => Promise.resolve(calculations));
    const getStatisticsCapabilityCatalog = vi.fn(() => Promise.resolve(statistics));
    renderLibrary({
        resolveDefinition,
        submitRun,
        getCalculationCatalog,
        getStatisticsCapabilityCatalog
    });
    await screen.findByRole("heading", { name: "test.indicator.rsi" });
    const user = userEvent.setup();
    const filter = screen.getByRole("searchbox", { name: "Filter Research Library" });
    await user.type(filter, "1.2.3");
    expect(screen.getByRole("heading", { name: "test.indicator.rsi" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "test.target.forward" })).not.toBeInTheDocument();
    expect(screen.getByText("No Statistics capabilities match this filter.")).toBeInTheDocument();
    await user.clear(filter);
    await user.type(filter, "FACTOR_SCORE");
    expect(screen.getByRole("heading", { name: "IC" })).toBeInTheDocument();
    expect(screen.getByText("No calculations match this filter.")).toBeInTheDocument();
    await user.clear(filter);
    expect(screen.getByRole("heading", { name: "test.target.forward" })).toBeInTheDocument();
    expect(resolveDefinition).not.toHaveBeenCalled();
    expect(submitRun).not.toHaveBeenCalled();
    expect(getCalculationCatalog).toHaveBeenCalledTimes(1);
    expect(getStatisticsCapabilityCatalog).toHaveBeenCalledTimes(1);
});

it("does not populate empty catalogs with reference or production assets", async () => {
    renderLibrary({
        getCalculationCatalog: () => Promise.resolve({ schema_version: 2, calculations: [] }),
        getStatisticsCapabilityCatalog: () => Promise.resolve({ schema_version: 2, statistics: [] })
    });
    expect(
        await screen.findByText("No calculation capabilities are published.")
    ).toBeInTheDocument();
    expect(screen.getByText("No Statistics capabilities are published.")).toBeInTheDocument();
    expect(screen.queryByText("test.indicator.rsi")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("shows loading and a failed catalog honestly while allowing explicit retry", async () => {
    let resolveStatistics!: (value: ResearchStatisticsCapabilityCatalogTransport) => void;
    const pendingStatistics = new Promise<ResearchStatisticsCapabilityCatalogTransport>(
        (resolve) => {
            resolveStatistics = resolve;
        }
    );
    const getCalculationCatalog = vi
        .fn<ResearchApiClient["getCalculationCatalog"]>()
        .mockRejectedValueOnce(
            new ResearchWebError("TRANSPORT_ERROR", "Library API is unavailable")
        )
        .mockResolvedValue(calculations);
    renderLibrary({
        getCalculationCatalog,
        getStatisticsCapabilityCatalog: () => pendingStatistics
    });
    expect(screen.getByText("Loading authoritative Statistics catalog…")).toHaveAttribute(
        "role",
        "status"
    );
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Library API is unavailable");
    expect(screen.queryByRole("heading", { name: "test.indicator.rsi" })).not.toBeInTheDocument();
    await userEvent.click(within(error).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "test.indicator.rsi" })).toBeInTheDocument();
    resolveStatistics(statistics);
    expect(await screen.findByRole("heading", { name: "IC" })).toBeInTheDocument();
    expect(getCalculationCatalog).toHaveBeenCalledTimes(2);
});

it("keeps the library subordinate to the existing authoring workflow", async () => {
    renderLibrary();
    await userEvent.click(screen.getByRole("link", { name: "New Research →" }));
    expect(screen.getByRole("heading", { name: "Research Builder" })).toBeInTheDocument();
});
