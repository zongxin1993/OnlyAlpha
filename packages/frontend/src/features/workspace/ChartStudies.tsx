import { createPortal } from "react-dom";
import type { WorkspaceStudy } from "../../api/workspace/client";
import { readChartStudyCapabilities } from "../../api/chartStudies/client";
import { workspaceStudyIntent } from "./workspaceIntent";
import {
    studyScalar,
    configurationErrors,
    transientConfigurationErrors,
    validPresentation
} from "./chartStudy";
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
    credentials,
    restoration,
    toolbarTarget
}: {
    readonly toolbarTarget?: HTMLElement | null;
    readonly restoration?: {
        readonly key: string;
        readonly contextKey: string;
        readonly studies: readonly WorkspaceStudy[];
    } | null;
    readonly context: ChartStudyContext | null;
    readonly credentials?: LocalReadCredentials;
    readonly children?: (state: {
        readonly instances: readonly ChartStudyInstance[];
        readonly configurationIntents: readonly WorkspaceStudy[];
        readonly configurationReady: boolean;
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
    const [initializedRestore, setInitializedRestore] = useState<string | null>(null);
    const [pendingRestore, setPendingRestore] = useState<readonly WorkspaceStudy[] | null>(null);
    const [restoreError, setRestoreError] = useState<string | null>(null);
    const [restoreRetry, setRestoreRetry] = useState(0);
    if (restoration != null && restoration.key !== initializedRestore) {
        setInitializedRestore(restoration.key);
        setInstances([]);
        setSelectedId(null);
        setDraft(null);
        setEditing(null);
        setIncarnationKey(createUuidV4());
        setPendingRestore(restoration.studies.length === 0 ? null : restoration.studies);
        setRestoreError(null);
    }
    useEffect(() => {
        if (pendingRestore === null) return;
        if (context === null || context.key !== restoration?.contextKey) return;
        const controller = new AbortController();
        void (async () => {
            if (credentials === undefined) throw new Error("需要当前正式会话");
            const capabilities = await readChartStudyCapabilities(credentials, controller.signal);
            const restored = pendingRestore.map((saved): ChartStudyInstance => {
                const capability = capabilities.find(
                    (row) =>
                        row.kind === saved.kind &&
                        row.type_id === saved.type_id &&
                        row.semantic_version === saved.semantic_version
                );
                if (capability === undefined) throw new Error("精确指标版本不可用");
                const selection = { source: "CHART_STUDY_TRANSIENT" as const, capability };
                const configuration = {
                    parameters: Object.fromEntries(
                        Object.entries(saved.parameters).map(([name, value]) => [
                            name,
                            studyScalar(value)
                        ])
                    ),
                    outputNames: saved.output_names
                };
                if (!["PRICE_OVERLAY", "SEPARATE_PANE"].includes(saved.presentation.placement))
                    throw new Error("Pane 配置无效");
                const presentation = {
                    placement: saved.presentation.placement as "PRICE_OVERLAY" | "SEPARATE_PANE",
                    color: saved.presentation.color,
                    lineWidth: saved.presentation.line_width,
                    opacity: saved.presentation.opacity,
                    visible: saved.presentation.visible,
                    seriesStyles: saved.presentation.series_styles
                };
                const descriptor = studyDescriptor(selection);
                if (
                    configurationErrors(descriptor, configuration).length > 0 ||
                    transientConfigurationErrors(capability, configuration).length > 0 ||
                    !validPresentation(presentation) ||
                    Object.keys(presentation.seriesStyles).some(
                        (name) => !descriptor.outputs.some((output) => output.name === name)
                    )
                )
                    throw new Error("保存配置不再被精确版本支持");
                return {
                    instanceId: createUuidV4(),
                    context,
                    selection,
                    configuration,
                    presentation,
                    connectionState: "CONFIGURED_NOT_EXECUTED"
                };
            });
            if (controller.signal.aborted) return;
            setInstances(restored);
            setPendingRestore(null);
            setRestoreError(null);
        })().catch(() => {
            if (!controller.signal.aborted)
                setRestoreError("保存的指标配置暂不可用；请重试或明确移除，不会替换版本。");
        });
        return () => {
            controller.abort();
        };
    }, [context, credentials, pendingRestore, restoration?.contextKey, restoreRetry]);
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
    const picker = (
        <div className="chart-studies__toolbar" inert={pendingRestore !== null}>
            <CalculationPicker
                draft={draft}
                onDraftChange={changeDraft}
                {...(credentials === undefined ? {} : { credentials })}
            />
        </div>
    );
    return (
        <>
            <section className="chart-studies" aria-label="图表配置实例">
                {toolbarTarget === undefined
                    ? picker
                    : toolbarTarget === null
                      ? null
                      : createPortal(picker, toolbarTarget)}
                {pendingRestore === null ? null : (
                    <section aria-label="待恢复指标配置">
                        <p role="status">
                            {context?.key !== restoration?.contextKey
                                ? "保存的指标配置等待原行情上下文恢复；也可明确移除配置。"
                                : (restoreError ?? "正在验证保存的指标配置…")}
                        </p>
                        <ol>
                            {pendingRestore.map((saved, index) => (
                                <li
                                    key={`${String(index)}:${saved.type_id}:${saved.semantic_version}`}
                                >
                                    {saved.type_id} · {saved.semantic_version}
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setRestoreError(null);
                                            setPendingRestore((previous) => {
                                                if (previous === null) return null;
                                                const next = previous.filter((_, i) => i !== index);
                                                return next.length === 0 ? null : next;
                                            });
                                        }}
                                    >
                                        移除此保存配置
                                    </button>
                                </li>
                            ))}
                        </ol>
                        <button
                            type="button"
                            onClick={() => {
                                setRestoreError(null);
                                setRestoreRetry((value) => value + 1);
                            }}
                        >
                            重试恢复指标配置
                        </button>
                    </section>
                )}
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
            {children?.({
                instances,
                selectedId,
                incarnationKey,
                onTransientRevalidated,
                configurationIntents: pendingRestore ?? instances.map(workspaceStudyIntent),
                configurationReady: pendingRestore === null
            })}
        </>
    );
}
