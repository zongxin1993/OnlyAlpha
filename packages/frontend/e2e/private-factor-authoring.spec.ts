import { readFile, writeFile } from "node:fs/promises";
import { z } from "zod";
import { expect, test } from "@playwright/test";
test("native private Factor authoring preserves content identity through display edits and two versions", async ({
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
    if (process.env.ONLYALPHA_BROWSER_RESTART_PHASE === "restored") {
        const evidence = process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE;
        if (evidence === undefined) throw new Error("canonical native harness evidence required");
        const { oldSource, oldPin } = z
            .strictObject({ oldSource: z.string(), oldPin: z.string() })
            .parse(JSON.parse(await readFile(evidence, "utf8")));
        await page.goto("/");
        const view = await editor();
        await view.getByRole("button", { name: "收盘价趋势强度 · 第 2 版", exact: true }).click();
        await expect(view.getByLabel("用途说明")).toHaveValue("重新整理的价格变化说明");
        await expect(view.getByRole("button", { name: /查看第 .* 版/ })).toHaveCount(2);
        await view.getByRole("button", { name: "查看第 1 版", exact: true }).click();
        const restored = view.getByRole("region", { name: "历史内容版本" });
        await expect(restored.locator("pre")).toHaveText(oldSource);
        await restored.getByText("精确身份", { exact: true }).click();
        await expect(restored.locator("code")).toHaveText(oldPin);
        await page.screenshot({ path: testInfo.outputPath("private-factor-restored.png") });
        expect(forbidden).toEqual([]);
        return;
    }
    await page.goto("/");
    let view = await editor();
    await view.getByRole("button", { name: "新建因子" }).click();
    await expect(view.getByLabel("因子名称", { exact: true })).toHaveValue(/私有因子 \d+/);
    await expect(view.getByLabel("用途说明")).toHaveValue("自定义计算；用途待完善。");
    await view.getByLabel("因子名称", { exact: true }).fill("用户创建的动量因子");
    await view.getByLabel("用途说明").fill("观察收盘价变化");
    await view.getByRole("button", { name: "保存草稿", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: /^草稿已保存$/ })).toBeVisible();
    await page.reload();
    view = await editor();
    await view.getByRole("button", { name: "用户创建的动量因子 · 草稿", exact: true }).click();
    await expect(view.getByLabel("用途说明")).toHaveValue("观察收盘价变化");
    await view.getByRole("button", { name: "发布内容版本", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: "内容版本已发布" })).toBeVisible();
    await view.getByRole("button", { name: "查看第 1 版", exact: true }).click();
    const history = view.getByRole("region", { name: "历史内容版本" });
    const oldSource = await history.locator("pre").textContent();
    await history.getByText("精确身份", { exact: true }).click();
    const oldPin = await history.locator("code").textContent();
    await view.getByLabel("因子名称", { exact: true }).fill("收盘价趋势强度");
    await view.getByLabel("用途说明").fill("重新整理的价格变化说明");
    await view.getByRole("button", { name: "保存名称和用途", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: "名称和用途已保存" })).toBeVisible();
    await expect(view.getByRole("button", { name: /查看第 .* 版/ })).toHaveCount(1);
    await view.getByRole("button", { name: "查看第 1 版", exact: true }).click();
    await history.getByText("精确身份", { exact: true }).click();
    await expect(history.locator("code")).toHaveText(oldPin ?? "");
    await expect(history.locator("pre")).toHaveText(oldSource ?? "");
    await page.reload();
    view = await editor();
    await view.getByRole("button", { name: "收盘价趋势强度 · 第 1 版", exact: true }).click();
    await expect(view.getByLabel("用途说明")).toHaveValue("重新整理的价格变化说明");
    // Source changes publish new content; no human version number is entered.
    await view
        .getByLabel("Python 源码")
        .fill(
            "def calculate(api, inputs, parameters):\n    return {'value': inputs['close'] * 2}\n"
        );
    await view.getByRole("button", { name: "保存草稿", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: /^草稿已保存$/ })).toBeVisible();
    await view.getByRole("button", { name: "发布内容版本", exact: true }).click();
    await expect(view.getByRole("status").filter({ hasText: "内容版本已发布" })).toBeVisible();
    await page.reload();
    view = await editor();
    await view.getByRole("button", { name: "收盘价趋势强度 · 第 2 版", exact: true }).click();
    await expect(view.getByRole("button", { name: /查看第 .* 版/ })).toHaveCount(2);
    await view.getByRole("button", { name: "查看第 1 版", exact: true }).click();
    await expect(view.getByRole("region", { name: "历史内容版本" }).locator("pre")).toHaveText(
        oldSource ?? ""
    );
    await view.getByRole("button", { name: "查看第 2 版", exact: true }).click();
    await expect(view.getByRole("region", { name: "历史内容版本" }).locator("pre")).toContainText(
        "* 2"
    );
    const evidence = process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE;
    if (evidence === undefined) throw new Error("canonical native harness evidence required");
    await writeFile(evidence, JSON.stringify({ oldSource, oldPin }));
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("private-factor-display.png") });
    await view.getByRole("button", { name: "关闭", exact: true }).click();
    await expect(page.getByRole("button", { name: "创建 / 编辑私有因子" })).toBeFocused();
    expect(forbidden).toEqual([]);
});

test("native private Factor contract forms preserve raw contracts and independent modes", async ({
    page
}, testInfo) => {
    const evidence = process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE;
    if (evidence === undefined) throw new Error("canonical native harness evidence required");
    const proof = evidence + ".forms";
    const writes: string[] = [];
    page.on("request", (request) => {
        if (request.method() !== "GET") writes.push(request.url());
    });
    async function openEditor() {
        await page.getByRole("button", { name: "因子", exact: true }).click();
        await page.getByRole("button", { name: "创建 / 编辑私有因子" }).click();
        return page.getByRole("dialog", { name: "私有 Factor 草稿与历史" });
    }
    await page.goto("/");
    let view = await openEditor();
    if (process.env.ONLYALPHA_BROWSER_RESTART_PHASE === "restored") {
        const expected = z
            .object({ input: z.unknown(), fingerprint: z.string() })
            .parse(JSON.parse(await readFile(proof, "utf8")));
        await view.getByRole("button", { name: "契约表单验收 · 第 1 版", exact: true }).click();
        await expect(view.getByLabel("可调参数第 1 项默认值")).toHaveValue("21");
        await expect(view.getByLabel("可调参数第 1 项使用时必须填写")).toBeChecked();
        await expect(view.getByLabel("计算结果第 1 项结果字段名")).toHaveValue("value");
        expect(JSON.parse(await view.getByLabel("输入契约 JSON").inputValue())).toEqual(
            expected.input
        );
        await view.getByRole("button", { name: "查看第 1 版", exact: true }).click();
        const history = view.getByRole("region", { name: "历史内容版本" });
        await history.getByText("精确身份", { exact: true }).click();
        await expect(history.locator("code")).toHaveText(expected.fingerprint);
        expect(writes).toEqual([]);
        return;
    }
    await view.getByRole("button", { name: "新建因子" }).click();
    await view.getByLabel("因子名称", { exact: true }).fill("契约表单验收");
    await expect(view.getByLabel("所需数据第 1 项代码中的名称")).toHaveValue("close");
    await expect(view.getByText("没有可调参数")).toBeVisible();
    await view.getByRole("button", { name: "添加参数", exact: true }).click();
    await view.getByLabel("可调参数第 1 项代码中的名称").fill("scale");
    await view.getByLabel("可调参数第 1 项设置默认值").check();
    await view.getByLabel("可调参数第 1 项默认值").fill("20");
    await expect(view.getByLabel("可调参数第 1 项使用时必须填写")).toBeChecked();
    await view
        .getByLabel("Python 源码")
        .fill(
            "def calculate(api, inputs, parameters):\n    return {'value': inputs['close'] * parameters['scale']}\n"
        );
    const savedSchema = z.object({
        result: z.object({
            draft_fingerprint: z.string(),
            draft: z.object({
                input_contract: z.unknown(),
                parameter_contract: z.unknown(),
                output_contract: z.unknown()
            })
        })
    });
    async function save() {
        const response = page.waitForResponse(
            (r) => r.request().method() === "PUT" && r.url().endsWith("/draft")
        );
        await view.getByRole("button", { name: "保存草稿", exact: true }).click();
        const receipt = savedSchema.parse(await (await response).json());
        await expect(view.getByRole("status").filter({ hasText: /^草稿已保存$/ })).toBeVisible();
        return receipt;
    }
    for (const [title, label] of [
        ["所需数据", "输入契约 JSON"],
        ["可调参数", "参数契约 JSON"],
        ["计算结果", "输出契约 JSON"]
    ]) {
        await view.getByRole("button", { name: title + "高级 JSON", exact: true }).click();
        const original = await view.getByLabel(label).inputValue();
        await view
            .getByLabel(label)
            .fill('{"custom":{"type":"DECIMAL","extension":{"exact":"0.10"}}}');
        await view.getByRole("button", { name: "切换到" + title + "表单", exact: true }).click();
        await expect(
            view.getByRole("region", { name: title }).getByText(/无法无损转换/)
        ).toBeVisible();
        for (const other of ["所需数据", "可调参数", "计算结果"].filter((name) => name !== title))
            await expect(
                view.getByRole("button", { name: other + "高级 JSON", exact: true })
            ).toBeVisible();
        await view.getByLabel(label).fill(original);
        await view.getByRole("button", { name: "切换到" + title + "表单", exact: true }).click();
    }
    await view.getByRole("button", { name: "可调参数高级 JSON" }).click();
    await view.getByLabel("参数契约 JSON").fill('{"scale":{"type":"INTEGER"}}');
    await view.getByRole("button", { name: "切换到可调参数表单" }).click();
    await view.getByLabel("可调参数第 1 项设置默认值").check();
    await view.getByLabel("可调参数第 1 项默认值").fill("20");
    await expect(view.getByRole("group", { name: "确认关联变更" })).toBeVisible();
    await view.getByRole("button", { name: "确认关联变更", exact: true }).click();
    const first = await save();
    expect(first.result.draft.parameter_contract).toEqual({
        scale: { type: "INTEGER", required: true, default: 20 }
    });
    const before = writes.length;
    for (const title of ["所需数据", "可调参数", "计算结果"]) {
        await view.getByRole("button", { name: title + "高级 JSON", exact: true }).click();
        await view.getByRole("button", { name: "切换到" + title + "表单", exact: true }).click();
    }
    await view.getByLabel("所需数据第 1 项允许缺失").check();
    await view.getByRole("button", { name: "所需数据高级 JSON" }).click();
    await view.getByRole("button", { name: "切换到所需数据表单" }).click();
    await view.getByLabel("所需数据第 1 项允许缺失").uncheck();
    expect(writes).toHaveLength(before);
    const unchanged = await save();
    expect(unchanged.result.draft_fingerprint).toBe(first.result.draft_fingerprint);
    expect(unchanged.result.draft).toEqual(first.result.draft);
    const complex =
        ' { "close": {"type":"DECIMAL","extension":{"steps":[2,1,null],"exact":"0.10"}} } ';
    await view.getByRole("button", { name: "所需数据高级 JSON" }).click();
    await view.getByLabel("输入契约 JSON").fill(complex);
    await view.getByRole("button", { name: "切换到所需数据表单" }).click();
    await expect(view.getByText(/当前结构无法无损转换/)).toBeVisible();
    await expect(view.getByLabel("输入契约 JSON")).toHaveValue(complex);
    await view.getByLabel("可调参数第 1 项默认值").fill("21");
    const changed = await save();
    expect(changed.result.draft.input_contract).toEqual(JSON.parse(complex));
    expect(changed.result.draft_fingerprint).not.toBe(first.result.draft_fingerprint);
    await view.getByRole("button", { name: "可调参数高级 JSON" }).click();
    const original = await view.getByLabel("参数契约 JSON").inputValue();
    const acceptedInputText = await view.getByLabel("输入契约 JSON").inputValue();
    const beforeInvalid = writes.length;
    await view.getByLabel("参数契约 JSON").fill('{"scale":{"type":"INTEGER","type":"DECIMAL"}}');
    await expect(view.getByRole("alert").filter({ hasText: /JSON 字段重复/ })).toBeVisible();
    await view.getByRole("button", { name: "保存草稿", exact: true }).click();
    expect(writes).toHaveLength(beforeInvalid);
    await expect(view.getByLabel("输入契约 JSON")).toHaveValue(acceptedInputText);
    await view.getByLabel("参数契约 JSON").fill(original);
    await view.getByRole("button", { name: "切换到可调参数表单" }).click();
    const publication = page.waitForResponse(
        (r) => r.request().method() === "POST" && r.url().endsWith("/revisions")
    );
    await view.getByRole("button", { name: "发布内容版本", exact: true }).click();
    const published = z
        .object({ result: z.object({ revision: z.object({ revision_fingerprint: z.string() }) }) })
        .parse(await (await publication).json());
    await expect(view.getByRole("status").filter({ hasText: "内容版本已发布" })).toBeVisible();
    await page.reload();
    view = await openEditor();
    await view.getByRole("button", { name: "契约表单验收 · 第 1 版", exact: true }).click();
    await expect(view.getByLabel("可调参数第 1 项默认值")).toHaveValue("21");
    expect(JSON.parse(await view.getByLabel("输入契约 JSON").inputValue())).toEqual(
        JSON.parse(complex)
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await view.getByLabel("计算结果第 1 项结果字段名").focus();
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("factor-contract-forms-mobile.png") });
    await page.setViewportSize({ width: 1440, height: 1100 });
    await view.getByLabel("输入契约 JSON").focus();
    await page.screenshot({ path: testInfo.outputPath("factor-contract-forms.png") });
    await writeFile(
        proof,
        JSON.stringify({
            input: z.unknown().parse(JSON.parse(complex)),
            fingerprint: published.result.revision.revision_fingerprint
        })
    );
    expect(
        writes.some((url) =>
            /\/api\/v2\/(research\/runs|backtest|strategy-freezes|research\/runtime-generations)/.test(
                url
            )
        )
    ).toBe(false);
});
