import type { IntegrationProbeAttempt } from "../../../api/integrations/model";

export type StatusTone = "ready" | "degraded" | "failed" | "unverified" | "disabled";

export interface StatusPresentation {
    readonly label: string;
    readonly tone: StatusTone;
}

const operationalLabels: Readonly<Record<string, StatusPresentation>> = {
    READY: { label: "正常", tone: "ready" },
    DEGRADED: { label: "降级", tone: "degraded" },
    OFFLINE: { label: "连接中断", tone: "failed" },
    FAILED: { label: "失败", tone: "failed" }
};

/** Canonical operational status projection. Unknown values keep their uncertainty. */
export function operationalPresentation(status: string): StatusPresentation {
    return operationalLabels[status] ?? { label: "未验证", tone: "unverified" };
}

/**
 * Lifecycle is a separate axis from operational health: a disabled source is not a
 * failed source, and an archived source is not an offline source.
 */
export function sourcePresentation(
    lifecycleState: string,
    operationalStatus: string | undefined
): StatusPresentation {
    if (lifecycleState === "ARCHIVED") return { label: "已归档", tone: "disabled" };
    if (lifecycleState === "DISABLED") return { label: "已禁用", tone: "disabled" };
    if (operationalStatus === undefined) return { label: "状态未知", tone: "unverified" };
    return operationalPresentation(operationalStatus);
}

export interface SourceSummary {
    readonly active: number;
    readonly abnormal: number;
    readonly unverified: number;
    readonly indicator: StatusTone | "empty";
    readonly countText: string;
}

export interface SourceSummaryInput {
    readonly lifecycle_state: string;
    readonly status: string | undefined;
}

const abnormalStatuses = new Set(["DEGRADED", "OFFLINE", "FAILED"]);

/**
 * UNKNOWN is unverified, never abnormal; DISABLED and ARCHIVED are excluded from both
 * counts, and an UNKNOWN-only set must not present itself as a warning.
 */
export function summarizeSources(items: readonly SourceSummaryInput[]): SourceSummary {
    const active = items.filter((item) => item.lifecycle_state === "ACTIVE");
    const abnormal = active.filter((item) => abnormalStatuses.has(item.status ?? "")).length;
    const unverified = active.filter(
        (item) => item.status !== "READY" && !abnormalStatuses.has(item.status ?? "")
    ).length;
    const indicator: SourceSummary["indicator"] =
        active.length === 0
            ? "empty"
            : active.some((item) => item.status === "OFFLINE" || item.status === "FAILED")
              ? "failed"
              : active.some((item) => item.status === "DEGRADED")
                ? "degraded"
                : unverified > 0
                  ? "unverified"
                  : "ready";
    const counts: string[] = [];
    if (abnormal > 0) counts.push(`${String(abnormal)} 异常`);
    if (unverified > 0) counts.push(`${String(unverified)} 未验证`);
    return {
        active: active.length,
        abnormal,
        unverified,
        indicator,
        countText: counts.join(" · ")
    };
}

/** Approved list ordering: abnormal, degraded, unverified, ready, disabled/archived. */
export function sourceRank(lifecycleState: string, status: string | undefined): number {
    if (lifecycleState !== "ACTIVE") return 4;
    if (status === "OFFLINE" || status === "FAILED") return 0;
    if (status === "DEGRADED") return 1;
    if (status !== "READY") return 2;
    return 3;
}

export interface CapabilitySummary {
    readonly historical: boolean;
    readonly realtime: boolean;
    readonly reference: boolean;
    readonly unmapped: readonly string[];
}

const historicalCapabilities = new Set([
    "HISTORICAL_BARS",
    "HISTORICAL_TICKS",
    "HISTORICAL_REFERENCE_PRICES",
    "HISTORICAL_FUNDING_RATES",
    "HISTORICAL_SETTLEMENTS"
]);
const realtimeCapabilities = new Set(["LIVE_BARS", "LIVE_TICKS", "LIVE_RECONNECT"]);
const referenceCapabilities = new Set(["INSTRUMENTS", "CALENDARS"]);
const runtimeCapabilityPrefixes = ["SUPPORTS_RUNTIME_CHECKPOINT", "CHECKPOINT_SCHEMA_VERSION"];

/** One shared capability to display-bucket mapping; never branched per provider. */
export function capabilitySummary(capabilities: readonly string[]): CapabilitySummary {
    const runtime = capabilities.filter((item) =>
        runtimeCapabilityPrefixes.some((prefix) => item.startsWith(prefix))
    );
    const buckets = capabilities.filter((item) => !runtime.includes(item));
    const unmapped = buckets.filter(
        (item) =>
            !historicalCapabilities.has(item) &&
            !realtimeCapabilities.has(item) &&
            !referenceCapabilities.has(item)
    );
    return {
        historical: buckets.some((item) => historicalCapabilities.has(item)),
        realtime: buckets.some((item) => realtimeCapabilities.has(item)),
        reference: buckets.some((item) => referenceCapabilities.has(item)),
        unmapped
    };
}

export interface ProbeSupport {
    readonly canProbe: boolean;
    readonly notice: string | null;
    readonly tone: StatusTone;
}

const undeclaredProbeNotice = "该类型未提供连接测试";

/**
 * Probe support is declared by the Integration Type Descriptor. The server projection
 * must agree with it; a disagreement is surfaced instead of being resolved silently.
 */
export function probeSupport(
    declared: boolean,
    serverSupported: boolean | undefined
): ProbeSupport {
    if (declared && serverSupported !== false) {
        return { canProbe: true, notice: null, tone: "ready" };
    }
    if (declared) {
        return {
            canProbe: false,
            notice: "类型声明了连接测试，但服务端未报告该类型支持连接测试；当前无法执行。",
            tone: "degraded"
        };
    }
    if (serverSupported === true) {
        return {
            canProbe: false,
            notice: "类型契约未声明连接测试，但服务端报告支持；状态不一致，请先修复契约。",
            tone: "degraded"
        };
    }
    return { canProbe: false, notice: undeclaredProbeNotice, tone: "unverified" };
}

export const probeChecks = [
    "CONNECTIVITY",
    "AUTHENTICATION",
    "REFERENCE_DATA",
    "HISTORICAL_DATA",
    "REALTIME_DATA"
] as const;

const probeCheckLabels: Readonly<Record<string, string>> = {
    CONNECTIVITY: "连接",
    AUTHENTICATION: "认证",
    REFERENCE_DATA: "参考数据",
    HISTORICAL_DATA: "历史数据",
    REALTIME_DATA: "实时数据"
};

export type ProbeCheckState = "PASS" | "FAIL" | "SKIPPED" | "UNDECLARED" | "MISSING";

export interface ProbeCheckRow {
    readonly check: string;
    readonly label: string;
    readonly state: ProbeCheckState;
    readonly latencyMs: number | null;
    readonly detail: string;
    readonly errorCode: string | null;
    readonly failureKind: string | null;
}

const probeCheckStateLabels: Readonly<Record<ProbeCheckState, string>> = {
    PASS: "通过",
    FAIL: "失败",
    SKIPPED: "未验证",
    UNDECLARED: "不适用",
    MISSING: "未知"
};

export function probeCheckStateLabel(state: ProbeCheckState): string {
    return probeCheckStateLabels[state];
}

export function probeCheckLabel(check: string): string {
    return probeCheckLabels[check] ?? check;
}

/**
 * A skipped check was declared but not verified; an undeclared check is not a capability
 * of the type at all; a declared check without a result is unknown. None of them may be
 * rendered as success or failure.
 */
export function probeCheckRows(
    declared: readonly string[],
    attempt: IntegrationProbeAttempt | undefined
): readonly ProbeCheckRow[] {
    return probeChecks.map((check) => {
        const label = probeCheckLabel(check);
        if (!declared.includes(check)) {
            return {
                check,
                label,
                state: "UNDECLARED",
                latencyMs: null,
                detail: "",
                errorCode: null,
                failureKind: null
            };
        }
        const result = attempt?.checks.find((item) => item.check === check);
        if (result === undefined) {
            return {
                check,
                label,
                state: "MISSING",
                latencyMs: null,
                detail: "",
                errorCode: null,
                failureKind: null
            };
        }
        const state: ProbeCheckState =
            result.status === "PASS" || result.status === "FAIL" || result.status === "SKIPPED"
                ? result.status
                : "MISSING";
        return {
            check,
            label,
            state,
            latencyMs: result.latency_ms,
            detail: result.detail,
            errorCode: result.error_code,
            failureKind: result.failure_kind
        };
    });
}

export function probeDurationMs(attempt: IntegrationProbeAttempt): number {
    return new Date(attempt.completed_at).getTime() - new Date(attempt.started_at).getTime();
}

export function shortFingerprint(value: string | null | undefined): string {
    return value?.slice(0, 8) ?? "—";
}

/** Local operator-facing timestamp; canonical values stay untouched in the API layer. */
export function formatTimestamp(value: string | null | undefined): string {
    if (value === null || value === undefined || value === "") return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const pad = (part: number) => String(part).padStart(2, "0");
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
        date.getMinutes()
    )}:${pad(date.getSeconds())}`;
}

/**
 * Keeps the canonical error code visible (operators copy it into issues) while adding a
 * plain-language recovery hint for the statuses a browser client actually sees.
 */
export function describeError(value: unknown): string {
    if (typeof value !== "object" || value === null) return "请求失败";
    const code = "code" in value && typeof value.code === "string" ? value.code : "";
    const message = "message" in value && typeof value.message === "string" ? value.message : "";
    const status = "status" in value && typeof value.status === "number" ? value.status : undefined;
    const hint =
        status === 401 || status === 403
            ? " 没有权限执行该操作，请确认当前操作者权限。"
            : status === 404
              ? " 目标数据源已不存在，请刷新列表后重试。"
              : status === 429
                ? " 请求过于频繁，请稍后重试。"
                : status !== undefined && status >= 500
                  ? " 服务端暂时不可用，请稍后重试。"
                  : "";
    const head = code === "" ? message : `${code}: ${message}`;
    return head === "" ? `请求失败${hint}` : `${head}${hint}`;
}

export function candidateSummary(names: readonly string[], limit = 3): string {
    if (names.length === 0) return "";
    const shown = names.slice(0, limit).join("、");
    return names.length > limit ? `${shown} 等 ${String(names.length)} 个` : shown;
}
