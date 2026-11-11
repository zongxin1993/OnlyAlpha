import { expect, test } from "@playwright/test";
import { TemporaryChartStudyBatchSchema } from "../src/api/chartStudies/http.generated";

const groups = [
    [
        ["wma", "2", "WMA", 1],
        ["sma", "2", "SMA", 1],
        ["roc", "2", "ROC", 1]
    ],
    [
        ["ema", "2", "EMA", 1],
        ["rsi", "3", "RSI", 1],
        ["atr", "4", "ATR", 1],
        ["macd", "3", "MACD", 3]
    ],
    [
        ["bollinger", "2", "布林带", 3],
        ["rolling_volatility", "2", "价格波动率", 1],
        ["zscore", "2", "Z-Score", 1],
        ["obv", "2", "OBV", 1]
    ],
    [
        ["vwap", "3", "VWAP · UTC交易日", 1],
        ["stochastic", "3", "Stochastic · 慢速", 2],
        ["rolling_return", "2", "滚动收益率", 1]
    ]
] as const;

test("Chart renders all fourteen Rust indicator families", async ({ page }) => {
    test.skip(
        process.env.ONLYALPHA_BROWSER_CHART_SMA_INPUT !== "1",
        "Requires the controlled Source in onlyalpha-dev"
    );
    test.setTimeout(120_000);
    const displayed = new Map<string, string>();
    page.on("response", async (response) => {
        if (
            !response.ok() ||
            !response.url().endsWith("/api/v2/chart/temporary-studies/evaluate-batch")
        )
            return;
        const { results } = TemporaryChartStudyBatchSchema.parse(await response.json());
        for (const row of results) {
            if (row.status !== "REJECTED" && row.evaluation.query_status === "DISPLAYABLE") {
                const { calculation } = row.evaluation;
                displayed.set(
                    `${calculation.type_id}@${calculation.semantic_version}`,
                    calculation.implementation_fingerprint
                );
            }
        }
    });

    await page.goto("/");
    const chart = page.getByTestId("price-chart");
    const instances = page.getByTestId("chart-study-instance");
    await expect(chart).toBeVisible();
    for (const group of groups) {
        let count = 0;
        for (const [type, version, label, seriesCount] of group) {
            const id = `onlyalpha.indicator.${type}`;
            await page.getByRole("button", { name: "目录", exact: true }).click();
            const catalog = page.getByRole("dialog", { name: "指标 / 因子目录" });
            await catalog.getByRole("searchbox", { name: "搜索指标或因子" }).fill(id);
            await catalog
                .getByRole("button", { name: `选择 ${label} · 配置草稿`, exact: true })
                .click();
            const editor = page.getByRole("dialog", { name: "指标 / 因子参数配置" });
            await editor.getByRole("button", { name: "添加", exact: true }).click();
            await expect.poll(() => displayed.get(`${id}@${version}`)).toMatch(/^[0-9a-f]{64}$/);
            count += seriesCount;
            await expect(chart).toHaveAttribute("data-study-series-count", String(count));
        }
        let remaining: number = group.length;
        while (remaining > 0) {
            await instances.last().getByRole("button", { name: "移除配置", exact: true }).click();
            remaining -= 1;
        }
        await expect(instances).toHaveCount(0);
        await expect(chart).toHaveAttribute("data-study-series-count", "0");
    }
});
