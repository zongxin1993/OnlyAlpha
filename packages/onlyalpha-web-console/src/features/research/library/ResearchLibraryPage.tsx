import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { ResearchCalculationCatalogTransport } from "../../../api/research/schemas";
import { useResearchApi } from "../../../app/providers";
import { QueryError } from "../../../shared/components/QueryState";
import { calculationCatalogOptions, statisticsCapabilityOptions } from "../studio/queries";

type CatalogItem = ResearchCalculationCatalogTransport["calculations"][number];
type CatalogScalar = CatalogItem["parameters"][number]["default"];

const scalarText = (scalar: CatalogScalar | null): string => {
    if (scalar === null) return "Not declared";
    return `${scalar.type} · ${scalar.value === null ? "NULL" : String(scalar.value)}`;
};

export function ResearchLibraryPage() {
    const client = useResearchApi();
    const calculations = useQuery(calculationCatalogOptions(client));
    const statistics = useQuery(statisticsCapabilityOptions(client));
    const [filter, setFilter] = useState("");
    const search = filter.trim().toLowerCase();
    const visibleCalculations = (calculations.data?.calculations ?? []).filter((item) =>
        [
            item.kind,
            item.type_reference.type_id,
            item.type_reference.semantic_version,
            ...item.parameters.map((parameter) => parameter.name),
            ...[...item.inputs, ...item.outputs].flatMap((port) => [port.name, port.semantic_type])
        ]
            .join(" ")
            .toLowerCase()
            .includes(search)
    );
    const visibleStatistics = (statistics.data?.statistics ?? []).filter((item) =>
        [
            item.statistic_type,
            ...item.variable_kinds,
            ...item.variable_semantic_roles,
            ...item.target_semantic_roles
        ]
            .join(" ")
            .toLowerCase()
            .includes(search)
    );

    return (
        <main className="page catalog-page">
            <header className="catalog-header">
                <div>
                    <p className="eyebrow">Research · authoring reference</p>
                    <h1>Research Library</h1>
                    <p className="lede">
                        Inspect server-published calculation and Statistics capabilities. This
                        read-only reference does not install assets, execute calculations, or
                        authorize a Strategy Revision.
                    </p>
                </div>
                <Link to="/research/new">New Research →</Link>
            </header>
            <div className="catalog-toolbar">
                <label className="catalog-label" htmlFor="research-library-filter">
                    Filter Research Library
                </label>
                <input
                    id="research-library-filter"
                    type="search"
                    value={filter}
                    onChange={(event) => {
                        setFilter(event.target.value);
                    }}
                    placeholder="Type, version, output, statistic…"
                />
            </div>
            <div className="catalog-grid">
                <section className="catalog-panel" aria-labelledby="library-calculations-heading">
                    <h2 id="library-calculations-heading">Calculation capabilities</h2>
                    {calculations.isPending ? (
                        <p role="status">Loading authoritative calculation catalog…</p>
                    ) : calculations.isError ? (
                        <QueryError
                            error={calculations.error}
                            retry={() => void calculations.refetch()}
                        />
                    ) : (
                        <>
                            <p className="catalog-meta">
                                {visibleCalculations.length} of{" "}
                                {calculations.data.calculations.length} calculation definitions
                                shown
                            </p>
                            {visibleCalculations.length === 0 ? (
                                <p>
                                    {calculations.data.calculations.length === 0
                                        ? "No calculation capabilities are published."
                                        : "No calculations match this filter."}
                                </p>
                            ) : (
                                visibleCalculations.map((item) => (
                                    <CalculationCard
                                        key={`${item.kind}:${item.type_reference.type_id}:${item.type_reference.semantic_version}`}
                                        item={item}
                                    />
                                ))
                            )}
                        </>
                    )}
                </section>
                <section className="catalog-panel" aria-labelledby="library-statistics-heading">
                    <h2 id="library-statistics-heading">Statistics capabilities</h2>
                    {statistics.isPending ? (
                        <p role="status">Loading authoritative Statistics catalog…</p>
                    ) : statistics.isError ? (
                        <QueryError
                            error={statistics.error}
                            retry={() => void statistics.refetch()}
                        />
                    ) : (
                        <>
                            <p className="catalog-meta">
                                {visibleStatistics.length} of {statistics.data.statistics.length}{" "}
                                Statistics definitions shown
                            </p>
                            {visibleStatistics.length === 0 ? (
                                <p>
                                    {statistics.data.statistics.length === 0
                                        ? "No Statistics capabilities are published."
                                        : "No Statistics capabilities match this filter."}
                                </p>
                            ) : (
                                visibleStatistics.map((item) => (
                                    <article className="catalog-card" key={item.statistic_type}>
                                        <h3>{item.statistic_type}</h3>
                                        <p className="catalog-meta">
                                            {item.executable
                                                ? "Executable in the published catalog"
                                                : "Not executable in the published catalog"}
                                        </p>
                                        <dl className="catalog-meta">
                                            <div>
                                                <dt>Variable kinds</dt>
                                                <dd>{item.variable_kinds.join(" · ") || "—"}</dd>
                                            </div>
                                            <div>
                                                <dt>Variable roles</dt>
                                                <dd>
                                                    {item.variable_semantic_roles.join(" · ") ||
                                                        "—"}
                                                </dd>
                                            </div>
                                            <div>
                                                <dt>Target roles</dt>
                                                <dd>
                                                    {item.target_semantic_roles.join(" · ") || "—"}
                                                </dd>
                                            </div>
                                            <div>
                                                <dt>Target required</dt>
                                                <dd>{item.target_required ? "Yes" : "No"}</dd>
                                            </div>
                                        </dl>
                                    </article>
                                ))
                            )}
                        </>
                    )}
                </section>
            </div>
        </main>
    );
}

function CalculationCard({ item }: { readonly item: CatalogItem }) {
    return (
        <article className="catalog-card">
            <p className="catalog-label">{item.kind}</p>
            <h3>{item.type_reference.type_id}</h3>
            <p className="catalog-meta">
                Semantic version {item.type_reference.semantic_version} · Parameter sweep{" "}
                {item.parameter_sweep_allowed ? "allowed" : "not allowed"}
            </p>
            <details>
                <summary>Inspect parameters and ports</summary>
                <h4>Parameters</h4>
                {item.parameters.length === 0 ? (
                    <p>No parameters declared.</p>
                ) : (
                    <div className="table-scroll">
                        <table className="catalog-table">
                            <thead>
                                <tr>
                                    <th scope="col">Parameter</th>
                                    <th scope="col">Default / constraints</th>
                                </tr>
                            </thead>
                            <tbody>
                                {item.parameters.map((parameter) => (
                                    <tr key={parameter.name}>
                                        <td>
                                            <code>{parameter.name}</code>
                                            <span className="catalog-meta">
                                                {parameter.type} ·{" "}
                                                {parameter.required ? "Required" : "Optional"}
                                            </span>
                                        </td>
                                        <td>
                                            <dl className="catalog-meta">
                                                <div>
                                                    <dt>Default</dt>
                                                    <dd>{scalarText(parameter.default)}</dd>
                                                </div>
                                                <div>
                                                    <dt>Minimum</dt>
                                                    <dd>{scalarText(parameter.minimum)}</dd>
                                                </div>
                                                <div>
                                                    <dt>Maximum</dt>
                                                    <dd>{scalarText(parameter.maximum)}</dd>
                                                </div>
                                                <div>
                                                    <dt>Enum values</dt>
                                                    <dd>
                                                        {parameter.enum_values
                                                            .map(scalarText)
                                                            .join("; ") || "Not declared"}
                                                    </dd>
                                                </div>
                                                <div>
                                                    <dt>Uppercase</dt>
                                                    <dd>{parameter.uppercase ? "Yes" : "No"}</dd>
                                                </div>
                                            </dl>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
                <PortTable heading="Inputs" ports={item.inputs} />
                <PortTable heading="Outputs" ports={item.outputs} />
            </details>
        </article>
    );
}

function PortTable({
    heading,
    ports
}: {
    readonly heading: string;
    readonly ports: CatalogItem["inputs"];
}) {
    return (
        <>
            <h4>{heading}</h4>
            {ports.length === 0 ? (
                <p>No {heading.toLowerCase()} declared.</p>
            ) : (
                <div className="table-scroll">
                    <table className="catalog-table">
                        <thead>
                            <tr>
                                <th scope="col">Port</th>
                                <th scope="col">Type / unit</th>
                                <th scope="col">Semantics / dimensions</th>
                                <th scope="col">Nullable</th>
                            </tr>
                        </thead>
                        <tbody>
                            {ports.map((port) => (
                                <tr key={port.name}>
                                    <td>{port.name}</td>
                                    <td>
                                        {port.data_type}
                                        <span className="catalog-meta">
                                            {port.unit ?? "No unit declared"}
                                        </span>
                                    </td>
                                    <td>
                                        {port.semantic_type}
                                        <span className="catalog-meta">
                                            {port.dimensions.join(" · ") ||
                                                "No dimensions declared"}
                                        </span>
                                    </td>
                                    <td>{port.nullable ? "Yes" : "No"}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </>
    );
}
