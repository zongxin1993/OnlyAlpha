import type { IntegrationSummary, IntegrationType } from "../../../api/integrations/model";
import { candidateSummary, capabilitySummary } from "./status";

interface BindingRow {
    readonly label: string;
    readonly capability: string;
    readonly bucket: "historical" | "realtime" | "reference";
    readonly selected: string | null;
}

const bindingGroups: readonly { readonly title: string; readonly rows: readonly BindingRow[] }[] = [
    {
        title: "加密货币 · Spot",
        rows: [
            {
                label: "历史数据",
                capability: "HISTORICAL_BARS",
                bucket: "historical",
                selected: null
            },
            { label: "实时数据", capability: "LIVE_BARS", bucket: "realtime", selected: null },
            { label: "参考数据", capability: "INSTRUMENTS", bucket: "reference", selected: null }
        ]
    },
    {
        title: "中国 A 股 · 日线与分钟",
        rows: [
            {
                label: "日线历史",
                capability: "HISTORICAL_BARS",
                bucket: "historical",
                selected: null
            },
            { label: "实时数据", capability: "LIVE_TICKS", bucket: "realtime", selected: null },
            { label: "参考数据", capability: "INSTRUMENTS", bucket: "reference", selected: null }
        ]
    }
];

/**
 * Source Binding has no canonical backend authority yet. This tab shows the approved
 * design state only: it never stores a browser-local default and never sends a command.
 */
export function DataSourceBindingTab({
    sources,
    types
}: {
    readonly sources: readonly IntegrationSummary[];
    readonly types: readonly IntegrationType[];
}) {
    function candidates(row: BindingRow) {
        return sources.filter((item) => {
            if (item.lifecycle_state !== "ACTIVE") return false;
            const descriptor = types.find((type) => type.type_id === item.type_id);
            return (
                descriptor !== undefined && capabilitySummary(descriptor.capabilities)[row.bucket]
            );
        });
    }
    return (
        <div className="binding-tab">
            <p className="banner banner--gap">
                <span className="tag tag--gap">后端缺口</span>此 Tab 目前没有 canonical
                事实：Product API 尚无来源绑定资源。实现前必须先有正式绑定 API；Web
                不在本地存储或推导默认来源，也不发送任何绑定命令。
            </p>
            {bindingGroups.map((group) => (
                <section className="binding-group" key={group.title}>
                    <h3>{group.title}</h3>
                    {group.rows.map((row) => {
                        const options = candidates(row);
                        const names = candidateSummary(options.map((item) => item.display_name));
                        return (
                            <div className="binding-row" key={`${group.title}-${row.label}`}>
                                <span className="binding-row__label">{row.label}</span>
                                <span className="binding-row__value binding-row__value--unset">
                                    未设置
                                </span>
                                <span className="binding-row__note muted">
                                    候选 {options.length} 个{names === "" ? "" : `：${names}`}（按
                                    capability {row.capability} 过滤）· 设计态，未持久化
                                </span>
                            </div>
                        );
                    })}
                </section>
            ))}
            <p className="muted">
                被禁用或未启用中的数据源不会出现在候选里；OnlyAlpha 不会自动 fallback 到其他
                Provider。「市场范围」本身也属于尚未开放的 canonical 能力，因此候选只按 capability
                过滤。
            </p>
        </div>
    );
}
