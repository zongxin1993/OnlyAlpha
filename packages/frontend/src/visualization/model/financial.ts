import type { DecimalText } from "../../domain/research/decimal";
import type { UnixNanoseconds } from "../../domain/research/time";

export type FinancialTime = number & { readonly __financialTime: unique symbol };

export interface FinancialCandle {
    readonly time: FinancialTime;
    readonly open: number;
    readonly high: number;
    readonly low: number;
    readonly close: number;
}

export interface FinancialVolume {
    readonly time: FinancialTime;
    readonly value: number;
    readonly direction: "UP" | "DOWN";
}

export interface FinancialLinePoint {
    readonly time: FinancialTime;
    readonly value?: number;
}

export interface FinancialSignalMarker {
    readonly time: FinancialTime;
    readonly role: string;
    readonly position: "aboveBar" | "belowBar";
    readonly shape: "arrowUp" | "arrowDown";
}

export interface FinancialProjectionError {
    readonly ok: false;
    readonly code: "FINANCIAL_PROJECTION_ERROR";
    readonly detail: string;
}

export type FinancialProjection<T> =
    { readonly ok: true; readonly value: T } | FinancialProjectionError;

export interface ExactFinancialCoordinate {
    readonly tsEventNs: UnixNanoseconds;
    readonly value: DecimalText;
}
