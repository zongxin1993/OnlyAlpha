import { useEffect, useRef, useState } from "react";
import { WorkspaceIcon } from "../../../shared/components/WorkspaceIcon";
import { CapabilityTags } from "./CapabilityTags";
import { ProviderIcon } from "./ProviderIcon";
import type { DataSourceOverview } from "./overview";
import { formatTimestamp, sourcePresentation } from "./status";
import "./dataSources.css";

/**
 * Workspace entry plus quick status Popover. It only reads formal Product API facts:
 * the Workspace source block stays an explicit gap placeholder until Source Binding
 * has canonical authority.
 */
export function DataSourceEntry({
    overview,
    onManage
}: {
    readonly overview: DataSourceOverview;
    readonly onManage: () => void;
}) {
    const [open, setOpen] = useState(false);
    const root = useRef<HTMLDivElement>(null);
    const trigger = useRef<HTMLButtonElement>(null);

    /**
     * The manager is a modal layer: dismiss the Popover and hand focus back to the entry
     * so the modal's focus restore has a live origin.
     */
    function openManager() {
        setOpen(false);
        trigger.current?.focus();
        onManage();
    }

    useEffect(() => {
        if (!open) return;
        function close(event: KeyboardEvent | MouseEvent) {
            if (event instanceof KeyboardEvent) {
                if (event.key === "Escape") setOpen(false);
                return;
            }
            if (root.current !== null && !root.current.contains(event.target as Node))
                setOpen(false);
        }
        document.addEventListener("keydown", close);
        document.addEventListener("mousedown", close);
        return () => {
            document.removeEventListener("keydown", close);
            document.removeEventListener("mousedown", close);
        };
    }, [open]);

    const { summary, operational, sources, types } = overview;
    const statusLabel = overview.failed ? "状态未知" : summary.countText;

    return (
        <div className="data-source-entry" ref={root}>
            <button
                type="button"
                ref={trigger}
                className={open ? "ds-trigger ds-trigger--open" : "ds-trigger"}
                aria-expanded={open}
                aria-haspopup="dialog"
                onClick={() => {
                    setOpen(!open);
                }}
            >
                <WorkspaceIcon name="database" />
                <span className="ds-trigger__label">数据源</span>
                <i
                    className={`state-mark state-mark--${overview.failed ? "unverified" : summary.indicator}`}
                    aria-hidden="true"
                />
                {statusLabel === "" ? null : (
                    <span className="ds-trigger__count">{statusLabel}</span>
                )}
                <svg
                    className="ds-trigger__caret"
                    viewBox="0 0 10 10"
                    fill="none"
                    aria-hidden="true"
                    focusable="false"
                >
                    <path
                        d="M2 3.8 5 6.9 8 3.8"
                        stroke="currentColor"
                        strokeWidth="1.3"
                        strokeLinecap="round"
                    />
                </svg>
            </button>
            {open ? (
                <div className="ds-popover" role="dialog" aria-label="数据源状态">
                    <header className="ds-popover__head">
                        <p className="ds-popover__title">数据源</p>
                        <span className="muted value">
                            {sources.length} 已配置
                            {summary.abnormal > 0 ? ` · ${String(summary.abnormal)} 异常` : ""}
                            {summary.unverified > 0
                                ? ` · ${String(summary.unverified)} 未验证`
                                : ""}
                        </span>
                    </header>
                    {overview.pending ? <p role="status">正在读取数据源…</p> : null}
                    {overview.failed ? (
                        <p className="error" role="alert">
                            数据源状态不可用：正式 Product API
                            无法访问，显示的是最后一次成功读取的事实。
                        </p>
                    ) : null}
                    {sources.length === 0 && !overview.pending ? (
                        <div className="empty-state">
                            <p className="empty-state__title">尚未配置数据源</p>
                            <p className="muted">
                                添加数据源后可以查看行情、同步历史数据并进行 Research。
                            </p>
                            <button type="button" onClick={openManager}>
                                添加第一个数据源
                            </button>
                        </div>
                    ) : null}
                    <ul className="ds-popover__list">
                        {sources.map((item) => {
                            const status = operational.get(item.integration_id);
                            const presentation = sourcePresentation(
                                item.lifecycle_state,
                                status?.status
                            );
                            const descriptor = types.find((type) => type.type_id === item.type_id);
                            return (
                                <li key={item.integration_id}>
                                    <ProviderIcon
                                        providerId={descriptor?.provider_id ?? item.type_id}
                                    />
                                    <div>
                                        <span className="ds-popover__name">
                                            {item.display_name}
                                        </span>
                                        <span className="ds-popover__meta muted">
                                            {status?.checked_at === null ||
                                            status?.checked_at === undefined
                                                ? "尚无探测结果"
                                                : `最近探测 ${formatTimestamp(status.checked_at)}`}
                                        </span>
                                        <CapabilityTags
                                            capabilities={descriptor?.capabilities ?? []}
                                        />
                                    </div>
                                    <span
                                        className={`state-badge state-badge--${presentation.tone}`}
                                    >
                                        <i className="state-mark" aria-hidden="true" />
                                        {presentation.label}
                                    </span>
                                </li>
                            );
                        })}
                    </ul>
                    <section className="ds-popover__workspace">
                        <p className="ds-popover__subtitle">当前工作区</p>
                        <p className="muted">
                            尚未有 canonical 来源绑定：工作区数据当前为 synthetic
                            占位，这里不显示任何 Provider 名。
                        </p>
                    </section>
                    <footer className="ds-popover__foot">
                        <button type="button" className="button-secondary" onClick={openManager}>
                            管理数据源…
                        </button>
                    </footer>
                </div>
            ) : null}
        </div>
    );
}
