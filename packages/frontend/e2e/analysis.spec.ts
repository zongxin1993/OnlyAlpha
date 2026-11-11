import { expect, test } from "@playwright/test";

// 研究仍走 Deferred 占位契约；数据画面（P2 Task 12 接回）改为真实画面移动可用性锚。
for (const destination of [{ path: "/research/analysis", feature: "研究" }]) {
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

for (const path of ["/data/inputs", "/data/sources/existing-source"]) {
    test(`数据画面 ${path} remains usable on mobile`, async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await page.goto(path);
        await expect(page.getByRole("heading", { name: "数据", exact: true })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
            true
        );
        // 真实画面的返回路径是左侧栏本身（Deferred 占位的「返回工作台」链接已不适用）；
        // 390 下侧栏为关闭态抽屉，用 DOM 锚断言入口存在，不做可见性断言。
        await expect(page.locator(".side-rail nav a[href='/']")).toHaveCount(1);
    });
}
