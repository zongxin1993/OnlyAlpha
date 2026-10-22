import { expect, test } from "@playwright/test";

for (const destination of [
    { path: "/research/analysis", feature: "研究" },
    { path: "/data/inputs", feature: "数据" },
    { path: "/data/sources/existing-source", feature: "数据" }
]) {
    test(`deferred ${destination.path} remains usable on mobile`, async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await page.goto(destination.path);
        await expect(
            page.getByRole("heading", { name: `${destination.feature} · 未实现` })
        ).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
            true
        );
        await page.getByRole("link", { name: "返回工作台" }).click();
        await expect(page).toHaveURL("/");
        await expect(page.getByRole("region", { name: "主图" })).toBeVisible();
    });
}
