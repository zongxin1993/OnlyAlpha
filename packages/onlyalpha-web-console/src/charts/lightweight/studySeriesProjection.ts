import type { LineData, UTCTimestamp, WhitespaceData } from "lightweight-charts";
import type { ChartStudyInstance } from "../../features/workspace/chartStudy";
import { z } from "zod";

/** Read-only presentation input, NOT a Product DTO or proof of Result admission.
 * There is no production adapter yet. Test evidence is explicit and cannot be
 * obtained by the shipping Workspace. A future verified Query adapter must own
 * scientific admission before extending this source family.
 */
export interface StudySeriesEvidence {
    readonly source: { readonly kind: "CONTROLLED_TEST_EVIDENCE"; readonly fixtureId: string };
    readonly instanceId: string;
    readonly chartContextKey: string;
    readonly incarnationKey: string;
    readonly configurationKey: string;
    readonly outputName: string;
    readonly points: readonly {
        readonly timeNs: string;
        readonly value: string | null;
        readonly readiness: string | null;
        readonly reason: string | null;
    }[];
}
export interface StudySeriesProjection {
    readonly pointsByTime: ReadonlyMap<number, StudySeriesEvidence["points"][number]>;
    /** Separate contiguous lines: native whitespace alone can bridge a gap. */
    readonly segments: readonly (readonly (
        LineData<UTCTimestamp> | WhitespaceData<UTCTimestamp>
    )[])[];
}
export type StudySeriesView =
    | { readonly status: "NOT_CONNECTED" | "STALE" | "INVALID"; readonly detail: string }
    | { readonly status: "PROJECTED"; readonly projection: StudySeriesProjection };

const text = z.string().min(1);
const evidenceShape = z.strictObject({
    source: z.strictObject({ kind: z.literal("CONTROLLED_TEST_EVIDENCE"), fixtureId: text }),
    instanceId: text,
    chartContextKey: text,
    incarnationKey: text,
    configurationKey: text,
    outputName: text,
    points: z.array(
        z.strictObject({
            timeNs: text,
            value: z.string().nullable(),
            readiness: text.nullable(),
            reason: z.string().nullable()
        })
    )
});
export function isStudySeriesEvidence(value: unknown): value is StudySeriesEvidence {
    return evidenceShape.safeParse(value).success;
}

export function projectStudySeries(
    instance: ChartStudyInstance,
    incarnationKey: string,
    timeline: readonly number[],
    evidence: StudySeriesEvidence | undefined
): StudySeriesView {
    if (instance.connectionState === "STALE_CONFIG")
        return { status: "STALE", detail: "配置已过期；无可用结果" };
    if (evidence === undefined) return { status: "NOT_CONNECTED", detail: "尚未计算 / 无可用结果" };
    if (!isStudySeriesEvidence(evidence))
        return { status: "INVALID", detail: "非法展示证据结构 / scalar 类型" };
    if (
        evidence.instanceId !== instance.instanceId ||
        evidence.chartContextKey !== instance.context.key ||
        evidence.incarnationKey !== incarnationKey ||
        evidence.outputName !== instance.configuration.outputName ||
        evidence.configurationKey !== JSON.stringify(instance.configuration)
    )
        return { status: "INVALID", detail: "展示证据与实例 / 上下文 / 输入不匹配" };
    try {
        const sourceKind: unknown = evidence.source.kind;
        if (sourceKind !== "CONTROLLED_TEST_EVIDENCE" || evidence.source.fixtureId.trim() === "")
            throw new Error("缺少来源证明");
        const pointsByTime = new Map<number, StudySeriesEvidence["points"][number]>();
        const numeric = new Map<number, number>();
        let previous = -Infinity;
        for (const point of evidence.points) {
            if (!/^(?:0|[1-9][0-9]*)$/.test(point.timeNs) || point.timeNs.length > 30)
                throw new Error("非法 UTC timestamp");
            const ns = BigInt(point.timeNs),
                time = Number(ns / 1_000_000_000n);
            // Exact whole seconds only: do not alias distinct nanosecond identities.
            if (
                ns % 1_000_000_000n !== 0n ||
                !Number.isSafeInteger(time) ||
                !Number.isFinite(new Date(time * 1000).getTime()) ||
                time <= previous
            )
                throw new Error("重复 / 倒序 / 不安全 timestamp");
            previous = time;
            if (point.value !== null) {
                if (
                    !/^-?(?:0|[1-9][0-9]*)(?:\.\d+)?$/.test(point.value) ||
                    point.value.length > 4096
                )
                    throw new Error("非法数值文本");
                // Deliberately lossy plotting only; hover retains the original text.
                const value = Number(point.value);
                if (
                    !Number.isFinite(value) ||
                    Math.abs(value) > Number.MAX_SAFE_INTEGER ||
                    (value === 0 && /[1-9]/.test(point.value))
                )
                    throw new Error("无法安全显示数值");
                numeric.set(time, value);
            }
            pointsByTime.set(time, { ...point });
        }
        const times = [...new Set([...timeline, ...pointsByTime.keys()])].sort((a, b) => a - b);
        const segments: (LineData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[][] = [];
        let run = new Map<number, LineData<UTCTimestamp>>();
        const flush = () => {
            if (run.size > 0) {
                segments.push(times.map((time) => run.get(time) ?? { time: time as UTCTimestamp }));
                run = new Map();
            }
        };
        for (const time of times) {
            const value = numeric.get(time);
            if (value === undefined) flush();
            else run.set(time, { time: time as UTCTimestamp, value });
        }
        flush();
        return { status: "PROJECTED", projection: { pointsByTime, segments } };
    } catch (error) {
        return {
            status: "INVALID",
            detail: error instanceof Error ? error.message : "非法展示证据"
        };
    }
}

export function studyHover(view: StudySeriesView, time: number | null): string {
    if (view.status !== "PROJECTED") return view.detail;
    if (time === null) return "请移动十字线查看精确点";
    const point = view.projection.pointsByTime.get(time);
    if (point === undefined) return "此时间无对应结果";
    return `${new Date(time * 1000).toISOString()} · ${point.value ?? "无数值"}${point.readiness === null ? "" : ` · ${point.readiness}`}${point.reason === null ? "" : ` · ${point.reason}`}`;
}
