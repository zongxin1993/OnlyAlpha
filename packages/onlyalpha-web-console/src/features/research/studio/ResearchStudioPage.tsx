import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ResearchWebError, errorMessage } from "../../../api/research/errors";
import type { ResearchCalculationCatalogItemTransport } from "../../../api/research/schemas";
import { useResearchApi } from "../../../app/providers";
import { CalculationEditor } from "./CalculationEditor";
import { ExpressionEditor } from "./ExpressionEditor";
import { ResearchInspector, type ResolutionState } from "./ResearchInspector";
import { ResearchDraftError, buildResearchDefinitionTransport } from "./definitionTransport";
import {
    calculationDraftFromCatalog,
    catalogKey,
    emptyComparison,
    initialResearchDraft,
    type CalculationDraft,
    type ExpressionDraft,
    type ResearchDraft
} from "./researchDraft";
import {
    calculationCatalogOptions,
    datasetFieldOptions,
    statisticsCapabilityOptions,
    universeCatalogOptions
} from "./queries";
import { ResearchRunSubmissionIntent, shouldAdmitResolution } from "./submissionIntent";

interface StudioState {
    readonly draft: ResearchDraft;
    readonly revision: number;
    readonly nextId: number;
}

export function ResearchStudioPage() {
    const client = useResearchApi();
    const navigate = useNavigate();
    const calculations = useQuery(calculationCatalogOptions(client));
    const universes = useQuery(universeCatalogOptions(client));
    const statisticsCapabilities = useQuery(statisticsCapabilityOptions(client));
    const datasetFields = useQuery(datasetFieldOptions(client));
    const [studio, setStudio] = useState<StudioState>({
        draft: initialResearchDraft(),
        revision: 0,
        nextId: 1
    });
    const [resolution, setResolution] = useState<ResolutionState>({ status: "UNRESOLVED" });
    const [submissionError, setSubmissionError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);
    const revisionRef = useRef(0);
    const resolveController = useRef<AbortController | null>(null);
    const submissionIntent = useRef(new ResearchRunSubmissionIntent());

    function changeDraft(update: (draft: ResearchDraft) => ResearchDraft) {
        resolveController.current?.abort();
        setStudio((current) => {
            const revision = current.revision + 1;
            revisionRef.current = revision;
            return { ...current, revision, draft: update(current.draft) };
        });
        setResolution({ status: "UNRESOLVED" });
        setSubmissionError(null);
    }

    if (
        calculations.isPending ||
        universes.isPending ||
        statisticsCapabilities.isPending ||
        datasetFields.isPending
    ) {
        return (
            <main className="page">
                <p role="status">Loading authoritative Research catalogs…</p>
            </main>
        );
    }
    const catalogError = [calculations, universes, statisticsCapabilities, datasetFields].find(
        (item) => item.isError
    );
    if (catalogError?.isError) {
        return (
            <main className="page">
                <div className="error" role="alert">
                    {errorMessage(catalogError.error)}
                </div>
            </main>
        );
    }
    if (
        calculations.data === undefined ||
        universes.data === undefined ||
        statisticsCapabilities.data === undefined ||
        datasetFields.data === undefined
    ) {
        return (
            <main className="page">
                <div className="error" role="alert">
                    CONTRACT_ERROR: catalog data is unavailable
                </div>
            </main>
        );
    }

    const catalogItems = calculations.data.calculations;
    const catalogMap = new Map(catalogItems.map((item) => [catalogKey(item), item]));
    const calculationChoices = catalogItems.filter((item) => item.type_reference.kind !== "TARGET");
    const targetChoices = catalogItems.filter((item) => item.type_reference.kind === "TARGET");
    const publishedSources = studio.draft.calculations.flatMap((item) =>
        item.publishedOutputs.map((output) => `${item.instanceKey}.${output}`)
    );
    const datasetSources = datasetFields.data.dataset_fields.map((item) => item.source);
    const expressionSources = [...datasetSources, ...publishedSources];
    const bindingSources = expressionSources;

    function addCalculation(item: ResearchCalculationCatalogItemTransport, target: boolean) {
        const base = item.type_reference.type_id.split(".").at(-1) ?? "calculation";
        const key = `${base}_${String(studio.nextId)}`;
        const next = calculationDraftFromCatalog(item, studio.nextId, key);
        setStudio((current) => ({ ...current, nextId: current.nextId + 1 }));
        changeDraft((draft) =>
            target
                ? { ...draft, targets: [...draft.targets, next] }
                : { ...draft, calculations: [...draft.calculations, next] }
        );
    }

    function updateCalculation(next: CalculationDraft, target: boolean) {
        changeDraft((draft) => ({
            ...draft,
            [target ? "targets" : "calculations"]: (target
                ? draft.targets
                : draft.calculations
            ).map((item) => (item.draftId === next.draftId ? next : item))
        }));
    }

    function removeCalculation(id: number, target: boolean) {
        changeDraft((draft) => ({
            ...draft,
            [target ? "targets" : "calculations"]: (target
                ? draft.targets
                : draft.calculations
            ).filter((item) => item.draftId !== id)
        }));
    }

    async function resolve() {
        let definition;
        try {
            definition = buildResearchDefinitionTransport(studio.draft, catalogItems);
        } catch (error) {
            setResolution({
                status: "INVALID",
                code: "RESEARCH_DRAFT_INCOMPLETE",
                detail: error instanceof Error ? error.message : "Draft is incomplete",
                ...(error instanceof ResearchDraftError ? { path: error.path } : {})
            });
            return;
        }
        const capturedRevision = studio.revision;
        const controller = new AbortController();
        resolveController.current?.abort();
        resolveController.current = controller;
        setResolution({ status: "RESOLVING", revision: capturedRevision });
        try {
            const value = await client.resolveDefinition(definition, controller.signal);
            if (
                !shouldAdmitResolution(
                    capturedRevision,
                    revisionRef.current,
                    controller.signal.aborted
                )
            )
                return;
            setResolution({ status: "RESOLVED", revision: capturedRevision, value });
        } catch (error) {
            if (
                !shouldAdmitResolution(
                    capturedRevision,
                    revisionRef.current,
                    controller.signal.aborted
                )
            )
                return;
            setResolution({
                status: "INVALID",
                code: error instanceof ResearchWebError ? error.code : "TRANSPORT_ERROR",
                detail: error instanceof Error ? error.message : "Resolution failed",
                ...(error instanceof ResearchWebError && error.path !== undefined
                    ? { path: error.path }
                    : {})
            });
        }
    }

    const canRun = resolution.status === "RESOLVED" && resolution.revision === studio.revision;
    async function run() {
        if (!canRun) return;
        const admittedResolution = resolution.value;
        const specificationFingerprint = admittedResolution.specification_fingerprint;
        setSubmitting(true);
        setSubmissionError(null);
        try {
            const key = submissionIntent.current.keyFor(specificationFingerprint);
            const submitted = await client.submitRun(admittedResolution.exact_specification, key);
            submissionIntent.current.confirm(specificationFingerprint);
            await navigate(`/research/runs/${submitted.run.runId}`);
        } catch (error) {
            setSubmissionError(errorMessage(error));
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <main className="studio-page">
            <header className="workspace-header">
                <div>
                    <p className="eyebrow">Structured Research Builder</p>
                    <h1>New Research</h1>
                    <p className="lede">
                        Author a Definition. The server alone resolves exact execution semantics.
                    </p>
                </div>
                <div className="workspace-actions">
                    <button
                        type="button"
                        className="button-secondary"
                        disabled={resolution.status === "RESOLVING"}
                        onClick={() => void resolve()}
                    >
                        {resolution.status === "RESOLVING" ? "Resolving…" : "Resolve"}
                    </button>
                    <button
                        type="button"
                        disabled={!canRun || submitting}
                        onClick={() => void run()}
                    >
                        {submitting ? "Submitting…" : "Run"}
                    </button>
                </div>
            </header>
            {submissionError === null ? null : (
                <div className="error" role="alert">
                    {submissionError}
                </div>
            )}
            <div className="studio-layout">
                <div className="builder-sections">
                    <section className="builder-section" id="universe-data">
                        <SectionTitle number="01" title="Universe & Data" />
                        <div className="form-grid">
                            <label>
                                Universe kind
                                <select
                                    value={studio.draft.dataset.universeKind}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: {
                                                ...draft.dataset,
                                                universeKind: event.target
                                                    .value as ResearchDraft["dataset"]["universeKind"]
                                            }
                                        }));
                                    }}
                                >
                                    {universes.data.selection_kinds.map((kind) => (
                                        <option key={kind}>{kind}</option>
                                    ))}
                                </select>
                            </label>
                            {studio.draft.dataset.universeKind.startsWith("REGISTERED") ? (
                                <label>
                                    Registered universe
                                    <select
                                        value={studio.draft.dataset.registeredId}
                                        onChange={(event) => {
                                            changeDraft((draft) => ({
                                                ...draft,
                                                dataset: {
                                                    ...draft.dataset,
                                                    registeredId: event.target.value
                                                }
                                            }));
                                        }}
                                    >
                                        <option value="">Select…</option>
                                        {universes.data.registered_universes
                                            .filter(
                                                (item) =>
                                                    item.kind === studio.draft.dataset.universeKind
                                            )
                                            .map((item) => (
                                                <option
                                                    key={item.registered_id}
                                                    value={item.registered_id}
                                                >
                                                    {typeof item.display_metadata.title === "string"
                                                        ? item.display_metadata.title
                                                        : item.registered_id}
                                                </option>
                                            ))}
                                    </select>
                                </label>
                            ) : (
                                <label>
                                    Instrument IDs
                                    <input
                                        aria-label="Instrument IDs"
                                        placeholder="A.XNAS, B.XNAS"
                                        value={studio.draft.dataset.instrumentsText}
                                        onChange={(event) => {
                                            changeDraft((draft) => ({
                                                ...draft,
                                                dataset: {
                                                    ...draft.dataset,
                                                    instrumentsText: event.target.value
                                                }
                                            }));
                                        }}
                                    />
                                </label>
                            )}
                            <label>
                                Start
                                <input
                                    type="text"
                                    placeholder="2026-01-01T00:00:00Z"
                                    value={studio.draft.dataset.start}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: { ...draft.dataset, start: event.target.value }
                                        }));
                                    }}
                                />
                            </label>
                            <label>
                                End
                                <input
                                    type="text"
                                    placeholder="2026-12-31T23:59:59Z"
                                    value={studio.draft.dataset.end}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: { ...draft.dataset, end: event.target.value }
                                        }));
                                    }}
                                />
                            </label>
                            <label>
                                Bar step
                                <input
                                    type="number"
                                    min="1"
                                    value={studio.draft.dataset.step}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: { ...draft.dataset, step: event.target.value }
                                        }));
                                    }}
                                />
                            </label>
                            <label>
                                Aggregation
                                <select
                                    value={studio.draft.dataset.aggregation}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: {
                                                ...draft.dataset,
                                                aggregation: event.target
                                                    .value as ResearchDraft["dataset"]["aggregation"]
                                            }
                                        }));
                                    }}
                                >
                                    {["TIME", "TICK", "VOLUME", "VALUE"].map((value) => (
                                        <option key={value}>{value}</option>
                                    ))}
                                </select>
                            </label>
                            <label>
                                Price type
                                <select
                                    value={studio.draft.dataset.priceType}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: {
                                                ...draft.dataset,
                                                priceType: event.target
                                                    .value as ResearchDraft["dataset"]["priceType"]
                                            }
                                        }));
                                    }}
                                >
                                    {["LAST", "BID", "ASK", "MID", "MARK"].map((value) => (
                                        <option key={value}>{value}</option>
                                    ))}
                                </select>
                            </label>
                            <label>
                                Aggregation source
                                <select
                                    value={studio.draft.dataset.aggregationSource}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: {
                                                ...draft.dataset,
                                                aggregationSource: event.target
                                                    .value as ResearchDraft["dataset"]["aggregationSource"]
                                            }
                                        }));
                                    }}
                                >
                                    <option>EXTERNAL</option>
                                    <option>INTERNAL</option>
                                </select>
                            </label>
                            <label>
                                Adjustment type
                                <select
                                    value={studio.draft.dataset.adjustmentType}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: {
                                                ...draft.dataset,
                                                adjustmentType: event.target
                                                    .value as ResearchDraft["dataset"]["adjustmentType"]
                                            }
                                        }));
                                    }}
                                >
                                    <option>RAW</option>
                                    <option>FORWARD</option>
                                    <option>BACKWARD</option>
                                </select>
                            </label>
                            <label>
                                Adjustment reference
                                <input
                                    type="text"
                                    placeholder="optional exact reference"
                                    value={studio.draft.dataset.adjustmentReference}
                                    onChange={(event) => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            dataset: {
                                                ...draft.dataset,
                                                adjustmentReference: event.target.value
                                            }
                                        }));
                                    }}
                                />
                            </label>
                        </div>
                    </section>
                    <CalculationSection
                        title="Calculations"
                        number="02"
                        items={studio.draft.calculations}
                        choices={calculationChoices}
                        catalogMap={catalogMap}
                        sources={bindingSources}
                        target={false}
                        add={addCalculation}
                        update={updateCalculation}
                        remove={removeCalculation}
                    />
                    <ExpressionSection
                        title="Eligibility"
                        number="03"
                        value={studio.draft.eligibility}
                        sources={expressionSources}
                        update={(value) => {
                            changeDraft((draft) => ({ ...draft, eligibility: value }));
                        }}
                    />
                    <section className="builder-section">
                        <SectionTitle number="04" title="Signals" />
                        <ExpressionBlock
                            title="Entry"
                            value={studio.draft.entry}
                            sources={expressionSources}
                            update={(value) => {
                                changeDraft((draft) => ({ ...draft, entry: value }));
                            }}
                        />
                        <ExpressionBlock
                            title="Exit"
                            value={studio.draft.exit}
                            sources={expressionSources}
                            update={(value) => {
                                changeDraft((draft) => ({ ...draft, exit: value }));
                            }}
                        />
                    </section>
                    <CalculationSection
                        title="Targets"
                        number="05"
                        items={studio.draft.targets}
                        choices={targetChoices}
                        catalogMap={catalogMap}
                        sources={bindingSources}
                        target
                        add={addCalculation}
                        update={updateCalculation}
                        remove={removeCalculation}
                    />
                    <section className="builder-section">
                        <SectionTitle number="06" title="Statistics" />
                        {studio.draft.statistics.map((item) => (
                            <div className="statistics-row" key={item.draftId}>
                                <label>
                                    Variable
                                    <select
                                        value={item.variable}
                                        onChange={(event) => {
                                            changeDraft((draft) => ({
                                                ...draft,
                                                statistics: draft.statistics.map((value) =>
                                                    value.draftId === item.draftId
                                                        ? { ...value, variable: event.target.value }
                                                        : value
                                                )
                                            }));
                                        }}
                                    >
                                        <option value="">Select…</option>
                                        {publishedSources.map((value) => (
                                            <option key={value}>{value}</option>
                                        ))}
                                    </select>
                                </label>
                                <label>
                                    Target
                                    <select
                                        value={item.targetInstanceKey}
                                        onChange={(event) => {
                                            changeDraft((draft) => ({
                                                ...draft,
                                                statistics: draft.statistics.map((value) =>
                                                    value.draftId === item.draftId
                                                        ? {
                                                              ...value,
                                                              targetInstanceKey: event.target.value
                                                          }
                                                        : value
                                                )
                                            }));
                                        }}
                                    >
                                        <option value="">Select…</option>
                                        {studio.draft.targets.map((value) => (
                                            <option key={value.draftId} value={value.instanceKey}>
                                                {value.instanceKey}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                                <label>
                                    Method
                                    <select
                                        value={item.method}
                                        onChange={(event) => {
                                            changeDraft((draft) => ({
                                                ...draft,
                                                statistics: draft.statistics.map((value) =>
                                                    value.draftId === item.draftId
                                                        ? { ...value, method: event.target.value }
                                                        : value
                                                )
                                            }));
                                        }}
                                    >
                                        {statisticsCapabilities.data.statistics
                                            .filter((value) => value.executable)
                                            .map((value) => (
                                                <option key={value.statistic_type}>
                                                    {value.statistic_type}
                                                </option>
                                            ))}
                                    </select>
                                </label>
                                <button
                                    type="button"
                                    className="button-subtle"
                                    onClick={() => {
                                        changeDraft((draft) => ({
                                            ...draft,
                                            statistics: draft.statistics.filter(
                                                (value) => value.draftId !== item.draftId
                                            )
                                        }));
                                    }}
                                >
                                    Remove
                                </button>
                            </div>
                        ))}
                        <button
                            type="button"
                            className="button-secondary"
                            onClick={() => {
                                const id = studio.nextId;
                                setStudio((current) => ({
                                    ...current,
                                    nextId: current.nextId + 1
                                }));
                                changeDraft((draft) => ({
                                    ...draft,
                                    statistics: [
                                        ...draft.statistics,
                                        {
                                            draftId: id,
                                            variable: publishedSources[0] ?? "",
                                            targetInstanceKey: draft.targets[0]?.instanceKey ?? "",
                                            method:
                                                statisticsCapabilities.data.statistics.find(
                                                    (item) => item.executable
                                                )?.statistic_type ?? "IC"
                                        }
                                    ]
                                }));
                            }}
                        >
                            Add Statistics
                        </button>
                    </section>
                </div>
                <ResearchInspector state={resolution} />
            </div>
        </main>
    );
}

function SectionTitle({ number, title }: { readonly number: string; readonly title: string }) {
    return (
        <div className="builder-title">
            <span>{number}</span>
            <h2>{title}</h2>
        </div>
    );
}

function CalculationSection({
    title,
    number,
    items,
    choices,
    catalogMap,
    sources,
    target,
    add,
    update,
    remove
}: {
    readonly title: string;
    readonly number: string;
    readonly items: readonly CalculationDraft[];
    readonly choices: readonly ResearchCalculationCatalogItemTransport[];
    readonly catalogMap: ReadonlyMap<string, ResearchCalculationCatalogItemTransport>;
    readonly sources: readonly string[];
    readonly target: boolean;
    readonly add: (item: ResearchCalculationCatalogItemTransport, target: boolean) => void;
    readonly update: (item: CalculationDraft, target: boolean) => void;
    readonly remove: (id: number, target: boolean) => void;
}) {
    const [selected, setSelected] = useState(
        choices[0] === undefined ? "" : catalogKey(choices[0])
    );
    return (
        <section className="builder-section">
            <SectionTitle number={number} title={title} />
            {items.map((item) => {
                const catalog = catalogMap.get(item.catalogKey);
                return catalog === undefined ? (
                    <div className="error" key={item.draftId}>
                        Catalog item unavailable
                    </div>
                ) : (
                    <CalculationEditor
                        key={item.draftId}
                        draft={item}
                        catalog={catalog}
                        sources={sources}
                        target={target}
                        onChange={(value) => {
                            update(value, target);
                        }}
                        onRemove={() => {
                            remove(item.draftId, target);
                        }}
                    />
                );
            })}
            <div className="add-row">
                <select
                    aria-label={`Add ${title}`}
                    value={selected}
                    onChange={(event) => {
                        setSelected(event.target.value);
                    }}
                >
                    {choices.map((item) => (
                        <option key={catalogKey(item)} value={catalogKey(item)}>
                            {item.type_reference.type_id}
                        </option>
                    ))}
                </select>
                <button
                    type="button"
                    className="button-secondary"
                    disabled={selected === ""}
                    onClick={() => {
                        const item = catalogMap.get(selected);
                        if (item !== undefined) add(item, target);
                    }}
                >
                    Add
                </button>
            </div>
        </section>
    );
}

function ExpressionBlock({
    title,
    value,
    sources,
    update
}: {
    readonly title: string;
    readonly value: ExpressionDraft | null;
    readonly sources: readonly string[];
    readonly update: (value: ExpressionDraft | null) => void;
}) {
    return (
        <div className="expression-block">
            <div className="section-heading">
                <h3>{title}</h3>
                {value === null ? (
                    <button
                        type="button"
                        className="button-secondary"
                        onClick={() => {
                            update(emptyComparison(sources[0]));
                        }}
                    >
                        Add expression
                    </button>
                ) : (
                    <button
                        type="button"
                        className="button-subtle"
                        onClick={() => {
                            update(null);
                        }}
                    >
                        Clear
                    </button>
                )}
            </div>
            {value === null ? (
                <p className="muted">Optional</p>
            ) : (
                <ExpressionEditor value={value} sources={sources} onChange={update} />
            )}
        </div>
    );
}
function ExpressionSection({
    title,
    number,
    value,
    sources,
    update
}: {
    readonly title: string;
    readonly number: string;
    readonly value: ExpressionDraft | null;
    readonly sources: readonly string[];
    readonly update: (value: ExpressionDraft | null) => void;
}) {
    return (
        <section className="builder-section">
            <SectionTitle number={number} title={title} />
            <ExpressionBlock title="Condition" value={value} sources={sources} update={update} />
        </section>
    );
}
