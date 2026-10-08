import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { ChartCalculationDraft } from "../../api/research/chartCatalog";
import { CalculationPicker } from "./CalculationPicker";
import { ChartStudyEditor } from "./ChartStudyEditor";
import { studyDescriptor, type ChartStudyContext, type ChartStudyInstance } from "./chartStudy";
import "./chartStudy.css";

/** One context-keyed, disposable workspace state source; never scientific persistence. */
export function ChartStudies({
    context,
    children
}: {
    readonly context: ChartStudyContext | null;
    readonly children?: (state: {
        readonly instances: readonly ChartStudyInstance[];
        readonly selectedId: string | null;
        readonly incarnationKey: string;
    }) => ReactNode;
}) {
    const [draft, setDraft] = useState<ChartCalculationDraft | null>(null);
    const [instances, setInstances] = useState<readonly ChartStudyInstance[]>([]);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [incarnationKey] = useState(() => crypto.randomUUID());
    const [editing, setEditing] = useState<ChartStudyInstance | null>(null);
    const [returnFocus, setReturnFocus] = useState<HTMLElement | null>(null);
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
            // Focus is a re-observation boundary, not a cached validity/TTL claim.
            setInstances((previous) =>
                previous.map((instance) => ({ ...instance, connectionState: "STALE_CONFIG" }))
            );
        };
        window.addEventListener("focus", invalidate);
        return () => {
            window.removeEventListener("focus", invalidate);
        };
    }, []);
    return (
        <>
            <section className="chart-studies" aria-label="图表配置实例">
                <div className="chart-studies__toolbar">
                    <CalculationPicker draft={draft} onDraftChange={changeDraft} />
                    <span>会话内配置 · 尚未接入计算结果</span>
                </div>
                {instances.length === 0 ? (
                    <p className="chart-studies__empty">尚未添加配置实例</p>
                ) : (
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
                                        onClick={() => {
                                            setSelectedId(instance.instanceId);
                                        }}
                                    >
                                        选择 {descriptor.typeId.split(".").at(-1)?.toUpperCase()}
                                    </button>
                                    <strong>
                                        {descriptor.typeId.split(".").at(-1)?.toUpperCase()} ·{" "}
                                        {descriptor.semanticVersion}
                                    </strong>
                                    <span>
                                        {Object.entries(instance.configuration.parameters)
                                            .map(
                                                ([name, value]) => `${name}=${String(value.value)}`
                                            )
                                            .join(" · ")}{" "}
                                        → {instance.configuration.outputName}
                                    </span>
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
                                        {descriptor.typeId.split(".").at(-1)?.toUpperCase()}
                                    </button>
                                    <span>
                                        {instance.connectionState === "STALE_CONFIG"
                                            ? "配置已过期；需重新验证"
                                            : "已配置，尚未接入后端计算"}
                                    </span>
                                    <span>
                                        {instance.presentation.placement === "PRICE_OVERLAY"
                                            ? "主图 Overlay"
                                            : "独立 Pane"}{" "}
                                        · {instance.presentation.color} ·{" "}
                                        {instance.presentation.lineWidth}px ·{" "}
                                        {instance.presentation.opacity} ·{" "}
                                        {instance.presentation.visible ? "显示偏好" : "隐藏偏好"}
                                    </span>
                                    <button
                                        type="button"
                                        onClick={(event) => {
                                            setReturnFocus(event.currentTarget);
                                            setEditing(instance);
                                            setDraft(instance.selection);
                                        }}
                                    >
                                        编辑 {descriptor.typeId.split(".").at(-1)?.toUpperCase()}
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
                        instance={editing}
                        hasContext={context !== null}
                        returnFocus={returnFocus}
                        onCancel={() => {
                            setDraft(null);
                            setEditing(null);
                        }}
                        onStale={() => {
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
                                instanceId: editing?.instanceId ?? crypto.randomUUID(),
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
            {children?.({ instances, selectedId, incarnationKey })}
        </>
    );
}
