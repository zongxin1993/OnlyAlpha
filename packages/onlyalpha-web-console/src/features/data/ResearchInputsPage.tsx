import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useResearchApi } from "../../app/providers";
import { QueryError } from "../../shared/components/QueryState";
import { datasetFieldOptions, universeCatalogOptions } from "../research/studio/queries";

const textMetadata = (metadata: Readonly<Record<string, unknown>>) =>
    Object.entries(metadata).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string"
    );

export function ResearchInputsPage() {
    const client = useResearchApi();
    const universes = useQuery(universeCatalogOptions(client));
    const fields = useQuery(datasetFieldOptions(client));
    const [filter, setFilter] = useState("");
    const search = filter.trim().toLowerCase();
    const visibleUniverses = (universes.data?.registered_universes ?? []).filter((universe) =>
        [universe.registered_id, universe.kind, ...textMetadata(universe.display_metadata).flat()]
            .join(" ")
            .toLowerCase()
            .includes(search)
    );
    const visibleFields = (fields.data?.dataset_fields ?? []).filter((field) =>
        [
            field.source,
            field.field_name,
            field.data_type,
            ...field.semantic_roles,
            ...field.dimensions,
            field.unit ?? ""
        ]
            .join(" ")
            .toLowerCase()
            .includes(search)
    );

    return (
        <main className="page catalog-page">
            <header className="catalog-header">
                <div>
                    <p className="eyebrow">Data · server-published capabilities</p>
                    <h1>Research Inputs</h1>
                    <p className="lede">
                        Explore Universe definitions and dataset-field capabilities before authoring
                        Research. These catalogs do not prove stored data availability, market
                        prices, or data freshness.
                    </p>
                </div>
                <Link to="/research/new">New Research →</Link>
            </header>
            <div className="catalog-toolbar">
                <label className="catalog-label" htmlFor="research-input-filter">
                    Filter research inputs
                </label>
                <input
                    id="research-input-filter"
                    type="search"
                    value={filter}
                    onChange={(event) => {
                        setFilter(event.target.value);
                    }}
                    placeholder="Universe, field, semantic role…"
                />
            </div>
            <div className="catalog-grid">
                <section className="catalog-panel" aria-labelledby="input-universes-heading">
                    <h2 id="input-universes-heading">Universe definitions</h2>
                    {universes.isPending ? (
                        <p role="status">Loading authoritative Universe catalog…</p>
                    ) : universes.isError ? (
                        <QueryError
                            error={universes.error}
                            retry={() => void universes.refetch()}
                        />
                    ) : (
                        <>
                            <h3>Supported selection kinds</h3>
                            {universes.data.selection_kinds.length === 0 ? (
                                <p>No Universe selection kinds are published.</p>
                            ) : (
                                <ul className="catalog-meta">
                                    {universes.data.selection_kinds.map((kind) => (
                                        <li key={kind}>{kind}</li>
                                    ))}
                                </ul>
                            )}
                            <h3>Registered universes</h3>
                            <p className="catalog-meta">
                                {visibleUniverses.length} of{" "}
                                {universes.data.registered_universes.length} registered definitions
                                shown
                            </p>
                            {visibleUniverses.length === 0 ? (
                                <p>
                                    {universes.data.registered_universes.length === 0
                                        ? "No registered universes are published."
                                        : "No registered universes match this filter."}
                                </p>
                            ) : (
                                visibleUniverses.map((universe) => (
                                    <article className="catalog-card" key={universe.registered_id}>
                                        <h4>{universe.registered_id}</h4>
                                        <p className="catalog-meta">{universe.kind}</p>
                                        <dl className="catalog-meta">
                                            {textMetadata(universe.display_metadata).map(
                                                ([name, value]) => (
                                                    <div key={name}>
                                                        <dt>{name}</dt>
                                                        <dd>{value}</dd>
                                                    </div>
                                                )
                                            )}
                                        </dl>
                                    </article>
                                ))
                            )}
                        </>
                    )}
                </section>
                <section className="catalog-panel" aria-labelledby="input-fields-heading">
                    <h2 id="input-fields-heading">Dataset-field capabilities</h2>
                    {fields.isPending ? (
                        <p role="status">Loading authoritative dataset-field catalog…</p>
                    ) : fields.isError ? (
                        <QueryError error={fields.error} retry={() => void fields.refetch()} />
                    ) : (
                        <>
                            <p className="catalog-meta">
                                {visibleFields.length} of {fields.data.dataset_fields.length} field
                                definitions shown
                            </p>
                            {visibleFields.length === 0 ? (
                                <p>
                                    {fields.data.dataset_fields.length === 0
                                        ? "No dataset-field capabilities are published."
                                        : "No dataset fields match this filter."}
                                </p>
                            ) : (
                                <div className="table-scroll">
                                    <table className="catalog-table">
                                        <thead>
                                            <tr>
                                                <th scope="col">Source / field</th>
                                                <th scope="col">Type / unit</th>
                                                <th scope="col">Semantic roles</th>
                                                <th scope="col">Dimensions</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {visibleFields.map((field) => (
                                                <tr key={field.source}>
                                                    <td>
                                                        <code>{field.source}</code>
                                                        <span className="catalog-meta">
                                                            {field.field_name}
                                                        </span>
                                                    </td>
                                                    <td>
                                                        {field.data_type}
                                                        <span className="catalog-meta">
                                                            {field.unit ?? "No unit declared"}
                                                        </span>
                                                    </td>
                                                    <td>
                                                        {field.semantic_roles.join(" · ") || "—"}
                                                    </td>
                                                    <td>{field.dimensions.join(" · ") || "—"}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </>
                    )}
                </section>
            </div>
        </main>
    );
}
