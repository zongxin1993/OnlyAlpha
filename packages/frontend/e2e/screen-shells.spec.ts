import { expect, test } from "@playwright/test";

// P2 画面壳契约：冻结稿的画面外壳纪律（view-head h1、诚实列表、真实健康徽章、
// 单列断点、移动零溢出、导航锚 redirect）在正式 native 拓扑下逐项可见。
const screens = [
    { path: "/data/inputs", heading: "数据" },
    { path: "/strategies", heading: "策略" },
    { path: "/backtest", heading: "回测" },
    { path: "/system/health", heading: "系统" }
] as const;

test("1440 下四画面 view-head h1 逐项可见，/data 与 /system redirect 生效", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/data");
    await expect(page).toHaveURL(/\/data\/inputs$/);
    await page.goto("/system");
    await expect(page).toHaveURL(/\/system\/health$/);
    for (const screen of screens) {
        await page.goto(screen.path);
        await expect(
            page.getByRole("heading", { level: 1, name: screen.heading, exact: true })
        ).toBeVisible();
    }
});

test("数据画面在 native 真实列表下可读：有配置源则名称可见，无则诚实空态", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/data/inputs");
    const configured = page.getByRole("article");
    const empty = page.getByRole("heading", { name: "尚未配置数据源" });
    await expect(configured.or(empty).first()).toBeVisible();
    if ((await configured.count()) > 0) {
        // 配置源卡片必须给出可读名称，而非匿名骨架。
        await expect(configured.first().locator("h3").first()).toBeVisible();
    }
});

test("系统画面健康徽章来自真实响应：/health/ready 确实发出且渲染与响应一致", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const probe = page.waitForResponse(
        (response) => new URL(response.url()).pathname === "/health/ready"
    );
    await page.goto("/system/health");
    const response = await probe;
    expect(response.status()).toBe(200);
    const body = (await response.json()) as { status: string };
    // exact：默认子串匹配会连探针路径 /health/ready 一起命中。
    await expect(page.getByText(body.status, { exact: true })).toBeVisible();
});

test("1024 策略 detail 单列：主区近全宽且零横向溢出", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 900 });
    await page.goto("/strategies/new");
    await expect(page.getByRole("heading", { level: 1, name: "策略", exact: true })).toBeVisible();
    const main = page.getByRole("main", { name: "策略定义" });
    await expect(main).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true
    );
    // 单列语义：主区宽度接近视口（≥70%），不存在 340px 侧栏并排截断。
    const width = await main.evaluate((element) => element.getBoundingClientRect().width);
    expect(width).toBeGreaterThanOrEqual(0.7 * 1024);
});

test("390 全画面零横向溢出", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const screen of screens) {
        await page.goto(screen.path);
        await expect(
            page.getByRole("heading", { level: 1, name: screen.heading, exact: true })
        ).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
            true
        );
    }
});
