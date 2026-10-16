import { studyColorName } from "./studyColors";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { createUuidV4 } from "../../api/integrations/submissionIntent";
import type { ChartCalculationDraft } from "../../api/research/chartCatalog";
import { CalculationPicker } from "./CalculationPicker";
import { ChartStudyEditor } from "./ChartStudyEditor";
import {
    studyDescriptor,
    studyName,
    studyDisplayLabel,
    type ChartStudyContext,
    type ChartStudyInstance
} from "./chartStudy";
import "./chartStudy.css";
import type { ChartStudyCapability } from "../../api/chartStudies/client";
import type { LocalReadCredentials } from "../../api/marketData/localReadCredentials";

/** One disposable workspace presentation-intent owner; never scientific persistence. */
export function ChartStudies({
    context,
    children,
    credentials
}: {
    readonly context: ChartStudyContext | null;
    readonly credentials?: LocalReadCredentials;
    readonly children?: (state: {
        readonly instances: readonly ChartStudyInstance[];
        readonly selectedId: string | null;
        readonly incarnationKey: string;
        readonly onTransientRevalidated: (
            capability: ChartStudyCapability,
            instanceIds: readonly string[]
        ) => void;
    }) => ReactNode;
}) {
    const [draft, setDraft] = useState<ChartCalculationDraft | null>(null);
    const [instances, setInstances] = useState<readonly ChartStudyInstance[]>([]);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [incarnationKey, setIncarnationKey] = useState(createUuidV4);
    const [contextKey, setContextKey] = useState(context?.key ?? null);
    const [editing, setEditing] = useState<ChartStudyInstance | null>(null);
    const [returnFocus, setReturnFocus] = useState<HTMLElement | null>(null);
    // Retain intent, but each context occurrence gets a fresh numeric/request owner.
    if (contextKey !== (context?.key ?? null)) {
        setContextKey(context?.key ?? null);
        setIncarnationKey(createUuidV4());
        setDraft(null);
        setEditing(null);
        if (context !== null)
            setInstances((previous) => previous.map((instance) => ({ ...instance, context })));
    }
    const onTransientRevalidated = useCallback(
        (capability: ChartStudyCapability, instanceIds: readonly string[]) => {
            const admitted = new Set(instanceIds);
            setInstances((previous) =>
                previous.map((instance) =>
                    instance.selection.source === "CHART_STUDY_TRANSIENT" &&
                    instance.connectionState === "STALE_CONFIG" &&
                    admitted.has(instance.instanceId)
                        ? {
                              ...instance,
                              selection: { source: "CHART_STUDY_TRANSIENT", capability },
                              connectionState: "CONFIGURED_NOT_EXECUTED"
                          }
                        : instance
                )
            );
        },
        []
    );
    const changeDraft = useCallback(
        (next: ChartCalculationDraft | null, trigger: HTMLElement | null) => {
            setEditing(null);
            setDraft(next);
            if (next !== null) {
                setReturnFocus(trigger);
            }
        },
        []
    );
    useEffect(() => {
        const invalidate = () => {
            setDraft(null);
            setEditing(null);
            setIncarnationKey(createUuidV4());
            // Focus is a re-observation boundary, not a cached validity/TTL claim.
            setInstances((previous) =>
                previous.map((instance) => ({ ...instance, connectionState: "STALE_CONFIG" }))
            );
        };
        window.addEventListener("focus", invalidate);
        const unsubscribe = credentials?.subscribe(invalidate);
        return () => {
            window.removeEventListener("focus", invalidate);
            unsubscribe?.();
        };
    }, [credentials]);
    return (
        <>
            <section className="chart-studies" aria-label="图表配置实例">
                <div className="chart-studies__toolbar">
                    <CalculationPicker
                        draft={draft}
                        onDraftChange={changeDraft}
                        {...(credentials === undefined ? {} : { credentials })}
                    />
                </div>
                {instances.length === 0 ? null : (
                    <ul className="chart-studies__list">
                        {instances.map((instance) => {
                            const descriptor = studyDescriptor(instance.selection);
                            return (
                                <li
                                    key={instance.instanceId}
                                    data-testid="chart-study-instance"
                                    data-instance-id={instance.instanceId}
                                    data-chart-context-key={instance.context.key}
                                    data-registration-source={instance.selection.source}
                                    data-connection-state={instance.connectionState}
                                    data-configuration={JSON.stringify(instance.configuration)}
                                    data-presentation={JSON.stringify(instance.presentation)}
                                    data-selected={selectedId === instance.instanceId}
                                >
                                    <span
                                        className="study-color"
                                        style={{
                                            backgroundColor: instance.presentation.color,
                                            opacity: instance.presentation.opacity
                                        }}
                                        aria-hidden="true"
                                    />
                                    <button
                                        type="button"
                                        aria-pressed={selectedId === instance.instanceId}
                                        aria-label={`选择 ${studyName(instance.selection)}`}
                                        onClick={() => {
                                            setSelectedId(instance.instanceId);
                                        }}
                                    >
                                        {studyDisplayLabel(instance)}
                                    </button>
                                    <button
                                        type="button"
                                        aria-pressed={instance.presentation.visible}
                                        onClick={() => {
                                            setInstances((previous) =>
                                                previous.map((row) =>
                                                    row.instanceId === instance.instanceId
                                                        ? {
                                                              ...row,
                                                              presentation: {
                                                                  ...row.presentation,
                                                                  visible: !row.presentation.visible
                                                              }
                                                          }
                                                        : row
                                                )
                                            );
                                        }}
                                    >
                                        {instance.presentation.visible ? "隐藏" : "显示"}{" "}
                                        {studyName(instance.selection)}
                                    </button>
                                    {instance.connectionState === "STALE_CONFIG" ? (
                                        <span>
                                            配置已过期；
                                            {instance.selection.source === "CHART_STUDY_TRANSIENT"
                                                ? "正在重新验证"
                                                : "需重新验证"}
                                        </span>
                                    ) : instance.selection.source !== "CHART_STUDY_TRANSIENT" ? (
                                        <span>已配置，尚未接入后端计算</span>
                                    ) : null}
                                    <details className="chart-studies__details">
                                        <summary
                                            aria-label={`配置详情 ${studyName(instance.selection)}`}
                                        >
                                            详情
                                        </summary>
                                        <p>
                                            {descriptor.typeId} · {descriptor.semanticVersion}
                                        </p>
                                        <p>
                                            {Object.entries(instance.configuration.parameters)
                                                .map(
                                                    ([name, value]) =>
                                                        `${name}=${String(value.value)}`
                                                )
                                                .join(" · ")}{" "}
                                            → {instance.configuration.outputNames.join(", ")}
                                        </p>
                                        <p>
                                            {instance.presentation.placement === "PRICE_OVERLAY"
                                                ? "主图 Overlay"
                                                : "独立 Pane"}{" "}
                                            · {studyColorName(instance.presentation.color)} ·{" "}
                                            {instance.presentation.lineWidth}px ·{" "}
                                            {instance.presentation.opacity} ·{" "}
                                            {instance.presentation.visible
                                                ? "显示偏好"
                                                : "隐藏偏好"}
                                        </p>
                                    </details>
                                    <button
                                        type="button"
                                        onClick={(event) => {
                                            setReturnFocus(event.currentTarget);
                                            setEditing(instance);
                                            setDraft(instance.selection);
                                        }}
                                    >
                                        编辑 {studyName(instance.selection)}
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            if (selectedId === instance.instanceId)
                                                setSelectedId(null);
                                            setInstances((previous) =>
                                                previous.filter(
                                                    (row) => row.instanceId !== instance.instanceId
                                                )
                                            );
                                        }}
                                    >
                                        移除配置
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                )}
                {draft === null ? null : (
                    <ChartStudyEditor
                        selection={draft}
                        {...(credentials === undefined ? {} : { credentials })}
                        instance={editing}
                        hasContext={context !== null}
                        returnFocus={returnFocus}
                        onCancel={() => {
                            setDraft(null);
                            setEditing(null);
                        }}
                        onStale={() => {
                            if (editing?.selection.source === "CHART_STUDY_TRANSIENT")
                                setIncarnationKey(createUuidV4());
                            if (editing !== null)
                                setInstances((previous) =>
                                    previous.map((instance) =>
                                        instance.instanceId === editing.instanceId
                                            ? { ...instance, connectionState: "STALE_CONFIG" }
                                            : instance
                                    )
                                );
                        }}
                        onConfirm={(configuration, presentation) => {
                            if (context === null) return;
                            const instance: ChartStudyInstance = {
                                instanceId: editing?.instanceId ?? createUuidV4(),
                                context,
                                selection: draft,
                                configuration,
                                presentation,
                                connectionState: "CONFIGURED_NOT_EXECUTED"
                            };
                            setInstances((previous) =>
                                editing === null
                                    ? [...previous, instance]
                                    : previous.map((row) =>
                                          row.instanceId === instance.instanceId ? instance : row
                                      )
                            );
                            setDraft(null);
                            setEditing(null);
                        }}
                    />
                )}
            </section>
            {children?.({ instances, selectedId, incarnationKey, onTransientRevalidated })}
        </>
    );
}
