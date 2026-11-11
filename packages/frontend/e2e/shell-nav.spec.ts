import { expect, test } from "@playwright/test";

const SHELL_ROUTES = [
    "/",
    "/overview",
    "/research/new",
    "/strategies",
    "/backtest",
    "/data/inputs",
    "/system/health"
] as const;

const MATRIX_WIDTHS = [390, 640, 768, 880, 1024, 1152, 1440] as const;

test("1440 下七项导航中文可见并逐项目击到目标画面", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "产品导航" });
    await expect(nav.locator(".rail-group-label")).toHaveText(["投研", "基础设施"]);

    await nav.getByRole("link", { name: "总览" }).click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.getByRole("heading", { name: "总览" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "总览" })).toHaveAttribute("aria-current", "page");

    await expect(page).toHaveURL(/\/overview$/);
    await nav.getByRole("link", { name: "研究" }).click();
    await expect(page).toHaveURL(/\/research\/new$/);
    await expect(page.getByRole("heading", { name: "研究 · 未实现" })).toBeVisible();

    await nav.getByRole("link", { name: "策略" }).click();
    await expect(page).toHaveURL(/\/strategies/);
    await expect(nav.getByRole("link", { name: "策略" })).toHaveAttribute("aria-current", "page");

    await nav.getByRole("link", { name: "回测" }).click();
    await expect(page).toHaveURL(/\/backtest/);

    await nav.getByRole("link", { name: "数据" }).click();
    await expect(page).toHaveURL(/\/data\/inputs$/);
    await expect(page.getByRole("heading", { name: "数据", exact: true })).toBeVisible();

    await nav.getByRole("link", { name: "系统" }).click();
    await expect(page.getByRole("heading", { name: "系统 · 未实现" })).toBeVisible();

    await nav.getByRole("link", { name: "工作台" }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("toolbar", { name: "图表工作条" })).toBeVisible();
});

test("主题切换后刷新保持所选主题", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.getByRole("button", { name: "切换主题" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByRole("button", { name: "切换主题" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("工作台渲染上下文条，总览使用页内标题", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.locator(".context-bar")).toBeVisible();
    await expect(page.locator("#workspace-toolbar-host")).toBeAttached();
    await expect(page.locator(".view-head")).toHaveCount(0);

    await page.goto("/overview");
    await expect(page.locator(".context-bar")).toHaveCount(0);
    await expect(page.locator(".view-head h1")).toHaveText("总览");
});

test("390 窄屏抽屉：开启、选择总览后自动关闭并进入画面", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const toggle = page.getByRole("button", { name: "开启导航" });
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(page.locator("body")).toHaveClass(/rail-open/);
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const rail = page.locator(".side-rail");
    await rail.getByRole("link", { name: "总览" }).click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.locator("body")).not.toHaveClass(/rail-open/);
    await expect(page.locator("#rail-mask")).toBeHidden();
    await expect(page.getByRole("heading", { name: "总览" })).toBeVisible();
});

test("390 窄屏抽屉：Esc 与遮罩可关闭", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("button", { name: "开启导航" }).click();
    await expect(page.locator("body")).toHaveClass(/rail-open/);
    await page.keyboard.press("Escape");
    await expect(page.locator("body")).not.toHaveClass(/rail-open/);
    await page.getByRole("button", { name: "开启导航" }).click();
    await expect(page.locator("body")).toHaveClass(/rail-open/);
    await page.locator("#rail-mask").click({ position: { x: 300, y: 400 } });
    await expect(page.locator("body")).not.toHaveClass(/rail-open/);
});

for (const route of SHELL_ROUTES) {
    test(`壳画面七档视口无横向溢出：${route}`, async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto(route);
        await expect(page.locator(".workstation-shell")).toBeVisible();
        await expect(page.getByText("Unexpected Application Error!")).toHaveCount(0);
        for (const width of MATRIX_WIDTHS) {
            await page.setViewportSize({ width, height: 900 });
            await expect
                .poll(() =>
                    page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
                )
                .toBe(true);
        }
    });
}
