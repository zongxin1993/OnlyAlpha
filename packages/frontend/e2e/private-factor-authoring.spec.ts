import { expect, test } from "@playwright/test";
test("native private Factor authoring saves drafts and preserves exact Revision history through normal UI", async ({
    page
}, testInfo) => {
    const forbidden: string[] = [];
    page.on("request", (request) => {
        if (
            request.method() !== "GET" &&
            /\/api\/v2\/(research\/runs|backtest|strategy-freezes|research\/runtime-generations)/.test(
                request.url()
            )
        )
            forbidden.push(request.url());
    });
    async function editor() {
        await page.getByRole("button", { name: "因子", exact: true }).click();
        await page.getByRole("button", { name: "创建 / 编辑私有因子" }).click();
        return page.getByRole("dialog", { name: "私有 Factor 草稿与历史" });
    }
    await page.goto("/");
    let view = await editor();
    await view.getByRole("button", { name: "新建因子" }).click();
    await view.getByLabel("因子名称").fill("用户创建的动量因子");
    await view.getByLabel("经济依据").fill("观察收盘价动量");
    await view.getByLabel("标签（逗号分隔）").fill("动量, 日线");
    await expect(view.getByRole("button", { name: "发布 Revision", exact: true })).toBeDisabled();
    await view.getByRole("button", { name: "保存草稿", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: /^草稿已保存$/ })).toHaveText(
        "草稿已保存"
    );
    await page.reload();
    view = await editor();
    await view.getByRole("button", { name: "用户创建的动量因子 · 草稿", exact: true }).click();
    await expect(view.getByLabel("经济依据")).toHaveValue("观察收盘价动量");
    await view.getByRole("button", { name: "发布 Revision", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: "Revision 已发布" })).toContainText(
        "Revision 已发布"
    );
    await view.getByRole("button", { name: /查看 Revision 1/ }).click();
    const oldSource = await view
        .getByRole("region", { name: "历史 Revision" })
        .locator("pre")
        .textContent();
    await view.getByLabel("语义版本").fill("2");
    await view
        .getByLabel("Python 源码")
        .fill(
            "def calculate(api, inputs, parameters):\n    return {'value': inputs['close'] * 2}\n"
        );
    await view.getByRole("button", { name: "保存草稿", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: /^草稿已保存$/ })).toHaveText(
        "草稿已保存"
    );
    await view.getByRole("button", { name: "发布 Revision", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: "Revision 已发布" })).toContainText(
        "Revision 已发布"
    );
    await page.reload();
    view = await editor();
    await view.getByRole("button", { name: "用户创建的动量因子 · 已发布", exact: true }).click();
    await expect(view.getByRole("button", { name: /查看 Revision/ })).toHaveCount(2);
    await view.getByRole("button", { name: /查看 Revision 1/ }).click();
    await expect(view.getByRole("region", { name: "历史 Revision" }).locator("pre")).toHaveText(
        oldSource ?? ""
    );
    await view.getByRole("button", { name: /查看 Revision 2/ }).click();
    await expect(view.getByRole("region", { name: "历史 Revision" }).locator("pre")).toContainText(
        "* 2"
    );
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("private-factor-authoring.png") });
    await view.getByRole("button", { name: "关闭", exact: true }).click();
    await expect(page.getByRole("button", { name: "创建 / 编辑私有因子" })).toBeFocused();
    expect(forbidden).toEqual([]);
});
