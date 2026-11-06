import { readFile, writeFile } from "node:fs/promises";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { z } from "zod";

import {
    observeRuntimePrefix,
    requirePreservedPrefix,
    RuntimePrefixSchema,
    type RuntimePrefix
} from "./support/backtest-runtime";

type Acceptance =
    "performance" | "functional" | "functional-cancel" | "functional-running-recovery";
const immutableRun = z.strictObject({
    run_id: z.uuid(),
    strategy_fingerprint: z.string().regex(/^[0-9a-f]{64}$/),
    preparation_command_id: z.uuid(),
    accepted_at: z.string()
});
const observedRun = z.object({ ...immutableRun.shape, state: z.string() });
const resultSnapshot = z.strictObject({
    path: z.string(),
    metrics: z.string(),
    tables: z.array(z.string())
});
const lifecycleEvidence = z.strictObject({
    kind: z.enum(["CANCELLED", "RUNNING"]),
    path: z.string(),
    originalPreparation: z.string(),
    run: immutableRun,
    prefix: RuntimePrefixSchema,
    result: resultSnapshot.nullable()
});

// Produced after the original host has positively drained by the read-only
// Rust VerifiedReplaySnapshot owner. Natural completion cannot satisfy this fence.
const pausedRuntime = z.object({
    schema_version: z.literal(1),
    run_id: z.uuid(),
    state: z.object({
        status: z.literal("PAUSED"),
        input_finished: z.literal(false),
        input_cancelled: z.boolean().optional()
    }),
    replay_prefix: z
        .array(
            z.object({
                sequence: z.number().int().positive(),
                digest: z.string().regex(/^[0-9a-f]{64}$/)
            })
        )
        .min(1)
        .max(16),
    steps: z
        .array(
            z.object({
                kind: z.string(),
                status: z.string(),
                input_finished: z.boolean(),
                input_cancelled: z.boolean()
            })
        )
        .min(1)
});

// Every case owns the same normal UI journey and original 300s aggregate budget.
async function backtestJourney(page: Page, testInfo: TestInfo, acceptance: Acceptance) {
    const journeyDeadline = Date.now() + 300_000;
    test.setTimeout(300_000);
    page.setDefaultTimeout(30_000);
    const sharedEvidence = process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE;
    if (sharedEvidence === undefined) throw new Error("canonical native restart harness required");
    const suffix = {
        performance: ".backtest",
        functional: ".backtest-functional",
        "functional-cancel": ".backtest-functional-cancel",
        "functional-running-recovery": ".backtest-functional-running-recovery"
    }[acceptance];
    const qualifier = {
        performance: "",
        functional: "（功能验收）",
        "functional-cancel": "（取消验收）",
        "functional-running-recovery": "（运行中恢复验收）"
    }[acceptance];
    const evidence = sharedEvidence + suffix;
    const factorName = "回测价量动量" + qualifier;
    const strategyName = "价量动量普通回测" + qualifier;
    const runObservations = new Map<string, z.infer<typeof observedRun>>();
    const observationErrors: string[] = [];
    const backtestWrites: string[] = [];
    page.on("response", (response) => {
        if (
            response.status() !== 200 ||
            !/^\/api\/v2\/backtest\/runs\/[0-9a-f-]+$/.test(new URL(response.url()).pathname)
        )
            return;
        void response
            .json()
            .then((body: unknown) => {
                const value = observedRun.parse(body);
                runObservations.set(value.run_id, value);
            })
            .catch((error: unknown) => {
                observationErrors.push(String(error));
            });
    });
    page.on("request", (request) => {
        const path = new URL(request.url()).pathname;
        if (request.method() !== "GET" && path.startsWith("/api/v2/backtest/"))
            backtestWrites.push(path);
    });
    const agentWrites: string[] = [];
    const confirmationObservations: {
        command_id: string;
        backtest_command_id: string;
        reserved_run_id: string;
    }[] = [];
    const confirmationErrors: string[] = [];
    page.on("response", async (response) => {
        const path = new URL(response.url()).pathname;
        if (
            response.status() !== 200 ||
            !path.startsWith("/api/v2/backtest/preparations/commands/")
        )
            return;
        const projection = z
            .object({
                state: z.string(),
                phase: z.string(),
                command_id: z.uuid(),
                backtest_command_id: z.uuid(),
                reserved_run_id: z.uuid(),
                run_id: z.uuid().nullable(),
                backtest_outcome: z.string(),
                readiness: z.object({ state: z.string() })
            })
            .parse(await response.json());
        if (
            projection.state === "RUNNING" &&
            projection.phase === "CONFIRMING" &&
            projection.run_id === null
        ) {
            if (
                projection.backtest_outcome !== "OUTCOME_UNKNOWN" ||
                projection.readiness.state !== "NOT_APPLICABLE"
            )
                confirmationErrors.push("确认仍在执行时返回了已确定未提交或重新生成的 readiness。");
            confirmationObservations.push({
                command_id: projection.command_id,
                backtest_command_id: projection.backtest_command_id,
                reserved_run_id: projection.reserved_run_id
            });
        }
    });
    page.on("request", (request) => {
        if (request.method() !== "GET" && /\/api\/v\d+\/(agent|model)/.test(request.url()))
            agentWrites.push(request.url());
    });
    async function navigateProduct(label: string) {
        await page.getByRole("button", { name: "更多功能", exact: true }).click();
        await page.getByRole("menuitem", { name: label, exact: true }).click();
    }
    async function resultView(requireBuy = true) {
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
        if (requireBuy)
            await expect(
                trades.getByRole("cell", { name: "买入", exact: true }).first()
            ).toBeVisible();
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
    await page.getByRole("button", { name: "更多功能", exact: true }).click();
    const productMenu = page.getByRole("menu");
    await expect(productMenu.getByRole("menuitem", { name: "策略", exact: true })).toBeVisible();
    await expect(productMenu.getByRole("menuitem", { name: "因子研究", exact: true })).toHaveCount(
        0
    );
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "全局设置", exact: true }).click();
    const settings = page.getByRole("dialog", { name: "设置", exact: true });
    await expect(settings.getByRole("tab", { name: "数据源", exact: true })).toBeVisible();
    await expect(settings.getByRole("tab", { name: /模型|Agent/ })).toHaveCount(0);
    await settings.getByRole("button", { name: "关闭设置", exact: true }).click();
    if (
        process.env.ONLYALPHA_BROWSER_RESTART_PHASE === "restored" &&
        (acceptance === "functional-cancel" || acceptance === "functional-running-recovery")
    ) {
        const previous = lifecycleEvidence.parse(JSON.parse(await readFile(evidence, "utf8")));
        expect(previous.kind).toBe(acceptance === "functional-cancel" ? "CANCELLED" : "RUNNING");
        expect(previous.path).toBe(`/backtest/runs/${previous.run.run_id}`);
        expect(previous.originalPreparation).toBe(
            `/backtest/preparations/${previous.run.preparation_command_id}`
        );
        if (previous.kind === "RUNNING") {
            const pause = pausedRuntime.parse(
                JSON.parse(await readFile(evidence + ".pause", "utf8"))
            );
            expect(pause.run_id).toBe(previous.run.run_id);
            expect(pause.state.input_cancelled).not.toBe(true);
            expect(pause.steps.at(-1)).toEqual({
                kind: "PAUSE",
                status: "PAUSED",
                input_finished: false,
                input_cancelled: false
            });
            expect(pause.replay_prefix.slice(0, previous.prefix.replay.length)).toEqual(
                previous.prefix.replay
            );
            await testInfo.attach("host-drained-paused-runtime", {
                body: JSON.stringify(pause),
                contentType: "application/json"
            });
        }
        await navigateProduct("回测");
        const original = page
            .getByRole("row")
            .filter({ has: page.locator(`a[href="${previous.path}"]`) });
        if (previous.kind === "CANCELLED")
            await expect(original.getByText("已取消", { exact: true })).toBeVisible();
        await original.getByRole("link", { name: "查看回测", exact: true }).click();
        expect(new URL(page.url()).pathname).toBe(previous.path);
        const result = await resultView(previous.kind !== "CANCELLED");
        expect(result.path).toBe(previous.path);
        if (previous.kind === "CANCELLED") {
            await expect(
                page.getByText("回测已取消，以下为已完成部分的结果", { exact: true })
            ).toBeVisible();
            expect(result).toEqual(previous.result);
        } else {
            await expect(page.getByText("已完成", { exact: true })).toBeVisible();
        }
        await expect
            .poll(() => runObservations.get(previous.run.run_id)?.state)
            .toBe(previous.kind === "CANCELLED" ? "CANCELLED" : "COMPLETED");
        const current = runObservations.get(previous.run.run_id);
        expect(current).toBeDefined();
        expect(
            current === undefined
                ? null
                : {
                      run_id: current.run_id,
                      strategy_fingerprint: current.strategy_fingerprint,
                      preparation_command_id: current.preparation_command_id,
                      accepted_at: current.accepted_at
                  }
        ).toEqual(previous.run);
        expect(current?.state).toBe(previous.kind === "CANCELLED" ? "CANCELLED" : "COMPLETED");
        const after = await observeRuntimePrefix(
            previous.run.run_id,
            previous.run.strategy_fingerprint,
            journeyDeadline
        );
        expect(after.state).toBe("OBSERVED");
        if (after.state !== "OBSERVED") throw new Error("重启后原 Ready 前缀不可读取。");
        requirePreservedPrefix(previous.prefix, after);
        await testInfo.attach("restored-runtime-prefix", {
            body: JSON.stringify(after),
            contentType: "application/json"
        });
        expect(backtestWrites).toEqual([]);
        expect(observationErrors).toEqual([]);
        expect(agentWrites).toEqual([]);
        await page.screenshot({
            path: testInfo.outputPath("backtest-lifecycle-restored.png"),
            fullPage: true
        });
        return;
    }
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
    await editor.getByLabel("因子名称", { exact: true }).fill(factorName);
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
    await page.getByText(factorName, { exact: true }).click();
    await expect(page.getByRole("button", { name: "保存策略定义", exact: true })).toBeEnabled();
    await page.getByRole("textbox", { name: "策略名称", exact: true }).fill(strategyName);
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
    const canStart = async () => (await start.isVisible()) && (await start.isEnabled());
    const readyDeadline = Date.now() + 120_000;
    const readUnavailable = page
        .getByRole("alert")
        .filter({ hasText: "暂时无法读取当前记录。已有策略与回测仍然保留，请重新查看。" });
    await expect
        .poll(
            async () => {
                if (await canStart()) return true;
                // Recovery only observes the same operation through the normal UI;
                // preparation is never resubmitted and its original budget continues.
                const observe = page.getByRole("button", { name: "重新查看", exact: true });
                if ((await readUnavailable.isVisible()) && (await observe.isEnabled())) {
                    const remaining = readyDeadline - Date.now();
                    if (remaining > 0) await observe.click({ timeout: remaining });
                }
                return canStart();
            },
            { timeout: 120_000 }
        )
        .toBe(true);
    expect(Date.now()).toBeLessThanOrEqual(readyDeadline);
    await page.screenshot({ path: testInfo.outputPath("backtest-ready.png"), fullPage: true });
    const originalPreparation = new URL(page.url()).pathname;
    await start.focus();
    await expect(start).toBeFocused();
    await page.keyboard.press("Enter");
    const runDeadline = acceptance === "performance" ? Date.now() + 120_000 : journeyDeadline;
    const resultHeading = page.getByRole("heading", { name: "回测结果", exact: true });
    const observeStart = page.getByRole("button", { name: "查看任务进度", exact: true });
    const unfinishedAction = page
        .getByRole("alert")
        .filter({ hasText: "本次操作暂未完成。已有记录仍然保留，请重新查看当前进度。" });
    let startReview: "NONE" | "READING" | "CONFIRMED" = "NONE";
    const observeOriginalRun = async () => {
        if (await resultHeading.isVisible()) return true;
        if (startReview === "NONE" && (await unfinishedAction.isVisible()) && (await canStart())) {
            expect(new URL(page.url()).pathname).toBe(originalPreparation);
            startReview = "READING";
            const remaining = runDeadline - Date.now();
            if (remaining > 0)
                await page
                    .getByRole("button", { name: "重新查看", exact: true })
                    .click({ timeout: remaining });
            return false;
        }
        if (startReview === "READING" && (await canStart())) {
            // One explicit recovery: a normal reread must show the same
            // original preparation READY again before another confirmation.
            expect(new URL(page.url()).pathname).toBe(originalPreparation);
            await expect(page.getByText("可以开始回测", { exact: true })).toBeVisible();
            startReview = "CONFIRMED";
            await start.focus();
            await expect(start).toBeFocused();
            await page.keyboard.press("Enter");
            return false;
        }
        // UNKNOWN is recovered by observing the original command through the
        // normal UI. This action never sends a second submission.
        if ((await observeStart.isVisible()) && (await observeStart.isEnabled())) {
            const remaining = runDeadline - Date.now();
            if (remaining > 0) await observeStart.click({ timeout: remaining });
        }
        return resultHeading.isVisible();
    };
    if (acceptance === "functional-cancel" || acceptance === "functional-running-recovery") {
        let interruption:
            { run: z.infer<typeof immutableRun>; prefix: RuntimePrefix; path: string } | undefined;
        await expect
            .poll(
                async () => {
                    if (await observeOriginalRun())
                        throw new Error("回测在运行中故障前置屏障之前已完成。");
                    const path = new URL(page.url()).pathname;
                    const match = /^\/backtest\/runs\/([0-9a-f-]+)$/.exec(path);
                    if (match?.[1] === undefined) return false;
                    const value = runObservations.get(match[1]);
                    if (value === undefined) return false;
                    if (["COMPLETED", "FAILED", "CANCELLED"].includes(value.state))
                        throw new Error(`前置任务已终止：${value.state}`);
                    if (
                        value.state !== "RUNNING" ||
                        !(await page
                            .getByRole("button", { name: "取消回测", exact: true })
                            .isVisible())
                    )
                        return false;
                    expect(originalPreparation).toBe(
                        `/backtest/preparations/${value.preparation_command_id}`
                    );
                    const prefix = await observeRuntimePrefix(
                        value.run_id,
                        value.strategy_fingerprint,
                        journeyDeadline
                    );
                    await testInfo.attach("runtime-prefix-observation", {
                        body: JSON.stringify(prefix),
                        contentType: "application/json"
                    });
                    if (prefix.state !== "OBSERVED") return false;
                    // The visible RUNNING state alone cannot establish an executed prefix.
                    await expect(
                        page.getByRole("button", { name: "取消回测", exact: true })
                    ).toBeEnabled();
                    interruption = {
                        path,
                        prefix,
                        run: {
                            run_id: value.run_id,
                            strategy_fingerprint: value.strategy_fingerprint,
                            preparation_command_id: value.preparation_command_id,
                            accepted_at: value.accepted_at
                        }
                    };
                    return true;
                },
                { timeout: Math.max(1, journeyDeadline - Date.now()) }
            )
            .toBe(true);
        if (interruption === undefined) throw new Error("未建立实际执行前缀屏障。");
        expect(confirmationErrors).toEqual([]);
        expect(observationErrors).toEqual([]);
        for (const observed of confirmationObservations)
            expect(interruption.run.run_id).toBe(observed.reserved_run_id);
        if (acceptance === "functional-running-recovery") {
            await writeFile(
                evidence,
                JSON.stringify({
                    kind: "RUNNING",
                    ...interruption,
                    originalPreparation,
                    result: null
                })
            );
            await testInfo.attach("running-before-host-stop", {
                body: JSON.stringify(interruption),
                contentType: "application/json"
            });
            expect(agentWrites).toEqual([]);
            return;
        }
        const selected = interruption;
        const cancellation = page.waitForResponse(
            (response) =>
                new URL(response.url()).pathname ===
                    `/api/v2/backtest/runs/${selected.run.run_id}/cancellation` &&
                response.request().method() === "POST"
        );
        await page.getByRole("button", { name: "取消回测", exact: true }).click();
        expect((await cancellation).status()).toBe(200);
        await expect(
            page.getByText("回测已取消，以下为已完成部分的结果", { exact: true })
        ).toBeVisible();
        const result = await resultView(false);
        expect(result.path).toBe(interruption.path);
        await expect.poll(() => runObservations.get(selected.run.run_id)?.state).toBe("CANCELLED");
        expect(backtestWrites.filter((path) => path.endsWith("/cancellation"))).toEqual([
            `/api/v2/backtest/runs/${interruption.run.run_id}/cancellation`
        ]);
        await page.reload();
        expect(await resultView(false)).toEqual(result);
        await page.getByRole("link", { name: "回测记录", exact: true }).click();
        const original = page
            .getByRole("row")
            .filter({ has: page.locator(`a[href="${result.path}"]`) });
        await expect(original.getByText("已取消", { exact: true })).toBeVisible();
        await original.getByRole("link", { name: "查看回测", exact: true }).click();
        expect(await resultView(false)).toEqual(result);
        await writeFile(
            evidence,
            JSON.stringify({ kind: "CANCELLED", ...interruption, originalPreparation, result })
        );
        expect(agentWrites).toEqual([]);
        return;
    }
    if (acceptance === "performance") {
        // Original fixed Run performance gate remains independent of the case budget.
        await expect.poll(observeOriginalRun, { timeout: 120_000 }).toBe(true);
        expect(Date.now()).toBeLessThanOrEqual(runDeadline);
    } else {
        // Functional evidence is bounded by this case's unchanged aggregate budget.
        // It does not certify completion within the separate 120s performance gate.
        await expect
            .poll(observeOriginalRun, { timeout: Math.max(1, journeyDeadline - Date.now()) })
            .toBe(true);
    }
    const result = await resultView();
    expect(confirmationErrors).toEqual([]);
    for (const observed of confirmationObservations) {
        expect(originalPreparation).toBe(`/backtest/preparations/${observed.command_id}`);
        expect(result.path).toBe(`/backtest/runs/${observed.reserved_run_id}`);
    }
    await testInfo.attach("confirmation-observations", {
        body: JSON.stringify(confirmationObservations),
        contentType: "application/json"
    });
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
}

// Existing owner checks retain their fixed 120s Run completion gate.
test("normal backtest works without Agent and reopens the same run after restart", async ({
    page
}, testInfo) => {
    await backtestJourney(page, testInfo, "performance");
});

test("normal backtest functional correctness reopens the same run after restart", async ({
    page
}, testInfo) => {
    await backtestJourney(page, testInfo, "functional");
});

test("normal backtest functional cancellation reopens the same cancelled run after restart", async ({
    page
}, testInfo) => {
    await backtestJourney(page, testInfo, "functional-cancel");
});

// Last in the initial batch: the harness drains/reopens immediately after this
// actual RUNNING + Ready-prefix observation, rather than after another journey.
test("normal backtest functional running recovery completes the same run after restart", async ({
    page
}, testInfo) => {
    await backtestJourney(page, testInfo, "functional-running-recovery");
});
