import { useInfiniteQuery } from "@tanstack/react-query";
import { useResearchApi } from "../../../app/providers";
import type { ResearchResultFingerprint } from "../../../domain/research/identity";
import type {
    ResearchMarketPoint,
    ResearchScientificSeriesPage,
    ResearchVariablePoint
} from "../../../domain/research/model";
import { formatUtcNanoseconds } from "../../../domain/research/time";
import { QueryError } from "../../../shared/components/QueryState";
import { FinancialEvidenceChart } from "../../../visualization/financial/lightweight/FinancialEvidenceChart";
import {
    projectFinancialTime,
    projectMarketEvidence,
    projectVariableEvidence
} from "../../../visualization/projection/financialProjection";
import { marketSeriesOptions, variableSeriesOptions } from "../queries";
import { admitPresentation } from "../results/model/presentationAdmission";
import { mergeScientificSeriesPages } from "../series/pagination";
import type { FactorSeriesOption, parseFactorDateRange } from "./factorModel";

interface FactorInstrumentCardProps {
    readonly result: ResearchResultFingerprint;
    readonly option: FactorSeriesOption;
    readonly instrumentId: string;
    readonly range: ReturnType<typeof parseFactorDateRange>;
}

export function FactorInstrumentCard(props: FactorInstrumentCardProps) {
    return (
        <section
            className="factor-instrument-card"
            aria-label={`${props.instrumentId} Factor evidence`}
        >
            <header className="factor-card-heading">
                <div>
                    <h3>{props.instrumentId}</h3>
                    <p>{props.option.label}</p>
                </div>
                <span className="kind-label">Exact instrument</span>
            </header>
            <p className="evidence-status">
                Shared time axis only. This single-instrument co-plot is not a time-series
                correlation coefficient.
            </p>
            <FactorInstrumentEvidence {...props} />
        </section>
    );
}

function checkedPoints(
    pages: readonly ResearchScientificSeriesPage[],
    { result, instrumentId, range }: FactorInstrumentCardProps
): ResearchScientificSeriesPage["points"] {
    for (const page of pages) {
        if (page.researchResultFingerprint !== result)
            throw new Error("Scientific page belongs to another Research Result");
        if (page.hasMore && page.points.length === 0)
            throw new Error("Scientific page cannot continue without an exact cursor point");
    }
    const points = mergeScientificSeriesPages(pages);
    for (const point of points) {
        if (point.instrumentId !== instrumentId)
            throw new Error("Scientific point belongs to another exact instrument");
        if (
            (range.from !== undefined && point.tsEventNs < range.from) ||
            (range.to !== undefined && point.tsEventNs >= range.to)
        )
            throw new Error("Scientific point is outside the requested [from, to) range");
    }
    return points;
}

function crossSeriesProjectionFailure(
    market: readonly ResearchMarketPoint[],
    factor: readonly ResearchVariablePoint[]
): string | null {
    const exactTimes = new Map<number, bigint>();
    for (const point of [...market, ...factor]) {
        const projected = projectFinancialTime(point.tsEventNs);
        if (!projected.ok) return projected.detail;
        const previous = exactTimes.get(projected.value.time);
        if (previous !== undefined && previous !== point.tsEventNs)
            return "Distinct Market and Factor nanoseconds collide at one renderer-second coordinate";
        exactTimes.set(projected.value.time, point.tsEventNs);
    }
    return null;
}

function FactorInstrumentEvidence(props: FactorInstrumentCardProps) {
    const { result, option, instrumentId, range } = props;
    const client = useResearchApi();
    const market = useInfiniteQuery(
        marketSeriesOptions(client, result, instrumentId, 500, range.from, range.to)
    );
    const factor = useInfiniteQuery(
        variableSeriesOptions(
            client,
            result,
            instrumentId,
            option.series,
            500,
            range.from,
            range.to
        )
    );
    if (market.isError)
        return <QueryError error={market.error} retry={() => void market.refetch()} />;
    if (factor.isError)
        return <QueryError error={factor.error} retry={() => void factor.refetch()} />;
    if (market.isPending || factor.isPending)
        return <p role="status">Loading bounded exact Market and Factor evidence…</p>;

    const admission = admitPresentation(() => {
        const marketPoints = checkedPoints(market.data.pages, props);
        const factorPoints = checkedPoints(factor.data.pages, props);
        if (!marketPoints.every((point): point is ResearchMarketPoint => point.kind === "MARKET"))
            throw new Error("Market page contains unexpected evidence kinds");
        if (
            !factorPoints.every(
                (point): point is ResearchVariablePoint => point.kind === "VARIABLE"
            )
        )
            throw new Error("Factor page contains unexpected evidence kinds");
        if (
            !["DECIMAL", "INTEGER"].includes(option.series.valueKind) ||
            factorPoints.some((point) => point.valueKind !== option.series.valueKind)
        )
            throw new Error("Factor point value kind does not match the selected Published Series");
        return { marketPoints, factorPoints };
    });
    if (!admission.ok)
        return (
            <p className="error" role="alert">
                CONTRACT_ERROR: Market / Factor page identity, kind, range, or cursor does not match
                the exact selection. Misbound evidence is not displayed.
            </p>
        );

    const { marketPoints, factorPoints } = admission.value;
    const marketProjection = projectMarketEvidence(marketPoints);
    const factorProjection = projectVariableEvidence(factorPoints);
    const projectionFailure = !marketProjection.ok
        ? marketProjection.detail
        : !factorProjection.ok
          ? factorProjection.detail
          : crossSeriesProjectionFailure(marketPoints, factorPoints);
    const loadingMore = market.isFetchingNextPage || factor.isFetchingNextPage;
    return (
        <>
            {projectionFailure !== null ? (
                <p className="warning">
                    FINANCIAL_PROJECTION_ERROR: {projectionFailure}. Exact evidence remains below.
                </p>
            ) : marketProjection.ok &&
              factorProjection.ok &&
              (marketPoints.length > 0 || factorPoints.length > 0) ? (
                <FinancialEvidenceChart
                    candles={marketProjection.value.candles}
                    volume={marketProjection.value.volume}
                    variable={factorProjection.value}
                    markers={[]}
                    variablePane
                    variableLabel={option.label}
                />
            ) : null}
            {marketPoints.length === 0 ? (
                <p>No Market rows exist in this exact selection.</p>
            ) : null}
            {factorPoints.length === 0 ? (
                <p>No Factor rows exist in this exact selection.</p>
            ) : null}
            <p className="evidence-status">
                {marketPoints.length} Market rows · {factorPoints.length} Factor rows loaded.
                {market.hasNextPage || factor.hasNextPage
                    ? " More exact pages are available; this is a bounded partial view."
                    : " All returned pages are loaded."}
            </p>
            <details className="factor-exact-data" open={projectionFailure !== null}>
                <summary>Exact Market data ({marketPoints.length} rows)</summary>
                <div className="table-scroll">
                    <table
                        className="factor-table"
                        aria-label={`${instrumentId} exact Market evidence`}
                    >
                        <thead>
                            <tr>
                                <th>UTC time</th>
                                <th>Raw ts_event_ns</th>
                                <th>Open</th>
                                <th>High</th>
                                <th>Low</th>
                                <th>Close</th>
                                <th>Volume</th>
                            </tr>
                        </thead>
                        <tbody>
                            {marketPoints.map((point) => (
                                <tr key={point.tsEventNs.toString()}>
                                    <td>{formatUtcNanoseconds(point.tsEventNs)}</td>
                                    <td>
                                        <code>{point.tsEventNs.toString()}</code>
                                    </td>
                                    <td>{point.open}</td>
                                    <td>{point.high}</td>
                                    <td>{point.low}</td>
                                    <td>{point.close}</td>
                                    <td>{point.volume}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </details>
            <details className="factor-exact-data" open={projectionFailure !== null}>
                <summary>Exact Factor data ({factorPoints.length} rows)</summary>
                <div className="table-scroll">
                    <table
                        className="factor-table"
                        aria-label={`${instrumentId} exact Factor evidence`}
                    >
                        <thead>
                            <tr>
                                <th>UTC time</th>
                                <th>Raw ts_event_ns</th>
                                <th>Value kind</th>
                                <th>Exact Factor value</th>
                            </tr>
                        </thead>
                        <tbody>
                            {factorPoints.map((point) => (
                                <tr key={point.tsEventNs.toString()}>
                                    <td>{formatUtcNanoseconds(point.tsEventNs)}</td>
                                    <td>
                                        <code>{point.tsEventNs.toString()}</code>
                                    </td>
                                    <td>{point.valueKind}</td>
                                    <td>
                                        {(point.valueKind === "INTEGER"
                                            ? point.integerValue
                                            : point.decimalValue) ?? "NULL"}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </details>
            {market.hasNextPage || factor.hasNextPage ? (
                <button
                    type="button"
                    disabled={loadingMore}
                    onClick={() => {
                        if (loadingMore) return;
                        if (market.hasNextPage) void market.fetchNextPage();
                        if (factor.hasNextPage) void factor.fetchNextPage();
                    }}
                >
                    {loadingMore ? "Loading exact pages…" : "Load next bounded evidence pages"}
                </button>
            ) : null}
        </>
    );
}
