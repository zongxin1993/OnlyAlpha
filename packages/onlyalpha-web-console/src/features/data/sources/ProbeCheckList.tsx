import type { IntegrationProbeAttempt } from "../../../api/integrations/model";
import { probeCheckRows, probeCheckStateLabel, type ProbeCheckState } from "./status";

function CheckGlyph({ state }: { readonly state: ProbeCheckState }) {
    const path =
        state === "PASS"
            ? "M1.6 5.3 4 7.7 8.4 2.5"
            : state === "FAIL"
              ? "M2.2 2.2 7.8 7.8M7.8 2.2 2.2 7.8"
              : "M2 5h6";
    return (
        <span className={`probe-check__glyph probe-check__glyph--${state.toLowerCase()}`}>
            <svg viewBox="0 0 10 10" fill="none" aria-hidden="true" focusable="false">
                <path
                    d={path}
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeDasharray={
                        state === "SKIPPED" || state === "UNDECLARED" ? "1.6 1.4" : undefined
                    }
                />
            </svg>
        </span>
    );
}

export function ProbeCheckList({
    declared,
    attempt
}: {
    readonly declared: readonly string[];
    readonly attempt: IntegrationProbeAttempt | undefined;
}) {
    const rows = probeCheckRows(declared, attempt);
    return (
        <ul className="probe-checks" aria-label="连接测试检查项">
            {rows.map((row) => (
                <li
                    key={row.check}
                    className={`probe-check probe-check--${row.state.toLowerCase()}`}
                >
                    <span className="probe-check__name">{row.label}</span>
                    <span className="probe-check__latency value">
                        {row.latencyMs === null ? "—" : `${String(row.latencyMs)} ms`}
                    </span>
                    <span className="probe-check__result">
                        <CheckGlyph state={row.state} />
                        <span className="probe-check__state">
                            {probeCheckStateLabel(row.state)}
                        </span>
                        <span className="probe-check__detail">
                            {row.state === "FAIL"
                                ? [row.detail, row.errorCode].filter(Boolean).join(" · ")
                                : ""}
                        </span>
                    </span>
                </li>
            ))}
        </ul>
    );
}
