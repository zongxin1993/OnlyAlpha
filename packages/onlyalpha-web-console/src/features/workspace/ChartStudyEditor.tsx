import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
    ChartCatalogError,
    verifyChartCalculationDraft,
    type ChartCalculationDraft
} from "../../api/research/chartCatalog";
import { CalculationSelectionSummary } from "./CalculationPicker";
import { keepDialogFocus } from "./dialogFocus";
import {
    configurationErrors,
    parameterTextInput,
    studyDescriptor,
    validPresentation,
    type ChartStudyInstance,
    type StudyConfiguration,
    type StudyDescriptor,
    type StudyParameter,
    type StudyPresentation
} from "./chartStudy";
import "./chartStudy.css";

function metadata(
    selection: ChartCalculationDraft
): { descriptor: StudyDescriptor; error: null } | { descriptor: null; error: string } {
    try {
        return { descriptor: studyDescriptor(selection), error: null };
    } catch (error) {
        return {
            descriptor: null,
            error: error instanceof Error ? error.message : "无效 Descriptor"
        };
    }
}
function defaultPresentation(): StudyPresentation {
    const token = getComputedStyle(document.documentElement)
        .getPropertyValue("--accent-solid")
        .trim();
    return { placement: "PRICE_OVERLAY", color: token, lineWidth: 2, opacity: 1, visible: true };
}

export function ChartStudyEditor({
    selection,
    instance,
    hasContext,
    returnFocus,
    onCancel,
    onConfirm,
    onStale
}: {
    readonly selection: ChartCalculationDraft;
    readonly instance: ChartStudyInstance | null;
    readonly hasContext: boolean;
    readonly returnFocus: HTMLElement | null;
    readonly onCancel: () => void;
    readonly onConfirm: (
        configuration: StudyConfiguration,
        presentation: StudyPresentation
    ) => void;
    readonly onStale: () => void;
}) {
    const [source] = useState(() => metadata(selection));
    const [configuration, setConfiguration] = useState<StudyConfiguration>(
        () =>
            instance?.configuration ?? {
                parameters: Object.fromEntries(
                    source.descriptor?.parameters.map((p) => [p.name, p.default]) ?? []
                ),
                outputName:
                    source.descriptor?.outputs.length === 1
                        ? (source.descriptor.outputs[0]?.name ?? "")
                        : ""
            }
    );
    const [presentation, setPresentation] = useState<StudyPresentation>(
        () => instance?.presentation ?? defaultPresentation()
    );
    const [status, setStatus] = useState<"editing" | "checking" | "stale">("editing");
    const [error, setError] = useState<string | null>(null);
    const dialog = useRef<HTMLDialogElement>(null);
    const request = useRef<AbortController | null>(null);
    const metadataError = source.error;
    const errors =
        source.descriptor === null ? [] : configurationErrors(source.descriptor, configuration);
    const canConfirm =
        metadataError === null &&
        errors.length === 0 &&
        validPresentation(presentation) &&
        hasContext &&
        status === "editing";
    useEffect(() => {
        const node = dialog.current;
        node?.showModal();
        node?.querySelector<HTMLElement>("input, select, button")?.focus();
        return () => {
            request.current?.abort();
            node?.close();
            if (returnFocus?.isConnected) returnFocus.focus();
        };
    }, [returnFocus]);

    async function confirm() {
        if (!canConfirm) return;
        const controller = new AbortController();
        request.current?.abort();
        request.current = controller;
        setStatus("checking");
        try {
            await verifyChartCalculationDraft(selection, controller.signal);
            if (!controller.signal.aborted && request.current === controller)
                onConfirm(configuration, presentation);
        } catch (failure) {
            if (controller.signal.aborted || request.current !== controller) return;
            setStatus("stale");
            setError(
                `配置未提交：${failure instanceof ChartCatalogError ? failure.code : "INVALID"}；元数据不可验证，请取消并重新选择。`
            );
            onStale();
        }
    }
    function parameterField(parameter: StudyParameter) {
        const current = configuration.parameters[parameter.name];
        const value = current?.value;
        const updateText = (text: string) => {
            setConfiguration((previous) => ({
                ...previous,
                parameters: {
                    ...previous.parameters,
                    [parameter.name]: parameterTextInput(parameter, text)
                }
            }));
        };
        if (parameter.type === "BOOLEAN" && parameter.default.type !== "NULL")
            if (typeof value === "boolean")
                return (
                    <input
                        type="checkbox"
                        aria-label={parameter.name}
                        checked={value}
                        onChange={(event) => {
                            const checked = event.target.checked;
                            setConfiguration((previous) => ({
                                ...previous,
                                parameters: {
                                    ...previous.parameters,
                                    [parameter.name]: { type: "BOOLEAN", value: checked }
                                }
                            }));
                        }}
                    />
                );
        // A NULL-default BOOLEAN keeps its explicit choice control after selection,
        // rather than replacing the focused element with a checkbox.
        if (parameter.type === "BOOLEAN")
            return (
                <select
                    aria-label={parameter.name}
                    value={typeof value === "boolean" ? String(value) : ""}
                    onChange={(event) => {
                        const next = event.target.value;
                        setConfiguration((previous) => ({
                            ...previous,
                            parameters: {
                                ...previous.parameters,
                                [parameter.name]:
                                    next === ""
                                        ? { type: "NULL", value: null }
                                        : { type: "BOOLEAN", value: next === "true" }
                            }
                        }));
                    }}
                >
                    <option value="">必填 / 无默认值</option>
                    <option value="true">true</option>
                    <option value="false">false</option>
                </select>
            );
        if (parameter.enumValues.length > 0)
            return (
                <select
                    aria-label={parameter.name}
                    value={value === null || value === undefined ? "" : String(value)}
                    onChange={(event) => {
                        const choice = parameter.enumValues.find(
                            (candidate) => String(candidate.value) === event.target.value
                        );
                        setConfiguration((previous) => ({
                            ...previous,
                            parameters: {
                                ...previous.parameters,
                                [parameter.name]: choice ?? { type: "NULL", value: null }
                            }
                        }));
                    }}
                >
                    <option value="">请选择官方 enum</option>
                    {value === null ||
                    value === undefined ||
                    parameter.enumValues.some(
                        (candidate) => String(candidate.value) === String(value)
                    ) ? null : (
                        <option value={String(value)}>
                            {String(value)} · 原始默认输入（匹配官方 enum）
                        </option>
                    )}
                    {parameter.enumValues.map((candidate, index) => (
                        <option key={index} value={String(candidate.value)}>
                            {String(candidate.value)}
                        </option>
                    ))}
                </select>
            );
        return (
            <input
                aria-label={parameter.name}
                type="text"
                inputMode={
                    parameter.type === "INTEGER"
                        ? "numeric"
                        : parameter.type === "DECIMAL"
                          ? "decimal"
                          : "text"
                }
                maxLength={4096}
                value={value === null || value === undefined ? "" : String(value)}
                onChange={(event) => {
                    updateText(event.target.value);
                }}
            />
        );
    }
    return createPortal(
        <dialog
            ref={dialog}
            className="calculation-picker chart-study-editor"
            aria-label="指标 / 因子参数配置"
            onCancel={(event) => {
                event.preventDefault();
                onCancel();
            }}
            onKeyDown={keepDialogFocus}
        >
            <header>
                <h2>{instance === null ? "添加配置" : "编辑配置"}</h2>
                <button type="button" aria-label="取消配置" onClick={onCancel}>
                    取消
                </button>
            </header>
            <CalculationSelectionSummary draft={selection} />
            <p>仅 UI 输入形状校验；不是 Core normalization、执行准入或数值 READY。</p>
            {selection.source === "EXACT_CATALOG" ? (
                <details>
                    <summary>精确元数据身份（不是计算结果）</summary>
                    <p>Runtime：{selection.catalog.runtimeGenerationFingerprint}</p>
                    <p>Catalog：{selection.catalog.catalogGenerationFingerprint}</p>
                    <p>Implementation：{selection.entry.capability.implementation_fingerprint}</p>
                    <p>Readiness capability：{selection.entry.readiness?.capability_fingerprint}</p>
                </details>
            ) : (
                <p>REGISTERED_DISCOVERY · 已登记 / 执行未连接</p>
            )}
            {metadataError === null ? null : (
                <p role="alert">Descriptor 不可配置：{metadataError}</p>
            )}
            <form
                noValidate
                onSubmit={(event) => {
                    event.preventDefault();
                    void confirm();
                }}
            >
                <fieldset disabled={status !== "editing" || metadataError !== null}>
                    <legend>计算输入意图</legend>
                    {source.descriptor?.parameters.map((parameter) => (
                        <label key={parameter.name}>
                            <span>
                                {parameter.name} · {parameter.type}
                                {parameter.required ? " · 必填" : ""}
                            </span>
                            {parameterField(parameter)}
                            <small>
                                默认{" "}
                                {parameter.default.type === "NULL"
                                    ? "无默认值"
                                    : String(parameter.default.value)}
                                {parameter.minimum === null
                                    ? ""
                                    : ` · minimum ${String(parameter.minimum.value)}`}
                                {parameter.maximum === null
                                    ? ""
                                    : ` · maximum ${String(parameter.maximum.value)}`}
                                {parameter.uppercase
                                    ? " · uppercase（Core 元数据；不在浏览器归一化）"
                                    : ""}
                            </small>
                        </label>
                    ))}
                    <label>
                        <span>输出</span>
                        <select
                            aria-label="输出"
                            value={configuration.outputName}
                            onChange={(event) => {
                                setConfiguration((previous) => ({
                                    ...previous,
                                    outputName: event.target.value
                                }));
                            }}
                        >
                            <option value="">请选择官方 output</option>
                            {source.descriptor?.outputs.map((output) => (
                                <option key={output.name} value={output.name}>
                                    {output.name} · {output.semantic_type}
                                </option>
                            ))}
                        </select>
                    </label>
                </fieldset>
                <fieldset disabled={status !== "editing"}>
                    <legend>显示偏好（尚不绘制）</legend>
                    <label>
                        <span>位置</span>
                        <select
                            aria-label="位置"
                            value={presentation.placement}
                            onChange={(event) => {
                                const placement = event.target.value;
                                if (placement === "PRICE_OVERLAY" || placement === "SEPARATE_PANE")
                                    setPresentation((previous) => ({ ...previous, placement }));
                            }}
                        >
                            <option value="PRICE_OVERLAY">主图 Overlay</option>
                            <option value="SEPARATE_PANE">独立 Pane</option>
                        </select>
                    </label>
                    <label>
                        <span>颜色</span>
                        <input
                            aria-label="颜色"
                            type="text"
                            placeholder="#RRGGBB"
                            value={presentation.color}
                            onChange={(event) => {
                                setPresentation((previous) => ({
                                    ...previous,
                                    color: event.target.value
                                }));
                            }}
                        />
                    </label>
                    <label>
                        <span>线宽（1–5）</span>
                        <input
                            aria-label="线宽"
                            type="number"
                            min="1"
                            max="5"
                            step="0.5"
                            value={
                                Number.isNaN(presentation.lineWidth) ? "" : presentation.lineWidth
                            }
                            onChange={(event) => {
                                setPresentation((previous) => ({
                                    ...previous,
                                    lineWidth:
                                        event.target.value === "" ? NaN : Number(event.target.value)
                                }));
                            }}
                        />
                    </label>
                    <label>
                        <span>透明度（0–1）</span>
                        <input
                            aria-label="透明度"
                            type="number"
                            min="0"
                            max="1"
                            step="0.05"
                            value={Number.isNaN(presentation.opacity) ? "" : presentation.opacity}
                            onChange={(event) => {
                                setPresentation((previous) => ({
                                    ...previous,
                                    opacity:
                                        event.target.value === "" ? NaN : Number(event.target.value)
                                }));
                            }}
                        />
                    </label>
                    <label className="study-visible">
                        <input
                            aria-label="显示"
                            type="checkbox"
                            checked={presentation.visible}
                            onChange={(event) => {
                                setPresentation((previous) => ({
                                    ...previous,
                                    visible: event.target.checked
                                }));
                            }}
                        />
                        显示（配置偏好）
                    </label>
                </fieldset>
                {errors.length === 0 ? null : <p role="alert">{errors.join("；")}</p>}
                {validPresentation(presentation) ? null : (
                    <p role="alert">显示偏好无效：颜色 #RRGGBB、线宽 1–5、透明度 0–1。</p>
                )}
                {hasContext ? null : (
                    <p role="alert">请先选择正式数据源、标的与 BarSemantic；当前不可添加。</p>
                )}
                {error === null ? null : <p role="alert">{error}</p>}
                {status === "checking" ? <p role="status">正在重新验证元数据…</p> : null}
                <footer>
                    <button type="button" onClick={onCancel}>
                        取消
                    </button>
                    <button type="submit" disabled={!canConfirm}>
                        {instance === null ? "添加" : "应用"}
                    </button>
                </footer>
            </form>
        </dialog>,
        document.body
    );
}
