import { expect, test } from "@playwright/test";
import { chartCatalogFixture } from "./support/chartCatalog";

for (const condition of [
    "no-runtime",
    "missing-catalog",
    "missing-readiness",
    "unsupported",
    "duplicate",
    "stale",
    "transport"
] as const) {
    test(`Catalog fails closed for ${condition} without submitting commands`, async ({ page }) => {
        const fixture = chartCatalogFixture();
        let activeReads = 0;
        const requests: string[] = [];
        if (condition === "missing-readiness")
            fixture.readiness.ordered_calculation_readiness_capabilities = [];
        if (condition === "unsupported") fixture.witness.readiness_contract_versions = [];
        if (condition === "duplicate")
            fixture.context.ordered_calculation_capabilities.push(fixture.capability);
        await page.route("**/api/v2/research/**", async (route) => {
            expect(route.request().method()).toBe("GET");
            const path = new URL(route.request().url()).pathname;
            requests.push(path);
            let status = 200;
            let body: unknown;
            if (path.endsWith("/active")) {
                activeReads++;
                body = fixture.active;
                if (condition === "no-runtime") {
                    status = 503;
                    body = { detail: "RUNTIME_GENERATION_NOT_ACTIVE" };
                }
                if (condition === "stale" && activeReads > 1)
                    body = { ...fixture.active, runtime_generation_fingerprint: "b".repeat(64) };
                if (condition === "transport") return route.abort("failed");
            } else if (path.includes("/runtime-generations/")) body = fixture.binding;
            else if (path.endsWith("/readiness")) body = fixture.readiness;
            else {
                body = fixture.context;
                if (condition === "missing-catalog") {
                    status = 404;
                    body = { detail: "EXACT_CATALOG_CONTEXT_NOT_FOUND" };
                }
            }
            await route.fulfill({
                status,
                contentType: "application/json",
                body: JSON.stringify(body)
            });
        });
        await page.goto("/");
        await page.getByRole("button", { name: "指标", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: "指标 / 因子目录" });
        if (condition === "missing-readiness" || condition === "unsupported")
            await expect(dialog.getByRole("button", { name: /选择 SMA/ })).toBeDisabled();
        else await expect(dialog.getByRole("alert")).toBeVisible();
        await expect(page.getByTestId("calculation-handoff")).toHaveCount(0);
        expect(requests.length).toBeGreaterThan(0);
        await page.keyboard.press("Escape");
        await expect(dialog).toHaveCount(0);
    });
}

test("Catalog selection detects a later active switch and clears previous handoff", async ({
    page
}) => {
    const fixture = chartCatalogFixture();
    let active = fixture.runtime;
    await page.route("**/api/v2/research/**", (route) => {
        expect(route.request().method()).toBe("GET");
        const path = new URL(route.request().url()).pathname;
        const body = path.endsWith("/active")
            ? { ...fixture.active, runtime_generation_fingerprint: active }
            : path.includes("/runtime-generations/")
              ? fixture.binding
              : path.endsWith("/readiness")
                ? fixture.readiness
                : fixture.context;
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("/");
    const trigger = page.getByRole("button", { name: "指标", exact: true });
    await trigger.click();
    await page.getByRole("button", { name: /选择 SMA/ }).click();
    await expect(page.getByTestId("calculation-handoff")).toBeVisible();
    await trigger.click();
    await expect(page.getByTestId("calculation-handoff")).toHaveCount(0);
    const select = page.getByRole("button", { name: /选择 SMA/ });
    await expect(select).toBeEnabled();
    active = "b".repeat(64);
    await select.click();
    await expect(page.getByRole("alert")).toContainText("已切换");
    await expect(page.getByTestId("calculation-handoff")).toHaveCount(0);
    await expect(select).toHaveCount(0);
});
