import { expect, test, type Page } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";

const name = "沪市封存日线";
async function settings(page: Page) {
    await page.getByRole("button", { name: "全局设置" }).click();
    return page.getByRole("dialog", { name: "设置" });
}
async function selectDay(page: Page, retained: boolean) {
    const panel = await settings(page);
    await panel.getByRole("tab", { name: "图表", exact: true }).click();
    const section = panel
        .locator("details")
        .filter({ has: page.locator("summary").filter({ hasText: "行情设置" }) });
    if ((await section.getAttribute("open")) === null) await section.locator("summary").click();
    const sources = section.getByLabel("数据源", { exact: true });
    const choice = sources.locator("option").filter({ hasText: name });
    await expect(choice).toHaveCount(1);
    await sources.selectOption({ label: await choice.innerText() });
    await panel.getByRole("button", { name: "关闭设置" }).click();
    await expect(page.getByRole("combobox", { name: "时间周期" })).toHaveValue("day");
    const day = page.getByRole("region", { name: "封存日线" });
    await day.getByLabel("证券代码").fill("600000");
    await day.getByRole("button", { name: retained ? "查已封存证券" : "查源端证券" }).click();
    await day.getByRole("button", { name: "600000.XSHG", exact: true }).click();
    return day;
}
test("封存日线通过数据源、原操作和图表读取", async ({ page }) => {
    test.skip(process.env.ONLYALPHA_BROWSER_TUSHARE_DAILY_INPUT !== "1", "需要固定外部日线输入");
    test.setTimeout(120000);
    const restored = process.env.ONLYALPHA_BROWSER_RESTART_PHASE === "restored";
    const sharedEvidence = process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE;
    if (sharedEvidence === undefined) throw new Error("需要原生重启验证入口");
    const evidence = sharedEvidence + ".tushare-day";
    let collections = 0;
    page.on("request", (r) => {
        if (
            r.method() === "POST" &&
            new URL(r.url()).pathname === "/api/v2/market-data/acquisitions"
        )
            collections++;
    });
    await page.goto("/");
    if (!restored) {
        const panel = await settings(page);
        await panel.getByRole("tab", { name: "数据源", exact: true }).click();
        await panel.getByRole("tab", { name: "添加数据源", exact: true }).click();
        await panel.getByRole("button", { name: /Tushare 沪深股票历史日线/ }).click();
        await panel.getByLabel("显示名称").fill(name);
        await panel.getByRole("button", { name: "创建数据源", exact: true }).click();
        await expect(panel.getByRole("heading", { name, exact: true })).toBeVisible();
        await panel.getByLabel("更换 Token").fill("onlyalpha-controlled-daily-input");
        await panel.getByRole("button", { name: "更换凭据" }).click();
        await expect(panel.getByText("已配置 · generation 1")).toBeVisible();
        await panel.getByRole("button", { name: "发布 Revision" }).click();
        await expect(panel.getByText(/^R1 ·/)).toBeVisible();
        await panel.getByRole("button", { name: "测试连接", exact: true }).click();
        await expect(panel.getByText(/尝试 .+ · 探测标的 600000.XSHG/)).toBeVisible();
        await panel.getByRole("button", { name: "关闭设置" }).click();
        const day = await selectDay(page, false);
        await expect(page.getByTestId("market-data-status")).toContainText("尚无封存日线");
        expect(collections).toBe(0);
        await day.getByText("采集日线", { exact: true }).click();
        await day.getByLabel("开始日期（UTC）").fill("2025-01-03");
        await day.getByLabel("结束日期（UTC，不含）").fill("2025-01-07");
        await day.getByRole("button", { name: "开始采集" }).click();
        await expect(day.getByRole("status")).toHaveText("已封存");
        await expect(page.getByTestId("market-data-status")).toHaveAttribute(
            "data-loaded-bar-count",
            "2"
        );
        const operation = await day.locator("code").innerText();
        const revision = await page
            .getByTestId("market-data-status")
            .getAttribute("data-sealed-revision-id");
        expect(revision).toBeTruthy();
        writeFileSync(evidence, JSON.stringify({ operation, revision }));
        await page.reload();
    }
    const expected = JSON.parse(readFileSync(evidence, "utf8")) as {
        operation: string;
        revision: string;
    };
    const day = await selectDay(page, true);
    await expect(
        page.getByText("1 日封存历史无法保存为工作区，可用原采集编号恢复。")
    ).toBeVisible();
    await page.getByRole("button", { name: "工作区", exact: true }).click();
    await expect(page.getByRole("menuitem", { name: "保存工作区" })).toHaveAttribute(
        "aria-disabled",
        "true"
    );
    await page.keyboard.press("Escape");
    if (restored) {
        await day.getByText("按原操作编号查询", { exact: true }).click();
        await day.getByLabel("原操作编号").fill(expected.operation);
    } else {
        await expect(day.locator("code")).toHaveText(expected.operation);
    }
    await day.getByRole("button", { name: "查询原操作", exact: true }).click();
    await expect(day.getByRole("status")).toHaveText("已封存");
    await expect(day.getByLabel("最新封存日线")).toHaveText(
        /收盘 12(?:\.0+)? · 成交量 12345(?:\.0+)?$/
    );
    const status = page.getByTestId("market-data-status");
    await expect(status).toContainText("已加载封存日线");
    await expect(status).toHaveAttribute("data-loaded-bar-count", "2");
    await expect(status).toHaveAttribute("data-sealed-revision-id", expected.revision);
    await expect(status).toHaveAttribute("data-temporary-window-fingerprint", "");
    expect(collections).toBe(restored ? 0 : 1);
});
