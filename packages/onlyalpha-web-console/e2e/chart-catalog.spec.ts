import { expect, test } from "@playwright/test";
import { chartCatalogFixture } from "./support/chartCatalog";

for (const condition of [
    "missing-catalog",
    "missing-readiness",
    "unsupported",
    "duplicate",
    "stale",
    "disappeared",
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
                if (condition === "stale" && activeReads > 1)
                    body = { ...fixture.active, runtime_generation_fingerprint: "b".repeat(64) };
                if (condition === "disappeared" && activeReads > 1) {
                    status = 503;
                    body = { detail: "RUNTIME_GENERATION_NOT_ACTIVE" };
                }
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
        expect(requests).not.toContain("/api/v2/research/catalog/calculations");
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
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "指标 / 因子参数配置" })).toHaveCount(0);
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

for (const width of [1440, 1024, 390]) {
    test(`Registered catalog is searchable and selectable without Runtime at ${String(width)}px`, async ({
        page
    }) => {
        await page.setViewportSize({ width, height: 900 });
        const fixture = chartCatalogFixture();
        const requests: string[] = [];
        await page.route("**/api/v2/research/**", (route) => {
            expect(route.request().method()).toBe("GET");
            const path = new URL(route.request().url()).pathname;
            requests.push(path);
            expect([
                "/api/v2/research/runtime-generations/active",
                "/api/v2/research/catalog/calculations"
            ]).toContain(path);
            return route.fulfill({
                status: path.endsWith("/active") ? 503 : 200,
                contentType: "application/json",
                body: JSON.stringify(
                    path.endsWith("/active")
                        ? { detail: "RUNTIME_GENERATION_NOT_ACTIVE" }
                        : fixture.discovery
                )
            });
        });
        await page.goto("/");
        const trigger = page.getByRole("button", { name: "指标", exact: true });
        await trigger.click();
        const dialog = page.getByRole("dialog");
        await expect(dialog.getByText("默认 20", { exact: true })).toBeVisible();
        await expect(dialog.getByText("默认 CLOSE", { exact: true })).toBeVisible();
        await expect(dialog.getByRole("status")).toContainText("Runtime 未激活");
        const search = dialog.getByRole("searchbox");
        await expect(search).toBeFocused();
        await search.fill("missing");
        await expect(dialog.getByText("没有匹配的注册项。", { exact: true })).toBeVisible();
        await search.fill("sma");
        const choose = dialog.getByRole("button", { name: "选择 SMA · 配置草稿" });
        await expect(choose).toBeEnabled();
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
            width
        );
        await dialog.getByRole("button", { name: "关闭目录" }).focus();
        await page.keyboard.press("Shift+Tab");
        await expect(choose).toBeFocused();
        await page.keyboard.press("Tab");
        await expect(dialog.getByRole("button", { name: "关闭目录" })).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(dialog).toHaveCount(0);
        await expect(trigger).toBeFocused();
        await trigger.click();
        await choose.click();
        const handoff = page.getByTestId("calculation-handoff");
        await expect(handoff).toHaveAttribute("data-registration-source", "REGISTERED_DISCOVERY");
        await expect(handoff).toHaveAttribute("data-type-id", "onlyalpha.indicator.sma");
        await expect(handoff).toContainText("执行未接入");
        for (const name of [
            "runtime-generation",
            "catalog-generation",
            "backend",
            "implementation",
            "readiness-capability"
        ])
            await expect(handoff).not.toHaveAttribute(`data-${name}`, /.+/);
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog", { name: "指标 / 因子参数配置" })).toHaveCount(0);
        await expect(trigger).toBeFocused();
        await page.getByRole("button", { name: "因子", exact: true }).click();
        await expect(dialog.getByText(/当前发现目录没有此类已登记项/)).toBeVisible();
        await expect(dialog.getByRole("button", { name: /选择 / })).toHaveCount(0);
        expect(requests.filter((path) => path.endsWith("/catalog/calculations"))).toHaveLength(4);
    });
}

test("required NULL BOOLEAN keeps explicit choice and keyboard focus after selecting false", async ({
    page
}) => {
    const discovery = {
        schema_version: 2,
        calculations: [
            {
                kind: "INDICATOR",
                type_reference: {
                    kind: "INDICATOR",
                    type_id: "example.boolean",
                    semantic_version: "1"
                },
                parameters: [
                    {
                        name: "enabled",
                        type: "BOOLEAN",
                        required: true,
                        default: { type: "NULL", value: null },
                        minimum: null,
                        maximum: null,
                        enum_values: [],
                        uppercase: false
                    }
                ],
                inputs: [],
                outputs: [
                    {
                        name: "value",
                        data_type: "BOOLEAN",
                        nullable: false,
                        dimensions: ["TIME"],
                        semantic_type: "BOOLEAN_SERIES",
                        unit: null
                    }
                ],
                parameter_sweep_allowed: true
            }
        ]
    };
    await page.route("**/api/v2/research/**", (route) =>
        route.fulfill({
            status: route.request().url().endsWith("/active") ? 503 : 200,
            contentType: "application/json",
            body: JSON.stringify(
                route.request().url().endsWith("/active")
                    ? { detail: "RUNTIME_GENERATION_NOT_ACTIVE" }
                    : discovery
            )
        })
    );
    await page.goto("/");
    await page.getByRole("button", { name: "指标", exact: true }).click();
    await page.getByRole("button", { name: /选择 BOOLEAN/ }).click();
    const editor = page.getByRole("dialog", { name: "指标 / 因子参数配置" });
    const choice = editor.getByRole("combobox", { name: "enabled", exact: true });
    await choice.focus();
    await choice.selectOption("false");
    await expect(choice).toBeFocused();
    await expect(choice).toHaveValue("false");
    await page.keyboard.press("Tab");
    await expect(editor.getByRole("combobox", { name: "输出", exact: true })).toBeFocused();
});
