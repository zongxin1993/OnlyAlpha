import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
    ChartCatalogError,
    readActiveRuntime,
    readChartCatalog,
    type ChartCatalog,
    type ChartCatalogEntry,
    type ChartCalculationDraft
} from "../../api/research/chartCatalog";
import { WorkspaceIcon } from "../../shared/components/WorkspaceIcon";
import "./calculationPicker.css";

type Category = "INDICATOR" | "FACTOR";
type CatalogState =
    | { readonly status: "idle" }
    | { readonly status: "loading" }
    | { readonly status: "ready"; readonly catalog: ChartCatalog }
    | { readonly status: "error"; readonly error: ChartCatalogError["code"] };
const messages: Record<ChartCatalogError["code"], string> = {
    NO_RUNTIME: "没有可用于新工作的 Runtime Generation；目录未接入。",
    MISSING_CATALOG: "绑定的精确 Catalog 不存在；目录未接入。",
    STALE: "Runtime Generation 已切换；旧目录与选择已失效，请刷新目录。",
    INVALID: "目录身份或契约验证失败；不可选择。",
    TRANSPORT: "目录请求失败或正式服务不可用；不可选择。"
};
const label = (entry: ChartCatalogEntry) =>
    entry.capability.type_id.split(".").at(-1)?.toUpperCase() ?? entry.capability.type_id;

/** Catalog navigation only. No Study, numeric execution or market-data side effects. */
export function CalculationPicker() {
    const [category, setCategory] = useState<Category | null>(null);
    const [state, setState] = useState<CatalogState>({ status: "idle" });
    const [draft, setDraft] = useState<ChartCalculationDraft | null>(null);
    const [selecting, setSelecting] = useState(false);
    const request = useRef<AbortController | null>(null);

    const refresh = useCallback(async () => {
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        setDraft(null);
        setSelecting(false);
        setState({ status: "loading" });
        try {
            const catalog = await readChartCatalog(controller.signal);
            if (request.current === controller && !controller.signal.aborted)
                setState({ status: "ready", catalog });
        } catch (error) {
            if (request.current === controller && !controller.signal.aborted)
                setState({
                    status: "error",
                    error: error instanceof ChartCatalogError ? error.code : "INVALID"
                });
        }
    }, []);

    useEffect(
        () => () => {
            request.current?.abort();
        },
        []
    );
    useEffect(() => {
        // Observe canonical identity again on return, not a timer/TTL-based claim.
        if (category === null && draft === null) return;
        const onFocus = () => {
            void refresh();
        };
        window.addEventListener("focus", onFocus);
        return () => {
            window.removeEventListener("focus", onFocus);
        };
    }, [category, draft, refresh]);

    function close() {
        request.current?.abort();
        setCategory(null);
        setSelecting(false);
    }
    async function select(entry: ChartCatalogEntry) {
        if (state.status !== "ready" || entry.availability !== "AVAILABLE") return;
        const catalog = state.catalog;
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        setSelecting(true);
        try {
            const active = await readActiveRuntime(controller.signal);
            if (controller.signal.aborted || request.current !== controller) return;
            if (active !== catalog.runtimeGenerationFingerprint)
                throw new ChartCatalogError("STALE");
            setDraft({ catalog, entry });
            close();
        } catch (error) {
            if (!controller.signal.aborted && request.current === controller) {
                setDraft(null);
                setSelecting(false);
                setState({
                    status: "error",
                    error: error instanceof ChartCatalogError ? error.code : "INVALID"
                });
            }
        }
    }

    return (
        <>
            {(["INDICATOR", "FACTOR"] as const).map((value) => (
                <button
                    key={value}
                    type="button"
                    className="picker__trigger"
                    aria-haspopup="dialog"
                    onClick={() => {
                        setCategory(value);
                        void refresh();
                    }}
                >
                    <WorkspaceIcon name="results" />
                    <span>{value === "INDICATOR" ? "指标" : "因子"}</span>
                </button>
            ))}
            {draft === null ? null : (
                <span
                    className="calculation-handoff"
                    role="status"
                    data-testid="calculation-handoff"
                    data-runtime-generation={draft.catalog.runtimeGenerationFingerprint}
                    data-catalog-generation={draft.catalog.catalogGenerationFingerprint}
                    data-kind={draft.entry.capability.kind}
                    data-type-id={draft.entry.capability.type_id}
                    data-semantic-version={draft.entry.capability.semantic_version}
                    data-backend={draft.entry.capability.backend}
                    data-implementation={draft.entry.capability.implementation_fingerprint}
                    data-readiness-capability={draft.entry.readiness?.capability_fingerprint}
                >
                    已选择 {label(draft.entry)} · {draft.entry.capability.semantic_version} ·{" "}
                    {draft.entry.capability.backend}； 仅配置草稿，尚未计算
                </span>
            )}
            {category === null ? null : (
                <CatalogDialog
                    category={category}
                    state={state}
                    selecting={selecting}
                    onClose={close}
                    onRefresh={() => {
                        void refresh();
                    }}
                    onSelect={(entry) => {
                        void select(entry);
                    }}
                />
            )}
        </>
    );
}

function CatalogDialog({
    category,
    state,
    selecting,
    onClose,
    onRefresh,
    onSelect
}: {
    readonly category: Category;
    readonly state: CatalogState;
    readonly selecting: boolean;
    readonly onClose: () => void;
    readonly onRefresh: () => void;
    readonly onSelect: (entry: ChartCatalogEntry) => void;
}) {
    const dialog = useRef<HTMLDialogElement>(null);
    const search = useRef<HTMLInputElement>(null);
    const [query, setQuery] = useState("");
    useEffect(() => {
        const node = dialog.current;
        const trigger =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
        node?.showModal();
        search.current?.focus();
        return () => {
            node?.close();
            trigger?.focus();
        };
    }, []);
    const entries =
        state.status === "ready"
            ? state.catalog.entries.filter(
                  (entry) =>
                      entry.capability.kind === category &&
                      `${label(entry)} ${entry.capability.type_id}`
                          .toLowerCase()
                          .includes(query.trim().toLowerCase())
              )
            : [];
    return createPortal(
        <dialog
            ref={dialog}
            className="calculation-picker"
            aria-label="指标 / 因子目录"
            onKeyDown={(event) => {
                if (event.key !== "Tab") return;
                // Native modal inertness protects the background, but Chromium can
                // move edge traversal into browser chrome. Keep the keyboard loop
                // inside the current, visible and enabled dialog controls.
                const controls = [
                    ...event.currentTarget.querySelectorAll<HTMLElement>(
                        'button:not([disabled]), input:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
                    )
                ].filter((element) => element.getClientRects().length > 0);
                const first = controls[0];
                const last = controls.at(-1);
                if (first === undefined || last === undefined) return;
                if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                }
            }}
            onCancel={(event) => {
                event.preventDefault();
                onClose();
            }}
        >
            <header>
                <h2>{category === "INDICATOR" ? "指标" : "因子"}目录</h2>
                <button type="button" aria-label="关闭目录" onClick={onClose}>
                    关闭
                </button>
            </header>
            <p>正式 Catalog 元数据 · 选择不启动计算，不改变行情。</p>
            <div className="calculation-picker__search">
                <input
                    ref={search}
                    type="search"
                    aria-label="搜索指标或因子"
                    placeholder="名称 / type_id"
                    value={query}
                    onChange={(event) => {
                        setQuery(event.target.value);
                    }}
                />
                <button
                    type="button"
                    onClick={onRefresh}
                    disabled={state.status === "loading" || selecting}
                >
                    刷新目录
                </button>
            </div>
            {state.status === "loading" || state.status === "idle" ? (
                <p role="status">正在读取精确目录…</p>
            ) : state.status === "error" ? (
                <p role="alert">{messages[state.error]}</p>
            ) : (
                <>
                    <details className="calculation-picker__identity">
                        <summary>精确目录身份</summary>
                        <p>Runtime：{state.catalog.runtimeGenerationFingerprint}</p>
                        <p>Catalog：{state.catalog.catalogGenerationFingerprint}</p>
                        <p>Projection：{state.catalog.projectionFingerprint}</p>
                    </details>
                    {entries.length === 0 ? (
                        <p role="status">
                            {query.trim() === ""
                                ? "当前目录没有此类注册项。"
                                : "没有匹配的注册项。"}
                        </p>
                    ) : (
                        <ul className="calculation-picker__entries">
                            {entries.map((entry) => (
                                <li
                                    key={JSON.stringify([
                                        entry.capability.kind,
                                        entry.capability.type_id,
                                        entry.capability.semantic_version,
                                        entry.capability.backend
                                    ])}
                                >
                                    <h3>{label(entry)}</h3>
                                    <p className="value">
                                        {entry.capability.kind} / {entry.capability.type_id}@
                                        {entry.capability.semantic_version}
                                    </p>
                                    <p>
                                        {entry.capability.backend} ·{" "}
                                        {entry.capability.type_descriptor.execution_shape} ·{" "}
                                        {entry.availability}
                                    </p>
                                    <p>
                                        Readiness：
                                        {entry.readiness === null
                                            ? "未接入"
                                            : entry.readiness.readiness_contract_versions.join(
                                                  ", "
                                              ) || "不支持"}
                                    </p>
                                    <p>
                                        Provider：{entry.capability.provider_id}@
                                        {entry.capability.provider_version}
                                    </p>
                                    <dl>
                                        {entry.capability.type_descriptor.parameters.map(
                                            (parameter) => (
                                                <div key={parameter.name}>
                                                    <dt>
                                                        {parameter.name} ·{" "}
                                                        {parameter.parameter_type}
                                                    </dt>
                                                    <dd>
                                                        {parameter.default === null
                                                            ? "无默认值"
                                                            : `默认 ${String(parameter.default)}`}
                                                        {parameter.required ? " · 必填" : ""}
                                                    </dd>
                                                </div>
                                            )
                                        )}
                                    </dl>
                                    <p>
                                        输出：
                                        {entry.capability.type_descriptor.outputs
                                            .map(
                                                (output) =>
                                                    `${output.name} (${output.semantic_type})`
                                            )
                                            .join(" · ")}
                                    </p>
                                    <button
                                        type="button"
                                        disabled={entry.availability !== "AVAILABLE" || selecting}
                                        onClick={() => {
                                            onSelect(entry);
                                        }}
                                    >
                                        选择 {label(entry)} · {entry.capability.backend}
                                    </button>
                                    <p>
                                        {entry.availability === "AVAILABLE"
                                            ? "可进入下一步配置；不是执行许可或数值就绪证明。"
                                            : entry.availability === "NOT_CONNECTED"
                                              ? "缺少精确 readiness 证明，不可选择。"
                                              : "当前后端、计算形状或 readiness 版本不支持此配置入口。"}
                                    </p>
                                </li>
                            ))}
                        </ul>
                    )}
                </>
            )}
        </dialog>,
        document.body
    );
}
