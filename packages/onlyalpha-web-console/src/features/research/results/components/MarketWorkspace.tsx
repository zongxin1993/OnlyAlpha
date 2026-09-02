import { useInfiniteQuery } from "@tanstack/react-query";
import { useResearchApi } from "../../../../app/providers";
import type {
    ResearchMarketPoint,
    ResearchPublishedSeries,
    ResearchSignalPoint,
    ResearchVariablePoint
} from "../../../../domain/research/model";
import { FinancialEvidenceChart } from "../../../../visualization/financial/lightweight/FinancialEvidenceChart";
import {
    projectMarketEvidence,
    projectSignalEvidence,
    projectVariableEvidence
} from "../../../../visualization/projection/financialProjection";
import { QueryError } from "../../../../shared/components/QueryState";
import { marketSeriesOptions, signalSeriesOptions, variableSeriesOptions } from "../../queries";
import { mergeScientificSeriesPages } from "../../series/pagination";
import { useResultWorkspace } from "../ResultWorkspaceContext";
import { publishedSeriesKey } from "../model/selectors";
import { admitPresentation } from "../model/presentationAdmission";

export function MarketWorkspace() {
    const { summary, candidates, published, selection, dispatch, scientificUnavailable } =
        useResultWorkspace();
    if (scientificUnavailable)
        return (
            <p className="warning">
                Market Scientific Evidence is unavailable for this Artifact profile.
            </p>
        );
    const candidate = candidates?.candidates.find(
        (item) => item.candidateFingerprint === selection.candidateFingerprint
    );
    if (candidate === undefined || selection.instrumentId === null || published === null)
        return <p role="status">Loading exact Market selectors…</p>;
    const compatible = published.series.filter(
        (series) =>
            series.candidateFingerprint === null ||
            series.candidateFingerprint === candidate.candidateFingerprint
    );
    const selectedSeries =
        compatible.find((series) => publishedSeriesKey(series) === selection.seriesKey) ?? null;
    return (
        <section aria-labelledby="market-heading">
            <div className="section-heading">
                <div>
                    <p className="eyebrow">Artifact Market + Published Evidence</p>
                    <h2 id="market-heading">Financial viewer</h2>
                </div>
            </div>
            <div className="viewer-selectors">
                <label>
                    Instrument
                    <select
                        value={selection.instrumentId}
                        onChange={(event) => {
                            dispatch({ type: "INSTRUMENT", value: event.target.value });
                        }}
                    >
                        {summary.instrumentIds.map((instrument) => (
                            <option key={instrument}>{instrument}</option>
                        ))}
                    </select>
                </label>
                <label>
                    Published series
                    <select
                        value={selection.seriesKey ?? ""}
                        onChange={(event) => {
                            dispatch({ type: "SERIES", value: event.target.value });
                        }}
                    >
                        <option value="">Market only</option>
                        {compatible.map((series) => (
                            <option
                                key={publishedSeriesKey(series)}
                                value={publishedSeriesKey(series)}
                            >
                                {series.outputName} · {series.valueKind}
                            </option>
                        ))}
                    </select>
                </label>
            </div>
            <LoadedMarketEvidence
                candidate={candidate.candidateFingerprint}
                instrumentId={selection.instrumentId}
                series={selectedSeries}
                signalRoles={candidate.signalRoles}
            />
        </section>
    );
}

function LoadedMarketEvidence({
    candidate,
    instrumentId,
    series,
    signalRoles
}: {
    readonly candidate: NonNullable<
        ReturnType<typeof useResultWorkspace>["candidates"]
    >["candidates"][number]["candidateFingerprint"];
    readonly instrumentId: string;
    readonly series: ResearchPublishedSeries | null;
    readonly signalRoles: NonNullable<
        ReturnType<typeof useResultWorkspace>["candidates"]
    >["candidates"][number]["signalRoles"];
}) {
    const { summary } = useResultWorkspace();
    const client = useResearchApi();
    const market = useInfiniteQuery(
        marketSeriesOptions(client, summary.researchResultFingerprint, instrumentId)
    );
    const variable = useInfiniteQuery({
        ...(series === null
            ? variableSeriesOptions(client, summary.researchResultFingerprint, instrumentId, {
                  candidateFingerprint: candidate,
                  calculationFingerprint: candidate,
                  nodeFingerprint: candidate,
                  outputName: "disabled",
                  valueKind: "DECIMAL"
              })
            : variableSeriesOptions(
                  client,
                  summary.researchResultFingerprint,
                  instrumentId,
                  series
              )),
        enabled: series !== null
    });
    const entryRole = signalRoles.includes("ENTRY_SIGNAL") ? "ENTRY_SIGNAL" : null;
    const exitRole = signalRoles.includes("EXIT_SIGNAL") ? "EXIT_SIGNAL" : null;
    const entry = useInfiniteQuery({
        ...signalSeriesOptions(
            client,
            summary.researchResultFingerprint,
            instrumentId,
            candidate,
            entryRole ?? "ELIGIBILITY"
        ),
        enabled: entryRole !== null
    });
    const exit = useInfiniteQuery({
        ...signalSeriesOptions(
            client,
            summary.researchResultFingerprint,
            instrumentId,
            candidate,
            exitRole ?? "ELIGIBILITY"
        ),
        enabled: exitRole !== null
    });
    const pending =
        market.isPending ||
        (series !== null && variable.isPending) ||
        (entryRole !== null && entry.isPending) ||
        (exitRole !== null && exit.isPending);
    if (pending) return <p role="status">Loading bounded exact financial evidence…</p>;
    for (const query of [market, variable, entry, exit])
        if (query.isError)
            return <QueryError error={query.error} retry={() => void query.refetch()} />;
    const admission = admitPresentation(() => {
        const marketPoints = mergeScientificSeriesPages(market.data?.pages ?? []).filter(
            (point): point is ResearchMarketPoint => point.kind === "MARKET"
        );
        const variablePoints =
            series === null
                ? []
                : mergeScientificSeriesPages(variable.data?.pages ?? []).filter(
                      (point): point is ResearchVariablePoint => point.kind === "VARIABLE"
                  );
        const entryPoints =
            entryRole === null
                ? []
                : mergeScientificSeriesPages(entry.data?.pages ?? []).filter(
                      (point): point is ResearchSignalPoint => point.kind === "SIGNAL"
                  );
        const exitPoints =
            exitRole === null
                ? []
                : mergeScientificSeriesPages(exit.data?.pages ?? []).filter(
                      (point): point is ResearchSignalPoint => point.kind === "SIGNAL"
                  );
        const marketProjection = projectMarketEvidence(marketPoints);
        const variableProjection = projectVariableEvidence(variablePoints);
        const entryProjection = projectSignalEvidence(entryRole ?? "ENTRY_SIGNAL", entryPoints);
        const exitProjection = projectSignalEvidence(exitRole ?? "EXIT_SIGNAL", exitPoints);
        return {
            marketPoints,
            variablePoints,
            entryPoints,
            exitPoints,
            marketProjection,
            variableProjection,
            entryProjection,
            exitProjection
        };
    });
    if (!admission.ok)
        return (
            <p className="error" role="alert">
                CONTRACT_ERROR: paginated Scientific evidence is inconsistent
            </p>
        );
    const {
        marketPoints,
        variablePoints,
        entryPoints,
        exitPoints,
        marketProjection,
        variableProjection,
        entryProjection,
        exitProjection
    } = admission.value;
    const failure = [marketProjection, variableProjection, entryProjection, exitProjection].find(
        (projection) => !projection.ok
    );
    if (failure !== undefined)
        return (
            <p className="warning">
                {failure.code}: {failure.detail}
            </p>
        );
    if (!marketProjection.ok || !variableProjection.ok || !entryProjection.ok || !exitProjection.ok)
        return null;
    return (
        <>
            {marketPoints.length === 0 ? (
                <p>No Market evidence exists for this exact instrument.</p>
            ) : (
                <FinancialEvidenceChart
                    candles={marketProjection.value.candles}
                    volume={marketProjection.value.volume}
                    variable={variableProjection.value}
                    markers={[...entryProjection.value, ...exitProjection.value].sort(
                        (left, right) =>
                            left.time - right.time ||
                            (left.role < right.role ? -1 : left.role > right.role ? 1 : 0)
                    )}
                />
            )}
            <div className="evidence-status">
                {marketPoints.length} market · {variablePoints.length} variable ·{" "}
                {entryPoints.length + exitPoints.length} signal rows loaded
            </div>
            {[market, variable, entry, exit].some((query) => query.hasNextPage) ? (
                <button
                    type="button"
                    onClick={() => {
                        for (const query of [market, variable, entry, exit])
                            if (query.hasNextPage) void query.fetchNextPage();
                    }}
                >
                    Load next bounded evidence pages
                </button>
            ) : null}
        </>
    );
}
