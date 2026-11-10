import { expect, test, type ElementHandle } from "@playwright/test";

// 研究与数据、系统仍是占位画面（策略转真实工作流见 aa0b3349，工具条整合见 e14e22c8）；
// 策略与回测已是真实页面，断言各自的真实标题而非"未实现"占位。
const destinations = [
    { path: "/research/new", feature: "研究", heading: "研究 · 未实现", deferred: true },
    { path: "/strategies", feature: "策略", heading: "我的策略", deferred: false },
    { path: "/backtest", feature: "回测", heading: "策略回测", deferred: false },
    { path: "/data/inputs", feature: "数据", heading: "数据 · 未实现", deferred: true },
    { path: "/system/health", feature: "系统", heading: "系统 · 未实现", deferred: true }
] as const;

// 左侧栏 DOM 顺序（NAV_GROUPS）：总览、工作台、研究、策略、回测、数据、系统。
const keyboardTour = [
    { nav: "总览", path: "/overview", enter: true },
    { nav: "工作台", path: "/", enter: false },
    { nav: "研究", path: "/research/new", enter: true },
    { nav: "策略", path: "/strategies", enter: true },
    { nav: "回测", path: "/backtest", enter: true },
    { nav: "数据", path: "/data/inputs", enter: true },
    { nav: "系统", path: "/system/health", enter: true }
] as const;

for (const width of [1440, 390]) {
    test(`deferred navigation and workstation return at ${String(width)}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        const businessRequests: string[] = [];
        const recordRequest = (request: { url(): string }) => {
            const path = new URL(request.url()).pathname;
            if (path.startsWith("/api/") || path.startsWith("/health/")) {
                businessRequests.push(path);
            }
        };
        page.on("request", recordRequest);
        await page.goto("/research/new");
        const navigation = page.getByRole("navigation", { name: "产品导航" });
        const drawer = width <= 900;
        const openNavigation = page.getByRole("button", { name: "开启导航" });
        // 关闭态抽屉对辅助技术不可见：角色查询只在打开态进行，身份句柄在打开时捕获。
        const persistentNavigation: ElementHandle<HTMLElement | SVGElement> | null = drawer
            ? null
            : await navigation.elementHandle();
        if (!drawer && !persistentNavigation) throw new Error("desktop handle required");
        let drawerNavigation: ElementHandle<HTMLElement | SVGElement> | null = null;
        for (const destination of destinations) {
            const requestsBefore = businessRequests.length;
            if (drawer) {
                // 窄屏导航收进抽屉：真实用户先点 ☰ 再选择画面。
                await openNavigation.click();
                drawerNavigation ??= await navigation.elementHandle();
            }
            const link = navigation.getByRole("link", { name: destination.feature, exact: true });
            await expect(link).toHaveAttribute("href", destination.path);
            await link.scrollIntoViewIfNeeded();
            await expect(link).toBeInViewport();
            await link.click();
            if (drawer) {
                await expect(page.locator("body")).not.toHaveClass(/rail-open/);
            }
            await expect(page).toHaveURL(destination.path);
            await expect(
                page.locator(`.side-rail nav a[href="${destination.path}"]`)
            ).toHaveAttribute("aria-current", "page");
            await expect(page.getByRole("heading", { name: destination.heading })).toBeVisible();
            if (destination.deferred) {
                await expect(page.getByRole("status")).toContainText("此功能尚未实现");
                expect(businessRequests.length).toBe(requestsBefore);
            }
            const held = drawer ? drawerNavigation : persistentNavigation;
            if (!held) throw new Error("navigation handle missing");
            expect(await held.evaluate((element) => element.isConnected)).toBe(true);
            expect(
                await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
            ).toBe(true);
        }
        if (!drawer) {
            // Traverse the real product controls by keyboard without entering a deferred command.
            await page.getByRole("link", { name: "OnlyAlpha 工作台" }).focus();
            for (const stop of keyboardTour) {
                await page.keyboard.press("Tab");
                const link = navigation.getByRole("link", { name: stop.nav, exact: true });
                await expect(link).toBeFocused();
                await expect(link).toBeInViewport();
                expect(await link.evaluate((element) => element.matches(":focus-visible"))).toBe(
                    true
                );
                if (stop.enter) {
                    await page.keyboard.press("Enter");
                    await expect(page).toHaveURL(stop.path);
                }
            }
        }
        page.off("request", recordRequest);
        if (drawer) {
            // 390：抽屉打开后焦点入栏，按 DOM 顺序 Tab 到目标链接后回车——确定性键盘路径。
            const openNavigation = page.getByRole("button", { name: "开启导航" });
            const stops = keyboardTour.filter((stop) => stop.enter);
            for (const [index, stop] of stops.entries()) {
                await openNavigation.focus();
                await page.keyboard.press("Enter");
                // 焦点入栏与打开同帧（layout effect）；Tab 跟随真实 DOM 序到目标链接。
                await expect(page.locator(".side-rail a").first()).toBeFocused();
                const activeHref = () =>
                    page.evaluate(() => document.activeElement?.getAttribute("href"));
                for (let guard = 0; guard < 12 && (await activeHref()) !== stop.path; guard += 1) {
                    await page.keyboard.press("Tab");
                }
                // activeElement 即真实焦点；角色查询会撞上路由激活态重渲染的重建窗口，不作焦点判据。
                await expect.poll(activeHref).toBe(stop.path);
                const last = index === stops.length - 1;
                if (index === 0 || last) {
                    // 首末两站走完整键盘导航（Tab→Enter→收起→焦点归还 ☰），其余站验证可达。
                    await page.keyboard.press("Enter");
                    await expect(page).toHaveURL(stop.path);
                } else {
                    await page.keyboard.press("Escape");
                }
                await expect(page.locator(".side-rail")).not.toHaveClass(/is-open/);
                await expect(openNavigation).toBeFocused();
            }
        }
        await page.getByRole("link", { name: "返回工作台" }).click();
        await expect(page).toHaveURL("/");
        await expect(page.getByRole("region", { name: "主图" })).toBeVisible();
        const heldHandle = drawer ? drawerNavigation : persistentNavigation;
        if (!heldHandle) throw new Error("navigation handle missing");
        await heldHandle.dispose();
    });
}
