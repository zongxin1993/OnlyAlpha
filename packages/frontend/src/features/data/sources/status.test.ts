import {
    candidateSummary,
    capabilitySummary,
    describeError,
    probeCheckRows,
    probeSupport,
    sourcePresentation,
    sourceRank,
    summarizeSources
} from "./status";
import { IntegrationWebError } from "../../../api/integrations/client";

function active(status: string | undefined) {
    return { lifecycle_state: "ACTIVE", status };
}

it("keeps UNKNOWN out of the abnormal count and inside the unverified count", () => {
    const summary = summarizeSources([active("UNKNOWN")]);
    expect(summary.abnormal).toBe(0);
    expect(summary.unverified).toBe(1);
    expect(summary.countText).toBe("1 未验证");
});

it.each(["DEGRADED", "OFFLINE", "FAILED"])("counts %s as abnormal", (status) => {
    const summary = summarizeSources([active(status)]);
    expect(summary.abnormal).toBe(1);
    expect(summary.unverified).toBe(0);
    expect(summary.countText).toBe("1 异常");
});

it("excludes DISABLED and ARCHIVED from both counts", () => {
    const summary = summarizeSources([
        { lifecycle_state: "DISABLED", status: "FAILED" },
        { lifecycle_state: "ARCHIVED", status: "OFFLINE" }
    ]);
    expect(summary.abnormal).toBe(0);
    expect(summary.unverified).toBe(0);
    expect(summary.indicator).toBe("empty");
    expect(summary.countText).toBe("");
});

it("does not present an unverifiable set as a warning", () => {
    expect(summarizeSources([active("UNKNOWN")]).indicator).toBe("unverified");
    expect(summarizeSources([active("UNKNOWN"), active("READY")]).indicator).toBe("unverified");
    expect(summarizeSources([active("UNKNOWN"), active("DEGRADED")]).indicator).toBe("degraded");
    expect(summarizeSources([active("FAILED"), active("UNKNOWN")]).indicator).toBe("failed");
    expect(summarizeSources([active("READY"), active("READY")]).indicator).toBe("ready");
    expect(summarizeSources([]).indicator).toBe("empty");
});

it("treats an unloaded status as unverified rather than as healthy", () => {
    const summary = summarizeSources([active(undefined)]);
    expect(summary.abnormal).toBe(0);
    expect(summary.unverified).toBe(1);
});

it("orders the configured list by severity and excludes archived by default", () => {
    expect(sourceRank("ACTIVE", "FAILED")).toBeLessThan(sourceRank("ACTIVE", "DEGRADED"));
    expect(sourceRank("ACTIVE", "DEGRADED")).toBeLessThan(sourceRank("ACTIVE", "UNKNOWN"));
    expect(sourceRank("ACTIVE", "UNKNOWN")).toBeLessThan(sourceRank("ACTIVE", "READY"));
    expect(sourceRank("ACTIVE", "READY")).toBeLessThan(sourceRank("DISABLED", "READY"));
    expect(sourceRank("DISABLED", "READY")).toBe(sourceRank("ARCHIVED", "READY"));
});

it("separates lifecycle from operational health", () => {
    expect(sourcePresentation("DISABLED", "FAILED").label).toBe("已禁用");
    expect(sourcePresentation("ARCHIVED", "OFFLINE").label).toBe("已归档");
    expect(sourcePresentation("ACTIVE", "OFFLINE").label).toBe("连接中断");
    expect(sourcePresentation("ACTIVE", "UNKNOWN").label).toBe("未验证");
});

it("requires the type descriptor to declare Probe support", () => {
    expect(probeSupport(true, true)).toMatchObject({ canProbe: true, notice: null });
    expect(probeSupport(true, undefined).canProbe).toBe(true);
    expect(probeSupport(false, false).notice).toBe("该类型未提供连接测试");
    expect(probeSupport(false, undefined).canProbe).toBe(false);
    expect(probeSupport(true, false).canProbe).toBe(false);
    expect(probeSupport(false, true).canProbe).toBe(false);
});

it("distinguishes skipped, undeclared and missing Probe checks", () => {
    const attempt = {
        checks: [
            {
                check: "CONNECTIVITY",
                status: "PASS",
                latency_ms: 12,
                detail: "",
                error_code: null,
                failure_kind: null,
                observations: []
            },
            {
                check: "REFERENCE_DATA",
                status: "SKIPPED",
                latency_ms: 0,
                detail: "",
                error_code: null,
                failure_kind: null,
                observations: []
            },
            {
                check: "HISTORICAL_DATA",
                status: "FAIL",
                latency_ms: 5,
                detail: "boom",
                error_code: "X_FAILED",
                failure_kind: "FAILED",
                observations: []
            }
        ]
    } as unknown as Parameters<typeof probeCheckRows>[1];
    const rows = probeCheckRows(
        ["CONNECTIVITY", "REFERENCE_DATA", "HISTORICAL_DATA", "REALTIME_DATA"],
        attempt
    );
    const byCheck = new Map(rows.map((row) => [row.check, row]));
    expect(byCheck.get("CONNECTIVITY")?.state).toBe("PASS");
    expect(byCheck.get("REFERENCE_DATA")?.state).toBe("SKIPPED");
    expect(byCheck.get("HISTORICAL_DATA")?.state).toBe("FAIL");
    expect(byCheck.get("REALTIME_DATA")?.state).toBe("MISSING");
    expect(rows).toHaveLength(5);
    expect(byCheck.get("AUTHENTICATION")?.state).toBe("UNDECLARED");
});

it("maps capabilities into the shared display buckets without provider branches", () => {
    const summary = capabilitySummary([
        "HISTORICAL_BARS",
        "LIVE_TICKS",
        "INSTRUMENTS",
        "SUPPORTS_RUNTIME_CHECKPOINT:STATELESS",
        "FUTURE_CAPABILITY"
    ]);
    expect(summary).toEqual({
        historical: true,
        realtime: true,
        reference: true,
        unmapped: ["FUTURE_CAPABILITY"]
    });
});

it("keeps the canonical error code and adds a recovery hint per status", () => {
    expect(describeError(new IntegrationWebError("FORBIDDEN", "denied", 403))).toContain(
        "没有权限"
    );
    expect(describeError(new IntegrationWebError("FORBIDDEN", "denied", 403))).toContain(
        "FORBIDDEN"
    );
    expect(describeError(new IntegrationWebError("MISSING", "gone", 404))).toContain("已不存在");
    expect(describeError(new IntegrationWebError("RATE", "slow down", 429))).toContain("过于频繁");
    expect(describeError(new IntegrationWebError("BOOM", "server", 503))).toContain("暂时不可用");
    expect(describeError(new IntegrationWebError("CONFLICT", "cas", 409))).toBe("CONFLICT: cas");
    expect(describeError(undefined)).toBe("请求失败");
});

it("bounds long candidate lists so one binding row cannot run away", () => {
    expect(candidateSummary(["a", "b"])).toBe("a、b");
    expect(candidateSummary(["a", "b", "c", "d", "e"])).toBe("a、b、c 等 5 个");
    expect(candidateSummary([])).toBe("");
});
