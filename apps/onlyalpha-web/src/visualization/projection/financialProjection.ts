import type {
    ResearchMarketPoint,
    ResearchSignalPoint,
    ResearchVariablePoint
} from "../../domain/research/model";
import type {
    FinancialCandle,
    FinancialLinePoint,
    FinancialProjection,
    FinancialSignalMarker,
    FinancialTime,
    FinancialVolume
} from "../model/financial";

const error = (detail: string): FinancialProjectionError => ({
    ok: false,
    code: "FINANCIAL_PROJECTION_ERROR",
    detail
});

type FinancialProjectionError = Extract<FinancialProjection<never>, { ok: false }>;

export function projectFinancialTime(
    exact: bigint,
    previous?: { readonly ns: bigint; readonly second: bigint }
): FinancialProjection<{ readonly time: FinancialTime; readonly second: bigint }> {
    if (previous !== undefined && exact <= previous.ns)
        return error("Exact timestamps are not strictly ordered");
    const second = exact / 1_000_000_000n;
    if (previous?.second === second)
        return error("Distinct nanosecond timestamps collide at renderer-second resolution");
    const coordinate = Number(second);
    if (!Number.isSafeInteger(coordinate)) return error("Timestamp is outside safe renderer range");
    return { ok: true, value: { time: coordinate as FinancialTime, second } };
}

export function projectFiniteDecimal(value: string): FinancialProjection<number> {
    const coordinate = Number(value);
    return Number.isFinite(coordinate)
        ? { ok: true, value: coordinate }
        : error("Exact Decimal cannot be represented as a finite renderer coordinate");
}

export function projectMarketEvidence(points: readonly ResearchMarketPoint[]): FinancialProjection<{
    readonly candles: readonly FinancialCandle[];
    readonly volume: readonly FinancialVolume[];
}> {
    const candles: FinancialCandle[] = [];
    const volume: FinancialVolume[] = [];
    let previous: { readonly ns: bigint; readonly second: bigint } | undefined;
    for (const point of points) {
        const projectedTime = projectFinancialTime(point.tsEventNs, previous);
        if (!projectedTime.ok) return projectedTime;
        const values = [
            projectFiniteDecimal(point.open),
            projectFiniteDecimal(point.high),
            projectFiniteDecimal(point.low),
            projectFiniteDecimal(point.close),
            projectFiniteDecimal(point.volume)
        ] as const;
        const failure = values.find((value) => !value.ok);
        if (failure !== undefined) return failure;
        const open = values[0].ok ? values[0].value : Number.NaN;
        const high = values[1].ok ? values[1].value : Number.NaN;
        const low = values[2].ok ? values[2].value : Number.NaN;
        const close = values[3].ok ? values[3].value : Number.NaN;
        const amount = values[4].ok ? values[4].value : Number.NaN;
        if (high < Math.max(open, close) || low > Math.min(open, close) || low > high)
            return error("OHLC evidence cannot be projected because its price bounds are invalid");
        candles.push({ time: projectedTime.value.time, open, high, low, close });
        volume.push({
            time: projectedTime.value.time,
            value: amount,
            direction: close >= open ? "UP" : "DOWN"
        });
        previous = { ns: point.tsEventNs, second: projectedTime.value.second };
    }
    return { ok: true, value: { candles, volume } };
}

export function projectVariableEvidence(
    points: readonly ResearchVariablePoint[]
): FinancialProjection<readonly FinancialLinePoint[]> {
    const result: FinancialLinePoint[] = [];
    let previous: { readonly ns: bigint; readonly second: bigint } | undefined;
    for (const point of points) {
        const projectedTime = projectFinancialTime(point.tsEventNs, previous);
        if (!projectedTime.ok) return projectedTime;
        const exact =
            point.valueKind === "DECIMAL"
                ? point.decimalValue
                : point.valueKind === "INTEGER"
                  ? point.integerValue
                  : null;
        if (point.valueKind === "BOOLEAN" || point.valueKind === "STRING")
            return error(`${point.valueKind} Published Series is exact-table only`);
        if (exact === null) result.push({ time: projectedTime.value.time });
        else {
            const value = projectFiniteDecimal(exact);
            if (!value.ok) return value;
            result.push({ time: projectedTime.value.time, value: value.value });
        }
        previous = { ns: point.tsEventNs, second: projectedTime.value.second };
    }
    return { ok: true, value: result };
}

export function projectSignalEvidence(
    role: string,
    points: readonly ResearchSignalPoint[]
): FinancialProjection<readonly FinancialSignalMarker[]> {
    const markers: FinancialSignalMarker[] = [];
    let previous: { readonly ns: bigint; readonly second: bigint } | undefined;
    for (const point of points) {
        const projectedTime = projectFinancialTime(point.tsEventNs, previous);
        if (!projectedTime.ok) return projectedTime;
        if (point.value === true) {
            const entry = role.includes("ENTRY");
            markers.push({
                time: projectedTime.value.time,
                role,
                position: entry ? "belowBar" : "aboveBar",
                shape: entry ? "arrowUp" : "arrowDown"
            });
        }
        previous = { ns: point.tsEventNs, second: projectedTime.value.second };
    }
    return { ok: true, value: markers };
}
