import { expect, test } from "@playwright/test";

for (const path of [
    "/research/new",
    "/research/runs/existing-run",
    "/research/results/exact-result/statistics/exact-statistics",
    "/research/library"
]) {
    test(`deferred Research address ${path} makes no business request`, async ({ page }) => {
        const requests: string[] = [];
        page.on("request", (request) => {
            if (new URL(request.url()).pathname.startsWith("/api/")) requests.push(request.url());
        });
        await page.goto(path);
        await expect(page.getByRole("heading", { name: "研究 · 未实现" })).toBeVisible();
        await expect(page.getByRole("status")).toContainText("此功能尚未实现");
        await expect(page.getByRole("link", { name: "返回工作台" })).toHaveAttribute("href", "/");
        expect(requests).toEqual([]);
    });
}
