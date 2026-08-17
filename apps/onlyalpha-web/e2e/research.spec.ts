import { expect, test } from "@playwright/test";

const result = "c1c188880821de9790dfcc84a075c8bdd615f273c27f9fa75bcccc1e812d33cc";
const statistics = "a23de5e058ec65fe9251b525f10c9b4d8a4b7a4b62d478214a1f0a7c50eef411";

test("portable Artifact to API v2 to browser exact vertical slice", async ({ page }) => {
    await page.goto("/research");
    await page.getByLabel("Research Result fingerprint").fill(result);
    await page.getByRole("button", { name: "Open exact result" }).click();
    await expect(page.getByRole("heading", { name: "Artifact overview" })).toBeVisible();
    await expect(page.getByText(result).first()).toBeVisible();
    await page.getByRole("link", { name: new RegExp(statistics) }).click();
    await expect(page).toHaveURL(`/research/${result}/statistics/${statistics}`);
    await page.reload();
    await expect(page).toHaveURL(`/research/${result}/statistics/${statistics}`);
    await expect(page.getByTestId("research-chart")).toBeVisible();
    await expect(page.locator("table").filter({ hasText: "Raw ts_event_ns" })).toBeVisible();
    await expect(page.getByRole("cell", { name: /^176/ }).first()).toBeVisible();
    await expect(page.getByText("2 loaded · more available")).toBeVisible();
    await page.getByRole("button", { name: "Load more" }).click();
    await expect(page.getByText("4 loaded · complete")).toBeVisible();
});
