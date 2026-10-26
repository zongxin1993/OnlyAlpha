import { expect, test } from "@playwright/test";

const destinations = [
    { path: "/research/new", feature: "研究" },
    { path: "/data/inputs", feature: "数据" },
    { path: "/strategies", feature: "策略" },
    { path: "/backtest/runs", feature: "回测" },
    { path: "/system/health", feature: "系统" }
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
        const persistentNavigation = await navigation.elementHandle();
        for (const destination of destinations) {
            const label = `${destination.feature} · 未实现`;
            const link = navigation.getByRole("link", { name: label, exact: true });
            await expect(link).toHaveAttribute("href", destination.path);
            await link.scrollIntoViewIfNeeded();
            await expect(link).toBeInViewport();
            await link.click();
            await expect(page).toHaveURL(destination.path);
            await expect(link).toHaveAttribute("aria-current", "page");
            await expect(page.getByRole("heading", { name: label })).toBeVisible();
            await expect(page.getByRole("status")).toContainText("此功能尚未实现");
            expect(await persistentNavigation.evaluate((element) => element.isConnected)).toBe(
                true
            );
            expect(
                await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
            ).toBe(true);
        }
        // Traverse the real product controls by keyboard without entering a deferred command.
        await page.getByRole("link", { name: "OnlyAlpha 工作台" }).focus();
        await page.keyboard.press("Tab");
        await expect(navigation.getByRole("link", { name: "工作台", exact: true })).toBeFocused();
        for (const destination of destinations) {
            await page.keyboard.press("Tab");
            const link = navigation.getByRole("link", {
                name: `${destination.feature} · 未实现`,
                exact: true
            });
            await expect(link).toBeFocused();
            await expect(link).toBeInViewport();
            expect(await link.evaluate((element) => element.matches(":focus-visible"))).toBe(true);
            await page.keyboard.press("Enter");
            await expect(page).toHaveURL(destination.path);
        }
        expect(businessRequests).toEqual([]);
        page.off("request", recordRequest);
        await page.getByRole("link", { name: "返回工作台" }).click();
        await expect(page).toHaveURL("/");
        await expect(page.getByRole("region", { name: "主图" })).toBeVisible();
        await persistentNavigation.dispose();
    });
}
