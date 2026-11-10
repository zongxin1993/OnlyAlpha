import { describe, expect, it } from "vitest";
import { NAV_GROUPS } from "./nav";

describe("导航配置单一来源", () => {
    it("两组共七项，顺序符合冻结稿", () => {
        expect(NAV_GROUPS.map((g) => g.group)).toEqual(["投研", "基础设施"]);
        expect(NAV_GROUPS.flatMap((g) => g.items.map((i) => i.label))).toEqual([
            "总览",
            "工作台",
            "研究",
            "策略",
            "回测",
            "数据",
            "系统"
        ]);
    });

    it("路由无重复且与现行路由一致", () => {
        const routes = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.to));
        expect(new Set(routes).size).toBe(routes.length);
        expect(routes).toEqual([
            "/overview",
            "/",
            "/research/new",
            "/strategies",
            "/backtest",
            "/data/inputs",
            "/system/health"
        ]);
    });

    it("顶部工作条只属于工作台", () => {
        const ctxItems = NAV_GROUPS.flatMap((g) => g.items).filter((i) => i.ctxbar);
        expect(ctxItems).toHaveLength(1);
        expect(ctxItems[0]?.to).toBe("/");
    });

    it("每项都有图标", () => {
        for (const item of NAV_GROUPS.flatMap((g) => g.items)) {
            expect(item.icon).toMatch(/^[a-z][a-z0-9-]*$/);
        }
    });
});
