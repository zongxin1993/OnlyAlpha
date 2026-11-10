export interface NavItem {
    readonly to: string;
    readonly label: string;
    readonly icon: string;
    /** 顶部工作条只属于工作台；其余画面使用页内标题（docs/webui/design-brief-2026-11-10.md）。 */
    readonly ctxbar: boolean;
}

export interface NavGroup {
    readonly group: string;
    readonly items: readonly NavItem[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
    {
        group: "投研",
        items: [
            { to: "/overview", label: "总览", icon: "dashboard", ctxbar: false },
            { to: "/", label: "工作台", icon: "candles", ctxbar: true },
            { to: "/research/new", label: "研究", icon: "research", ctxbar: false },
            { to: "/strategies", label: "策略", icon: "library", ctxbar: false },
            { to: "/backtest", label: "回测", icon: "runs", ctxbar: false }
        ]
    },
    {
        group: "基础设施",
        items: [
            { to: "/data/inputs", label: "数据", icon: "data", ctxbar: false },
            { to: "/system/health", label: "系统", icon: "shield", ctxbar: false }
        ]
    }
] as const;
