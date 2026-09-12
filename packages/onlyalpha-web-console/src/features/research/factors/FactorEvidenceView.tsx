import { useState, type SyntheticEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { ResearchResultFingerprint } from "../../../domain/research/identity";
import type {
    ResearchArtifactSummary,
    ResearchCandidate,
    ResearchStatisticsCatalog
} from "../../../domain/research/model";
import { StatisticsEvidence } from "../results/components/StatisticsWorkspace";
import { FactorInstrumentCard } from "./FactorInstrumentCard";
import { parseFactorDateRange, statisticsForFactor, type FactorSeriesOption } from "./factorModel";

export function FactorEvidenceView({
    result,
    summary,
    candidate,
    options,
    statistics
}: {
    readonly result: ResearchResultFingerprint;
    readonly summary: ResearchArtifactSummary;
    readonly candidate: ResearchCandidate;
    readonly options: readonly FactorSeriesOption[];
    readonly statistics: ResearchStatisticsCatalog;
}) {
    const [params, setParams] = useSearchParams();
    const catalogSelection = params.get("factor");
    const choices =
        catalogSelection === null
            ? options
            : options.filter(
                  (option) =>
                      `FACTOR:${option.node.definition.typeId}@${option.node.definition.semanticVersion}` ===
                      catalogSelection
              );
    const selectedKey = params.get("series");
    const option =
        selectedKey === null
            ? choices.length === 1
                ? choices[0]
                : undefined
            : choices.find((item) => item.key === selectedKey);
    const fromDate = params.get("from") ?? "";
    const toDate = params.get("to") ?? "";
    const requested = params.getAll("instrument");
    const instruments = params.has("instrument")
        ? requested.length === 1 && requested[0] === ""
            ? []
            : requested
        : summary.instrumentIds.slice(0, 1);
    let range: ReturnType<typeof parseFactorDateRange> = {};
    let selectionError: string | null = null;
    try {
        range = parseFactorDateRange(fromDate, toDate);
        if (
            new Set(instruments).size !== instruments.length ||
            instruments.some((id) => !summary.instrumentIds.includes(id))
        )
            throw new Error(
                "INVALID_QUERY: stock display selection is not an exact subset of the Artifact instruments."
            );
        if (selectedKey !== null && option === undefined)
            throw new Error(
                "INVALID_QUERY: Factor series is not a member of the selected exact Factor context."
            );
    } catch (error) {
        selectionError =
            error instanceof Error ? error.message : "INVALID_QUERY: invalid evidence selection";
    }
    function toggleInstrument(id: string, checked: boolean) {
        setParams(
            (previous) => {
                const next = new URLSearchParams(previous);
                next.delete("instrument");
                const selected = checked
                    ? [...instruments, id]
                    : instruments.filter((item) => item !== id);
                for (const value of selected) next.append("instrument", value);
                if (selected.length === 0) next.set("instrument", "");
                return next;
            },
            { flushSync: true }
        );
    }
    const seed = new URLSearchParams();
    if (option !== undefined)
        seed.set(
            "factor",
            `FACTOR:${option.node.definition.typeId}@${option.node.definition.semanticVersion}`
        );
    for (const id of instruments) seed.append("instrument", id);
    if (fromDate !== "") seed.set("from", fromDate);
    if (toDate !== "") seed.set("to", toDate);
    return (
        <div className="factor-evidence-view">
            <label className="factor-output-selector">
                Exact Factor output
                <select
                    aria-label="Exact Factor output"
                    value={option?.key ?? ""}
                    onChange={(event) => {
                        setParams((previous) => {
                            const next = new URLSearchParams(previous);
                            if (event.target.value === "") next.delete("series");
                            else next.set("series", event.target.value);
                            next.delete("statistic");
                            return next;
                        });
                    }}
                >
                    <option value="">Select an exact Factor output</option>
                    {choices.map((item) => (
                        <option key={item.key} value={item.key}>
                            {item.label}
                        </option>
                    ))}
                </select>
            </label>
            {choices.length === 0 ? (
                <p className="warning">
                    {catalogSelection === null
                        ? "This Candidate has no published numeric Factor outputs. Indicator outputs are not reclassified as Factors."
                        : "No exact Factor type/version matching the catalog selection in this Candidate."}
                </p>
            ) : null}
            <fieldset className="factor-stock-picker">
                <legend>Stock display selection</legend>
                <div>
                    {summary.instrumentIds.map((id) => (
                        <label key={id}>
                            <input
                                type="checkbox"
                                checked={instruments.includes(id)}
                                onChange={(event) => {
                                    toggleInstrument(id, event.target.checked);
                                }}
                            />
                            {id}
                        </label>
                    ))}
                </div>
                <p>
                    Display only: selecting stocks does not change the original Research statistics
                    population.
                </p>
            </fieldset>
            <FactorDateControls
                key={`${fromDate}:${toDate}`}
                from={fromDate}
                to={toDate}
                onApply={(from, to) => {
                    setParams((previous) => {
                        const next = new URLSearchParams(previous);
                        if (from === "") next.delete("from");
                        else next.set("from", from);
                        if (to === "") next.delete("to");
                        else next.set("to", to);
                        return next;
                    });
                }}
            />
            {selectionError !== null ? (
                <p className="error" role="alert">
                    {selectionError}
                </p>
            ) : option === undefined ? (
                <p className="factor-empty-message">
                    Choose an exact Factor output before loading stock evidence.
                </p>
            ) : (
                <>
                    <section className="factor-subject" aria-label="Selected Factor identity">
                        <div>
                            <span className="analysis-badge">
                                FACTOR · {option.node.definition.semanticVersion}
                            </span>
                            <h3>{option.node.definition.typeId}</h3>
                            <p>
                                {option.series.outputName} · {option.series.valueKind} · independent
                                price and Factor scales
                            </p>
                        </div>
                        <Link className="primary-link" to={`/research/new?${seed.toString()}`}>
                            Research this selection →
                        </Link>
                        <p className="factor-seed-note">
                            New draft only: type/version, stocks and dates are carried over.
                            Parameters and published outputs use catalog defaults and must be
                            confirmed again; historical execution settings are not cloned.
                        </p>
                        <details>
                            <summary>Exact Factor parameters and references</summary>
                            <dl>
                                <dt>Candidate</dt>
                                <dd>{candidate.candidateFingerprint}</dd>
                                <dt>Calculation</dt>
                                <dd>{option.series.calculationFingerprint}</dd>
                                <dt>Node</dt>
                                <dd>{option.series.nodeFingerprint}</dd>
                                <dt>Parameters</dt>
                                <dd>
                                    <pre>
                                        {JSON.stringify(option.node.definition.parameters, null, 2)}
                                    </pre>
                                </dd>
                            </dl>
                        </details>
                    </section>
                    {instruments.length === 0 ? (
                        <p>
                            Select one or more Artifact instruments to view their price and Factor
                            evidence.
                        </p>
                    ) : (
                        <div className="factor-plots">
                            {instruments.map((id) => (
                                <FactorInstrumentCard
                                    key={`${option.key}:${id}:${fromDate}:${toDate}`}
                                    result={result}
                                    option={option}
                                    instrumentId={id}
                                    range={range}
                                />
                            ))}
                        </div>
                    )}
                    <FactorCorrelationPanel
                        result={result}
                        candidate={candidate}
                        option={option}
                        statistics={statistics}
                        range={range}
                    />
                </>
            )}
        </div>
    );
}

function FactorDateControls({
    from,
    to,
    onApply
}: {
    readonly from: string;
    readonly to: string;
    readonly onApply: (from: string, to: string) => void;
}) {
    const [start, setStart] = useState(from);
    const [end, setEnd] = useState(to);
    const [error, setError] = useState<string | null>(null);
    function submit(event: SyntheticEvent<HTMLFormElement>) {
        event.preventDefault();
        try {
            parseFactorDateRange(start, end);
            setError(null);
            onApply(start, end);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : "Invalid time range");
        }
    }
    return (
        <form className="factor-date-controls" onSubmit={submit} noValidate>
            <label>
                From UTC (inclusive)
                <input
                    type="date"
                    value={start}
                    onChange={(event) => {
                        setStart(event.target.value);
                    }}
                />
            </label>
            <label>
                To UTC (exclusive)
                <input
                    type="date"
                    value={end}
                    onChange={(event) => {
                        setEnd(event.target.value);
                    }}
                />
            </label>
            <button type="submit">Apply time window</button>
            <button
                type="button"
                className="quiet-button"
                onClick={() => {
                    setStart("");
                    setEnd("");
                    setError(null);
                    onApply("", "");
                }}
            >
                Full evidence interval
            </button>
            <p>
                Dates filter existing evidence using [from, to). They do not recalculate the Factor,
                Target or statistics.
            </p>
            {error === null ? null : (
                <p className="error" role="alert">
                    {error}
                </p>
            )}
        </form>
    );
}

function FactorCorrelationPanel({
    result,
    candidate,
    option,
    statistics,
    range
}: {
    readonly result: ResearchResultFingerprint;
    readonly candidate: ResearchCandidate;
    readonly option: FactorSeriesOption;
    readonly statistics: ResearchStatisticsCatalog;
    readonly range: ReturnType<typeof parseFactorDateRange>;
}) {
    const [params, setParams] = useSearchParams();
    let descriptors: ReturnType<typeof statisticsForFactor>;
    try {
        descriptors = statisticsForFactor(result, candidate, option, statistics);
        if (
            new Set(descriptors.map((item) => item.statisticsFingerprint)).size !==
            descriptors.length
        )
            throw new Error("CONTRACT_ERROR: duplicate Statistics identities");
    } catch (error) {
        return (
            <p className="error" role="alert">
                {error instanceof Error ? error.message : "CONTRACT_ERROR: mismatched Statistics"}
            </p>
        );
    }
    const raw = params.get("statistic");
    const descriptor =
        raw === null
            ? descriptors.length === 1
                ? descriptors[0]
                : undefined
            : descriptors.find((item) => item.statisticsFingerprint === raw);
    return (
        <section className="factor-correlation" aria-labelledby="factor-correlation-heading">
            <header>
                <div>
                    <p className="eyebrow">Published Research Statistics</p>
                    <h2 id="factor-correlation-heading">Factor / Target correlation</h2>
                </div>
                <span className="analysis-badge">NO BROWSER CALCULATION</span>
            </header>
            <p className="product-boundary-note">
                Statistics population: original Research universe. Stock checkboxes affect charts
                only; each row’s sample count is the authoritative observed pair count, not the
                number of checked stocks.
            </p>
            <label>
                Correlation statistic
                <select
                    aria-label="Correlation statistic"
                    value={descriptor?.statisticsFingerprint ?? ""}
                    onChange={(event) => {
                        setParams((previous) => {
                            const next = new URLSearchParams(previous);
                            if (event.target.value === "") next.delete("statistic");
                            else next.set("statistic", event.target.value);
                            return next;
                        });
                    }}
                >
                    <option value="">Select published IC / Rank IC</option>
                    {descriptors.map((item) => (
                        <option value={item.statisticsFingerprint} key={item.statisticsFingerprint}>
                            {item.definition.method} · {item.feature.outputName} →{" "}
                            {item.target.outputName} · {item.statisticsFingerprint}
                        </option>
                    ))}
                </select>
            </label>
            {raw !== null && descriptor === undefined ? (
                <p className="error" role="alert">
                    INVALID_QUERY: Statistics is not a member of the selected Factor and Candidate.
                </p>
            ) : descriptor === undefined ? (
                <p>
                    {descriptors.length === 0
                        ? "No Factor / Target correlation is exposed for this exact Factor by the current public read contract."
                        : "Choose an exact published statistic to inspect its time series."}
                </p>
            ) : (
                <>
                    <p className="factor-method">
                        {descriptor.definition.method === "IC"
                            ? "IC · Pearson cross-sectional correlation"
                            : descriptor.definition.method === "RANK_IC"
                              ? "Rank IC · average-rank Spearman cross-sectional correlation"
                              : descriptor.definition.method}{" "}
                        · minimum {descriptor.definition.minimumObservations} observed pairs
                    </p>
                    <p className="factor-caption">
                        Target: {descriptor.target.outputName}. This is not correlation with raw
                        price, and not a single-stock temporal correlation coefficient. Missing or
                        invalid observations remain NULL with their source status.
                    </p>
                    <StatisticsEvidence
                        key={`${descriptor.statisticsFingerprint}:${params.get("from") ?? ""}:${params.get("to") ?? ""}`}
                        result={result}
                        descriptor={descriptor}
                        {...range}
                    />
                </>
            )}
            <p className="factor-caption">
                Mean IC, IR, Factor-pair and stability summaries are not exposed by the current Web
                API. No substitute summaries are calculated here.
            </p>
        </section>
    );
}
