import { readFile, writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { z } from "zod";

// Existing owner checks allow 120s for completion. Authoring/preparation have
// separate bounds below; this aggregate limit does not relax the Run budget.
test("normal backtest works without Agent and reopens the same run after restart", async ({
    page
}, testInfo) => {
    test.setTimeout(300_000);
    page.setDefaultTimeout(30_000);
    const sharedEvidence = process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE;
    if (sharedEvidence === undefined) throw new Error("canonical native restart harness required");
    const evidence = sharedEvidence + ".backtest";
    const agentWrites: string[] = [];
    page.on("request", (request) => {
        if (request.method() !== "GET" && /\/api\/v\d+\/(agent|model)/.test(request.url()))
            agentWrites.push(request.url());
    });
    async function navigateProduct(label: string) {
        await page.getByRole("button", { name: "更多功能", exact: true }).click();
        await page.getByRole("menuitem", { name: label, exact: true }).click();
    }
    async function resultView() {
        await expect(page.getByRole("heading", { name: "回测结果", exact: true })).toBeVisible({
            timeout: 120_000
        });
        const view = page.getByRole("main", { name: "策略回测" });
        await expect(view.getByText("净收益（USDT）", { exact: true })).toBeVisible();
        await expect(view.getByText("最大回撤", { exact: true })).toBeVisible();
        await expect(view.getByText("手续费（USDT）", { exact: true })).toBeVisible();
        await expect(view.getByText("成交明细", { exact: true })).toBeVisible();
        await expect(view.getByText("期末持仓", { exact: true })).toBeVisible();
        await expect(view.locator(".backtest-metrics")).not.toContainText("暂不可用");
        const trades = view.getByRole("table").filter({
            has: page.getByRole("columnheader", { name: "成交时间（UTC）", exact: true })
        });
        const positions = view.getByRole("table").filter({
            has: page.getByRole("columnheader", { name: "持仓数量（BTC）", exact: true })
        });
        const details = view.getByRole("table").filter({
            has: page.getByText("样本（UTC）", { exact: true })
        });
        await expect(trades).toHaveCount(1);
        await expect(positions).toHaveCount(1);
        await expect(details).toHaveCount(1);
        await expect(trades.getByRole("cell", { name: "买入", exact: true }).first()).toBeVisible();
        return {
            path: new URL(page.url()).pathname,
            metrics: await view.locator(".backtest-metrics").innerText(),
            tables: [
                await trades.innerText(),
                await positions.innerText(),
                await details.innerText()
            ]
        };
    }
    await page.goto("/");
    if (process.env.ONLYALPHA_BROWSER_RESTART_PHASE === "restored") {
        const previous = z
            .strictObject({ path: z.string(), metrics: z.string(), tables: z.array(z.string()) })
            .parse(JSON.parse(await readFile(evidence, "utf8")));
        await navigateProduct("回测");
        const original = page
            .getByRole("row")
            .filter({ has: page.locator(`a[href="${previous.path}"]`) });
        await expect(original.getByText("已完成", { exact: true })).toBeVisible();
        await original.getByRole("link", { name: "查看回测", exact: true }).click();
        expect(await resultView()).toEqual(previous);
        await page.screenshot({
            path: testInfo.outputPath("backtest-restored.png"),
            fullPage: true
        });
        expect(agentWrites).toEqual([]);
        return;
    }
    await page.getByRole("button", { name: "因子", exact: true }).click();
    await page.getByRole("button", { name: "创建 / 编辑私有因子" }).click();
    const editor = page.getByRole("dialog", { name: "私有 Factor 草稿与历史" });
    await editor.getByRole("button", { name: "新建因子", exact: true }).click();
    await editor.getByLabel("因子名称", { exact: true }).fill("回测价量动量");
    await editor.getByLabel("用途说明").fill("已收盘一分钟行情的价格变化与相对成交量");
    await editor
        .getByLabel("Python 源码")
        .fill(
            "def calculate(api, inputs, parameters):\n" +
                "    return {'value': api.mul(api.sub(api.div(inputs['close'], inputs['close_lag_20']), parameters['literal_1']), api.div(inputs['volume'], inputs['volume_mean_20']))}\n"
        );
    for (const [title, label, contract] of [
        [
            "所需数据",
            "输入契约 JSON",
            Object.fromEntries(
                ["close", "close_lag_20", "volume", "volume_mean_20"].map((name) => [
                    name,
                    { type: "DECIMAL", missing: true }
                ])
            )
        ],
        [
            "可调参数",
            "参数契约 JSON",
            { literal_1: { type: "DECIMAL", required: false, default: "1" } }
        ],
        ["计算结果", "输出契约 JSON", { value: { type: "DECIMAL", missing: true } }]
    ] as const) {
        await editor.getByRole("button", { name: title + "高级 JSON", exact: true }).click();
        await editor.getByLabel(label).fill(JSON.stringify(contract));
    }
    await editor.getByRole("button", { name: "保存草稿", exact: true }).click();
    await expect(editor.getByRole("status").filter({ hasText: /^草稿已保存$/ })).toBeVisible();
    await editor.getByRole("button", { name: "发布内容版本", exact: true }).click();
    await expect(editor.getByRole("status").filter({ hasText: "内容版本已发布" })).toBeVisible();
    await editor.getByRole("button", { name: "关闭", exact: true }).click();
    await page
        .getByRole("dialog", { name: "指标 / 因子目录", exact: true })
        .getByRole("button", { name: "关闭目录", exact: true })
        .click();
    await navigateProduct("策略");
    await page.getByRole("link", { name: "新建策略", exact: true }).click();
    await page.getByRole("combobox", { name: "已保存因子", exact: true }).click();
    await page.getByText("回测价量动量", { exact: true }).click();
    await expect(page.getByRole("button", { name: "保存策略定义", exact: true })).toBeEnabled();
    await page.getByRole("textbox", { name: "策略名称", exact: true }).fill("价量动量普通回测");
    await page.getByRole("button", { name: "保存策略定义", exact: true }).click();
    await page.getByRole("link", { name: "配置回测", exact: true }).click();
    await expect(page.getByText("2025-01-03 00:00 至 12:00", { exact: true })).toBeVisible();
    await expect(page.getByText("手续费每边 0.1%；滑点每边 0.02%", { exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "回测行情数据源", exact: true }).click();
    // This harness declares one existing Source with controlled external input.
    // Strategy creation, preparation and Run submission all remain normal UI actions.
    await expect(page.getByRole("option")).toHaveCount(1);
    await page.getByRole("combobox", { name: "回测行情数据源", exact: true }).press("ArrowDown");
    await page.getByRole("combobox", { name: "回测行情数据源", exact: true }).press("Enter");
    await page.getByRole("button", { name: "确认策略并准备回测", exact: true }).click();
    const start = page.getByRole("button", { name: "开始回测", exact: true });
    const readyDeadline = Date.now() + 120_000;
    const readUnavailable = page
        .getByRole("alert")
        .filter({ hasText: "暂时无法读取当前记录。已有策略与回测仍然保留，请重新查看。" });
    await expect
        .poll(async () => (await start.isEnabled()) || (await readUnavailable.isVisible()), {
            timeout: 120_000
        })
        .toBe(true);
    if (await readUnavailable.isVisible()) {
        // Normal user recovery observes the same operation. It never resubmits
        // preparation, and the original READY budget continues to apply.
        const remaining = readyDeadline - Date.now();
        expect(remaining).toBeGreaterThan(0);
        await page
            .getByRole("button", { name: "重新查看", exact: true })
            .click({ timeout: remaining });
    }
    const remaining = readyDeadline - Date.now();
    expect(remaining).toBeGreaterThan(0);
    await expect(start).toBeEnabled({ timeout: remaining });
    expect(Date.now()).toBeLessThanOrEqual(readyDeadline);
    await page.screenshot({ path: testInfo.outputPath("backtest-ready.png"), fullPage: true });
    await start.focus();
    await expect(start).toBeFocused();
    await page.keyboard.press("Enter");
    const result = await resultView();
    await page.reload();
    expect(await resultView()).toEqual(result);
    await page.getByRole("link", { name: "回测记录", exact: true }).click();
    const original = page
        .getByRole("row")
        .filter({ has: page.locator(`a[href="${result.path}"]`) });
    await expect(original.getByText("已完成", { exact: true })).toBeVisible();
    await original.getByRole("link", { name: "查看回测", exact: true }).click();
    expect(await resultView()).toEqual(result);
    await writeFile(evidence, JSON.stringify(result));
    await page.screenshot({ path: testInfo.outputPath("backtest-result.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("backtest-narrow.png"), fullPage: true });
    expect(agentWrites).toEqual([]);
});
