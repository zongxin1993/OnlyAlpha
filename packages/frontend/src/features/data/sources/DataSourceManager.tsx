import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AddDataSourceTab } from "./AddDataSourceTab";
import { ConfiguredSourcesTab } from "./ConfiguredSourcesTab";
import { DataSourceBindingTab } from "./DataSourceBindingTab";
import { DataSourceConfigurationView } from "./DataSourceConfigurationView";
import { DataSourceManagerBoundary } from "./DataSourceManagerBoundary";
import { useDataSourceOverview } from "./overview";
import "./dataSources.css";

export type DataSourceManagerTab = "configured" | "add" | "binding";

const tabLabels: Readonly<Record<DataSourceManagerTab, string>> = {
    configured: "已配置",
    add: "添加数据源",
    binding: "数据源绑定"
};

/**
 * One management surface shared by the Workspace Modal and the `/data/sources`
 * deep-link routes. Tab and detail selection stay in component state and never
 * mutate the URL.
 */
export function DataSourceManager({
    variant,
    initialTab = "configured",
    initialIntegrationId,
    onClose
}: {
    readonly variant: "modal" | "page";
    readonly initialTab?: DataSourceManagerTab;
    readonly initialIntegrationId?: string;
    readonly onClose?: (() => void) | undefined;
}) {
    const overview = useDataSourceOverview();
    const [tab, setTab] = useState<DataSourceManagerTab>(initialTab);
    const [openSource, setOpenSource] = useState(initialIntegrationId ?? "");
    const surface = useRef<HTMLDivElement>(null);
    const restoreFocus = useRef<HTMLElement | null>(null);

    useEffect(() => {
        if (variant !== "modal") return;
        restoreFocus.current =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
        // The dialog is portaled outside #root, so while it is open the application is
        // reachable only through the dialog.
        document.getElementById("root")?.setAttribute("inert", "");
        surface.current?.focus();
        return () => {
            document.getElementById("root")?.removeAttribute("inert");
            restoreFocus.current?.focus();
        };
    }, [variant]);

    useEffect(() => {
        if (variant !== "modal" || onClose === undefined) return;
        function onKey(event: KeyboardEvent) {
            if (event.key === "Escape") {
                onClose?.();
                return;
            }
            if (event.key !== "Tab") return;
            const node = surface.current;
            if (node === null) return;
            const focusable = [
                ...node.querySelectorAll<HTMLElement>(
                    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
                )
            ];
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (first === undefined || last === undefined) {
                event.preventDefault();
                node.focus();
                return;
            }
            const active = document.activeElement;
            if (event.shiftKey && (active === first || active === node)) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && active === last) {
                event.preventDefault();
                first.focus();
            }
        }
        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("keydown", onKey);
        };
    }, [variant, onClose]);

    const body =
        openSource !== "" ? (
            <DataSourceConfigurationView
                integrationId={openSource}
                onBack={() => {
                    setOpenSource("");
                }}
            />
        ) : tab === "configured" ? (
            <ConfiguredSourcesTab
                overview={overview}
                onOpenSource={setOpenSource}
                onAddSource={() => {
                    setTab("add");
                }}
            />
        ) : tab === "add" ? (
            <AddDataSourceTab
                overview={overview}
                onCreated={(integrationId) => {
                    setTab("configured");
                    setOpenSource(integrationId);
                }}
            />
        ) : (
            <DataSourceBindingTab sources={overview.sources} types={overview.types} />
        );

    const surfaceElement = (
        <div
            className="manager-surface"
            data-variant={variant}
            tabIndex={-1}
            ref={surface}
            role={variant === "modal" ? "dialog" : undefined}
            aria-modal={variant === "modal" ? true : undefined}
            aria-label={variant === "modal" ? "管理数据源" : undefined}
        >
            <header className="manager-surface__head">
                <h2>管理数据源</h2>
                {onClose === undefined ? null : (
                    <button type="button" className="button-subtle" onClick={onClose}>
                        关闭
                    </button>
                )}
            </header>
            {openSource === "" ? (
                <div className="manager-surface__tabs" role="tablist" aria-label="数据源管理视图">
                    {(Object.keys(tabLabels) as DataSourceManagerTab[]).map((key) => (
                        <button
                            key={key}
                            type="button"
                            role="tab"
                            id={`data-source-tab-${key}`}
                            aria-controls={`data-source-panel-${key}`}
                            aria-selected={tab === key}
                            tabIndex={tab === key ? 0 : -1}
                            className={
                                tab === key ? "manager-tab manager-tab--active" : "manager-tab"
                            }
                            onClick={() => {
                                setTab(key);
                            }}
                        >
                            {tabLabels[key]}
                            {key === "configured" ? (
                                <span className="manager-tab__count value">
                                    {overview.sources.length}
                                </span>
                            ) : null}
                        </button>
                    ))}
                </div>
            ) : (
                <div className="manager-surface__tabs">
                    <span className="manager-tab manager-tab--active">{tabLabels[tab]}</span>
                </div>
            )}
            <div
                className="manager-surface__body"
                role={openSource === "" ? "tabpanel" : undefined}
                id={openSource === "" ? `data-source-panel-${tab}` : undefined}
                aria-labelledby={openSource === "" ? `data-source-tab-${tab}` : undefined}
            >
                <DataSourceManagerBoundary>{body}</DataSourceManagerBoundary>
            </div>
        </div>
    );
    if (variant === "page") return surfaceElement;
    return createPortal(
        <div
            className="manager-overlay"
            role="presentation"
            onMouseDown={(event) => {
                if (event.target === event.currentTarget) onClose?.();
            }}
        >
            {surfaceElement}
        </div>,
        document.body
    );
}
