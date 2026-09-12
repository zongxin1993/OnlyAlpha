import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useResearchApi } from "../../../app/providers";
import { parseResearchResultFingerprint } from "../../../domain/research/identity";
import { ExactResourceForm } from "../../../shared/components/ExactResourceForm";
import { QueryError } from "../../../shared/components/QueryState";
import { WorkspaceIcon } from "../../../shared/components/WorkspaceIcon";
import { admitResourceIdentity } from "../../../shared/resourceIdentity";
import { runsOptions } from "../runs/queries";
import { calculationCatalogOptions } from "../studio/queries";
import { catalogKey } from "../studio/researchDraft";
import { FactorResultView } from "./FactorResultView";
import { factorCatalogItems } from "./factorModel";
import "./factors.css";

export function FactorExplorerPage() {
    const client = useResearchApi();
    const catalog = useQuery(calculationCatalogOptions(client));
    const runs = useInfiniteQuery(runsOptions(client));
    const [params, setParams] = useSearchParams();
    const [search, setSearch] = useState("");
    const selectedFactor = params.get("factor") ?? "";
    const rawResult = params.get("result");
    const result = admitResourceIdentity(rawResult ?? undefined, parseResearchResultFingerprint);
    const factors = factorCatalogItems(catalog.data?.calculations ?? [], search);
    const completed =
        runs.data?.pages
            .flatMap((page) => page.runs)
            .filter((run) => run.state === "COMPLETED" && run.resultRef !== null) ?? [];
    const newResearch = new URLSearchParams();
    if (selectedFactor !== "") newResearch.set("factor", selectedFactor);
    function openResult(value: string) {
        const fingerprint = parseResearchResultFingerprint(value);
        setParams((previous) => {
            const next = new URLSearchParams();
            next.set("result", fingerprint);
            const factor = previous.get("factor");
            if (factor !== null) next.set("factor", factor);
            return next;
        });
    }
    return (
        <main className="factor-explorer">
            <header className="factor-page-header">
                <div>
                    <p className="eyebrow">Research · Factor evidence</p>
                    <h1>Factor Explorer</h1>
                    <p>
                        Find a registered Factor. Compare exact stock evidence and inspect published
                        IC / Rank IC.
                    </p>
                </div>
                <Link className="primary-link" to={`/research/new?${newResearch.toString()}`}>
                    Configure Research <WorkspaceIcon name="arrow" />
                </Link>
            </header>
            <div className="factor-workspace-layout">
                <aside className="factor-catalog" aria-label="Registered Factor catalog">
                    <header>
                        <WorkspaceIcon name="library" />
                        <h2>Factor Library</h2>
                    </header>
                    <label htmlFor="factor-search">Search registered Factors</label>
                    <input
                        type="search"
                        id="factor-search"
                        placeholder="Type, version or output…"
                        value={search}
                        onChange={(event) => {
                            setSearch(event.target.value);
                        }}
                    />
                    <p className="factor-caption">Current API catalog · L3 Factors only</p>
                    {catalog.isError ? (
                        <QueryError error={catalog.error} retry={() => void catalog.refetch()} />
                    ) : catalog.isPending ? (
                        <p role="status">Loading registered Factors…</p>
                    ) : factors.length === 0 ? (
                        <p className="factor-empty-message">
                            No registered Factors match this search. Indicators are not reclassified
                            as Factors.
                        </p>
                    ) : (
                        <div className="factor-catalog-items">
                            {factors.map((factor) => (
                                <button
                                    type="button"
                                    key={catalogKey(factor)}
                                    aria-pressed={selectedFactor === catalogKey(factor)}
                                    onClick={() => {
                                        setParams((previous) => {
                                            const next = new URLSearchParams(previous);
                                            next.set("factor", catalogKey(factor));
                                            next.delete("series");
                                            next.delete("statistic");
                                            return next;
                                        });
                                    }}
                                >
                                    <span className="analysis-badge">
                                        FACTOR · {factor.type_reference.semantic_version}
                                    </span>
                                    <strong>{factor.type_reference.type_id}</strong>
                                    <span>
                                        {factor.outputs.map((output) => output.name).join(" · ")}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}
                    {selectedFactor === "" ? null : (
                        <button
                            type="button"
                            className="quiet-button"
                            onClick={() => {
                                setParams((previous) => {
                                    const next = new URLSearchParams(previous);
                                    next.delete("factor");
                                    next.delete("series");
                                    next.delete("statistic");
                                    return next;
                                });
                            }}
                        >
                            Clear catalog selection
                        </button>
                    )}
                    <p className="factor-caption">
                        Historical Graph evidence keeps its own exact type/version, even when the
                        current catalog changes.
                    </p>
                </aside>
                <section
                    className="factor-evidence-workspace"
                    aria-label="Factor evidence workspace"
                >
                    <div className="factor-evidence-toolbar">
                        <label>
                            Completed Research Run
                            <select
                                aria-label="Completed Factor Research Run"
                                value={
                                    completed.find((run) => run.resultRef === rawResult)?.runId ??
                                    ""
                                }
                                onChange={(event) => {
                                    const reference = completed.find(
                                        (run) => run.runId === event.target.value
                                    )?.resultRef;
                                    if (reference !== null && reference !== undefined)
                                        openResult(reference);
                                }}
                            >
                                <option value="">Select an exact completed Run</option>
                                {completed.map((run) => (
                                    <option value={run.runId} key={run.runId}>
                                        {run.runId} · {run.finishedAt ?? "COMPLETED"}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <Link className="secondary-link" to="/research/runs">
                            <WorkspaceIcon name="clock" />
                            Run history
                        </Link>
                    </div>
                    {runs.isError ? (
                        <QueryError
                            title="Run references are unavailable; an exact Result may still be opened."
                            error={runs.error}
                            retry={() => void runs.refetch()}
                        />
                    ) : null}
                    <details className="factor-result-input">
                        <summary>Open an exact Research Result fingerprint</summary>
                        <ExactResourceForm
                            key={rawResult ?? "empty"}
                            id="factor-result"
                            label="Research Result fingerprint"
                            action="Open Factor evidence"
                            initialValue={rawResult ?? ""}
                            placeholder="64 lower-case hexadecimal characters"
                            onOpen={openResult}
                        />
                    </details>
                    {result.error === null ? null : (
                        <p className="error" role="alert">
                            INVALID_QUERY: {result.error}
                        </p>
                    )}
                    {result.value === null ? (
                        <div className="factor-start">
                            <WorkspaceIcon name="results" />
                            <h2>From Factor hypothesis to evidence</h2>
                            <p>
                                Select a Factor, then open an existing Result or configure a new
                                Research with your stock or basket.
                            </p>
                            <div className="factor-start-options">
                                <span>01 · Exact Factor version</span>
                                <span>02 · Stocks and UTC interval</span>
                                <span>03 · Price + Factor panes</span>
                                <span>04 · Published IC / Rank IC</span>
                            </div>
                            <p className="product-boundary-note">
                                Single-stock charts show co-movement, not a temporal correlation
                                coefficient. IC / Rank IC are cross-sectional statistics over the
                                original Research population.
                            </p>
                        </div>
                    ) : (
                        <FactorResultView key={result.value} result={result.value} />
                    )}
                </section>
            </div>
        </main>
    );
}
