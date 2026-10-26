import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type {
    IntegrationOperationalStatus,
    IntegrationSummary,
    IntegrationType
} from "../../../api/integrations/model";
import { isIndeterminateMutationError } from "../../../api/integrations/client";
import { MutationSubmissionIntent } from "../../../api/integrations/submissionIntent";
import { useIntegrationApi } from "../../../app/providers";
import { CapabilityTags } from "./CapabilityTags";
import { ProviderIcon } from "./ProviderIcon";
import type { DataSourceOverview } from "./overview";
import {
    describeError,
    formatTimestamp,
    probeSupport,
    shortFingerprint,
    sourcePresentation,
    sourceRank
} from "./status";

function ConfiguredSourceCard({
    source,
    descriptor,
    status,
    onOpen
}: {
    readonly source: IntegrationSummary;
    readonly descriptor: IntegrationType | undefined;
    readonly status: IntegrationOperationalStatus | undefined;
    readonly onOpen: () => void;
}) {
    const client = useIntegrationApi();
    const cache = useQueryClient();
    const intent = useRef(new MutationSubmissionIntent());
    const [busy, setBusy] = useState("");
    const [error, setError] = useState("");
    const [menuOpen, setMenuOpen] = useState(false);
    const menu = useRef<HTMLDivElement>(null);
    const menuTrigger = useRef<HTMLButtonElement>(null);
    const presentation = sourcePresentation(source.lifecycle_state, status?.status);
    const support = probeSupport(descriptor?.probe_contract != null, status?.probe_supported);
    const revision = source.current_revision_fingerprint ?? null;
    const archived = source.lifecycle_state === "ARCHIVED";

    async function run(
        label: string,
        key: string,
        operation: (commandId: string) => Promise<unknown>
    ) {
        setBusy(label);
        setError("");
        try {
            await operation(intent.current.commandFor(key));
            intent.current.definitive(key);
            await cache.invalidateQueries({ queryKey: ["integrations"] });
        } catch (value) {
            if (!isIndeterminateMutationError(value)) intent.current.definitive(key);
            setError(describeError(value));
        } finally {
            setBusy("");
            setMenuOpen(false);
        }
    }

    const probeReason = !support.canProbe
        ? (support.notice ?? "")
        : revision === null
          ? "需要先发布一个 Revision 才能测试连接"
          : "";

    useEffect(() => {
        if (!menuOpen) return;
        function onKey(event: KeyboardEvent) {
            if (event.key !== "Escape") return;
            event.stopPropagation();
            setMenuOpen(false);
            menuTrigger.current?.focus();
        }
        function onPointer(event: MouseEvent) {
            if (menu.current !== null && !menu.current.contains(event.target as Node))
                setMenuOpen(false);
        }
        document.addEventListener("keydown", onKey, true);
        document.addEventListener("mousedown", onPointer);
        return () => {
            document.removeEventListener("keydown", onKey, true);
            document.removeEventListener("mousedown", onPointer);
        };
    }, [menuOpen]);

    return (
        <article
            className="configured-source"
            data-lifecycle={source.lifecycle_state}
            aria-label={source.display_name}
        >
            <div className="configured-source__head">
                <ProviderIcon providerId={descriptor?.provider_id ?? source.type_id} size="lg" />
                <div className="configured-source__identity">
                    <h3>{source.display_name}</h3>
                    <p className="muted">{descriptor?.description ?? source.type_id}</p>
                </div>
                <span className={`state-badge state-badge--${presentation.tone}`}>
                    <i className="state-mark" aria-hidden="true" />
                    {presentation.label}
                </span>
            </div>
            <div className="configured-source__meta">
                <CapabilityTags capabilities={descriptor?.capabilities ?? []} />
                <span className="value">草稿 v{source.draft_version}</span>
                <span className="value">revision {shortFingerprint(revision)}</span>
                {status?.checked_at ? (
                    <span className="value">最近探测 {formatTimestamp(status.checked_at)}</span>
                ) : null}
            </div>
            {support.notice ? <p className="configured-source__notice">{support.notice}</p> : null}
            {busy === "probe" ? (
                <p className="configured-source__probing" role="status">
                    <i className="state-mark state-mark--probing" aria-hidden="true" />
                    正在测试连接…
                </p>
            ) : null}
            {error ? (
                <p className="error" role="alert">
                    {error}
                </p>
            ) : null}
            <div className="configured-source__actions">
                {descriptor?.probe_contract != null ? (
                    <button
                        type="button"
                        className="button-secondary"
                        disabled={!support.canProbe || revision === null || busy !== ""}
                        aria-description={probeReason === "" ? undefined : probeReason}
                        title={probeReason === "" ? undefined : probeReason}
                        onClick={() => {
                            if (revision === null) return;
                            void run("probe", JSON.stringify(["probe", revision]), () =>
                                client.probe(source.integration_id, revision)
                            );
                        }}
                    >
                        {busy === "probe" ? "测试中…" : "测试连接"}
                    </button>
                ) : null}
                <button type="button" className="button-subtle" onClick={onOpen}>
                    配置
                </button>
                <button
                    type="button"
                    className="button-subtle"
                    disabled={archived || busy !== ""}
                    onClick={() => {
                        void run(
                            "lifecycle",
                            JSON.stringify(["lifecycle", source.lifecycle_state, "toggle"]),
                            (commandId) =>
                                client.setLifecycle(
                                    source.integration_id,
                                    source.lifecycle_state,
                                    source.lifecycle_state === "ACTIVE" ? "DISABLED" : "ACTIVE",
                                    commandId
                                )
                        );
                    }}
                >
                    {source.lifecycle_state === "ACTIVE" ? "禁用" : "启用"}
                </button>
                <div className="overflow-menu" ref={menu}>
                    <button
                        type="button"
                        className="button-icon"
                        ref={menuTrigger}
                        aria-expanded={menuOpen}
                        aria-label={`${source.display_name} 更多操作`}
                        onClick={() => {
                            setMenuOpen(!menuOpen);
                        }}
                    >
                        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                            <circle cx="3.4" cy="8" r="1.15" fill="currentColor" />
                            <circle cx="8" cy="8" r="1.15" fill="currentColor" />
                            <circle cx="12.6" cy="8" r="1.15" fill="currentColor" />
                        </svg>
                    </button>
                    {menuOpen ? (
                        <div className="overflow-menu__panel" role="group" aria-label="低频操作">
                            <button type="button" className="button-subtle" onClick={onOpen}>
                                查看 revision / probe 历史
                            </button>
                            <button
                                type="button"
                                className="button-subtle"
                                disabled={archived || busy !== ""}
                                onClick={() => {
                                    void run(
                                        "archive",
                                        JSON.stringify(["archive", source.lifecycle_state]),
                                        (commandId) =>
                                            client.setLifecycle(
                                                source.integration_id,
                                                source.lifecycle_state,
                                                "ARCHIVED",
                                                commandId
                                            )
                                    );
                                }}
                            >
                                归档（删除）
                            </button>
                            <p className="muted">
                                归档保留 revision、凭据绑定与历史证据，不删除数据。
                            </p>
                        </div>
                    ) : null}
                </div>
            </div>
        </article>
    );
}

export function ConfiguredSourcesTab({
    overview,
    onOpenSource,
    onAddSource
}: {
    readonly overview: DataSourceOverview;
    readonly onOpenSource: (integrationId: string) => void;
    readonly onAddSource: () => void;
}) {
    const [showArchived, setShowArchived] = useState(false);
    const [limit, setLimit] = useState(50);
    const visible = overview.sources
        .filter((item) => showArchived || item.lifecycle_state !== "ARCHIVED")
        .slice()
        .sort((left, right) => {
            const leftStatus = overview.operational.get(left.integration_id)?.status;
            const rightStatus = overview.operational.get(right.integration_id)?.status;
            return (
                sourceRank(left.lifecycle_state, leftStatus) -
                    sourceRank(right.lifecycle_state, rightStatus) ||
                left.display_name.localeCompare(right.display_name)
            );
        });
    const archivedCount = overview.sources.filter(
        (item) => item.lifecycle_state === "ARCHIVED"
    ).length;
    if (overview.pending) return <p role="status">正在读取数据源…</p>;
    if (overview.failed) {
        return (
            <p className="error" role="alert">
                数据源状态不可用：正式 Product API 无法访问。界面不会 fallback 到任何推断值。
            </p>
        );
    }
    if (overview.sources.length === 0) {
        return (
            <div className="empty-state">
                <h3>尚未配置数据源</h3>
                <p className="muted">添加数据源后可以查看行情、同步历史数据并进行 Research。</p>
                <button type="button" onClick={onAddSource}>
                    添加第一个数据源
                </button>
            </div>
        );
    }
    const shown = visible.slice(0, limit);
    const hidden = visible.length - shown.length;
    return (
        <div className="configured-list">
            {shown.map((item) => (
                <ConfiguredSourceCard
                    key={item.integration_id}
                    source={item}
                    descriptor={overview.types.find((type) => type.type_id === item.type_id)}
                    status={overview.operational.get(item.integration_id)}
                    onOpen={() => {
                        onOpenSource(item.integration_id);
                    }}
                />
            ))}
            {hidden > 0 ? (
                <p className="muted">
                    已显示 {shown.length} / {visible.length} 个数据源。
                    <button
                        type="button"
                        className="button-subtle"
                        onClick={() => {
                            setLimit(limit + 50);
                        }}
                    >
                        显示更多
                    </button>
                </p>
            ) : null}
            {!showArchived && archivedCount > 0 ? (
                <button
                    type="button"
                    className="button-subtle"
                    onClick={() => {
                        setShowArchived(true);
                    }}
                >
                    显示已归档（{archivedCount}）
                </button>
            ) : null}
            {showArchived && archivedCount > 0 ? (
                <button
                    type="button"
                    className="button-subtle"
                    onClick={() => {
                        setShowArchived(false);
                    }}
                >
                    隐藏已归档（{archivedCount}）
                </button>
            ) : null}
        </div>
    );
}
