import { useRef, useState } from "react";
import { isIndeterminateMutationError } from "../../../api/integrations/client";
import { createUuidV4, MutationSubmissionIntent } from "../../../api/integrations/submissionIntent";
import { useIntegrationApi } from "../../../app/providers";
import { ProviderIcon } from "./ProviderIcon";
import type { DataSourceOverview } from "./overview";
import { capabilitySummary } from "./status";

const capabilityLabels: readonly [keyof ReturnType<typeof capabilitySummary>, string][] = [
    ["historical", "历史"],
    ["realtime", "实时"],
    ["reference", "参考"]
];

export function AddDataSourceTab({
    overview,
    onCreated
}: {
    readonly overview: DataSourceOverview;
    readonly onCreated: (integrationId: string) => void;
}) {
    const client = useIntegrationApi();
    const [query, setQuery] = useState("");
    const [limit, setLimit] = useState(60);
    const [typeId, setTypeId] = useState("");
    const [displayName, setDisplayName] = useState("");
    const [error, setError] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const intent = useRef(new MutationSubmissionIntent());
    const pending = useRef<{ readonly key: string; readonly integrationId: string } | null>(null);
    const needle = query.trim().toLowerCase();
    const matches = overview.types.filter(
        (item) =>
            needle === "" ||
            `${item.display_name} ${item.type_id} ${item.provider_id}`
                .toLowerCase()
                .includes(needle)
    );

    if (typeId !== "") {
        const selected = overview.types.find((item) => item.type_id === typeId);
        return (
            <form
                className="create-source"
                aria-label="新建数据源"
                onSubmit={(event) => {
                    event.preventDefault();
                    const key = JSON.stringify({ typeId, displayName });
                    if (pending.current !== null && pending.current.key !== key) {
                        intent.current.definitive(pending.current.key);
                    }
                    const integrationId =
                        pending.current?.key === key
                            ? pending.current.integrationId
                            : createUuidV4();
                    pending.current = { key, integrationId };
                    const commandId = intent.current.commandFor(key);
                    setSubmitting(true);
                    setError("");
                    void client
                        .createIntegration(
                            {
                                integration_id: integrationId,
                                type_id: typeId,
                                display_name: displayName
                            },
                            commandId
                        )
                        .then(() => {
                            intent.current.definitive(key);
                            pending.current = null;
                            onCreated(integrationId);
                        })
                        .catch((value: unknown) => {
                            if (!isIndeterminateMutationError(value)) {
                                intent.current.definitive(key);
                                pending.current = null;
                            }
                            setError(value instanceof Error ? value.message : "创建失败");
                        })
                        .finally(() => {
                            setSubmitting(false);
                        });
                }}
            >
                <button
                    type="button"
                    className="button-subtle"
                    onClick={() => {
                        setTypeId("");
                        setError("");
                    }}
                >
                    ← 返回 Provider 列表
                </button>
                <div className="create-source__head">
                    <ProviderIcon providerId={selected?.provider_id ?? typeId} size="lg" />
                    <div>
                        <h3>{selected?.display_name ?? typeId}</h3>
                        <p className="muted">{selected?.description ?? ""}</p>
                    </div>
                </div>
                <label>
                    显示名称
                    <input
                        value={displayName}
                        required
                        onChange={(event) => {
                            setDisplayName(event.target.value);
                        }}
                    />
                </label>
                <p className="muted">
                    创建后进入配置视图：填写该类型的契约字段、测试连接、保存草稿或发布 Revision。
                </p>
                {error ? (
                    <p className="error" role="alert">
                        {error}
                    </p>
                ) : null}
                <div className="create-source__actions">
                    <button type="submit" disabled={submitting}>
                        {submitting ? "创建中…" : "创建数据源"}
                    </button>
                </div>
            </form>
        );
    }

    const visible = matches.slice(0, limit);
    const hidden = matches.length - visible.length;
    return (
        <div className="provider-catalog">
            <div className="catalog-toolbar">
                <label className="search-field">
                    <span className="visually-hidden">搜索数据源类型</span>
                    <input
                        type="search"
                        placeholder="搜索数据源类型 / 供应商"
                        value={query}
                        onChange={(event) => {
                            setQuery(event.target.value);
                        }}
                    />
                </label>
                <span className="muted">
                    来源：正式 Product API /integration-types?category=DATA_SOURCE
                </span>
            </div>
            {overview.pending ? <p role="status">正在读取 Integration Type…</p> : null}
            {overview.failed ? (
                <p className="error" role="alert">
                    无法读取 Integration Type。
                </p>
            ) : null}
            <div className="provider-grid">
                {visible.map((item) => {
                    const summary = capabilitySummary(item.capabilities);
                    return (
                        <button
                            key={item.type_id}
                            type="button"
                            className="provider-card"
                            onClick={() => {
                                setTypeId(item.type_id);
                                setDisplayName(item.display_name);
                            }}
                        >
                            <ProviderIcon providerId={item.provider_id} size="lg" />
                            <span className="provider-card__name">{item.display_name}</span>
                            <span className="capability-tags">
                                {capabilityLabels
                                    .filter(([key]) => summary[key] === true)
                                    .map(([key, label]) => (
                                        <span className="capability-tag" key={key}>
                                            {label}
                                        </span>
                                    ))}
                            </span>
                            <span className="provider-card__description">{item.description}</span>
                        </button>
                    );
                })}
            </div>
            {matches.length === 0 && !overview.pending ? (
                <p className="muted">
                    {overview.types.length === 0
                        ? "服务端尚未发布任何 DATA_SOURCE 类型。"
                        : "没有匹配的数据源类型。"}
                </p>
            ) : null}
            {hidden > 0 ? (
                <p className="muted">
                    已显示 {visible.length} / {matches.length} 个类型。
                    <button
                        type="button"
                        className="button-subtle"
                        onClick={() => {
                            setLimit(limit + 60);
                        }}
                    >
                        显示更多
                    </button>
                </p>
            ) : null}
            <p className="muted">
                Provider 图标为 fallback 字母盒：仓库暂无品牌资产，官方 Logo 需另行提供。
            </p>
        </div>
    );
}
