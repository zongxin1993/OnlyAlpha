import { expect, test } from "@playwright/test";

test("real Browser reads the Research product through Web and API", async ({ page }) => {
    const live = await page.request.get("/health/live");
    expect(live.ok(), `${String(live.status())}: ${await live.text()}`).toBeTruthy();

    await page.goto("/research/runs");
    await expect(page.getByRole("heading", { name: "Research Runs", exact: true })).toBeVisible();
    await expect(page.getByText("No Runs have been submitted.", { exact: true })).toBeVisible();

    const runs = await page.request.get("/api/v2/research/runs?limit=10");
    expect(runs.ok()).toBeTruthy();
    await expect(page).toHaveURL(/\/research\/runs$/);
});
