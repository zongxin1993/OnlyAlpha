import { readFile, writeFile } from "node:fs/promises";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { z } from "zod";

type Acceptance =
    "performance" | "functional" | "functional-cancel" | "functional-running-recovery";
const immutableRun = z.strictObject({
    run_id: z.uuid(),
    strategy_fingerprint: z.string().regex(/^[0-9a-f]{64}$/),
    preparation_command_id: z.uuid(),
    accepted_at: z.string()
});
const observedRun = z.object({
    ...immutableRun.shape,
    state: z.string(),
    cancel_requested_at: z.string().optional(),
    cancellation_reason: z.literal("USER_REQUESTED").optional(),
    report_status: z.object({ state: z.string() })
});
const preparationIdentity = z.object({
    command_id: z.uuid(),
    backtest_command_id: z.uuid(),
    reserved_run_id: z.uuid()
});
const cancelReceipt = z.strictObject({ command_id: z.uuid(), requested_at: z.string() });
const lifecycleIdentity = { path: z.string(), originalPreparation: z.string(), run: immutableRun };
const lifecycleEvidence = z.discriminatedUnion("kind", [
    z.strictObject({ ...lifecycleIdentity, kind: z.literal("RUNNING") }),
    z.strictObject({ ...lifecycleIdentity, kind: z.literal("CANCELLED"), cancellation: cancelReceipt })
]);

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
    const readyPreparations = new Map<string, z.infer<typeof preparationIdentity>>();
    const confirmationObservations: z.infer<typeof preparationIdentity>[] = [];
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
                ...preparationIdentity.shape,
                run_id: z.uuid().nullable(),
                backtest_outcome: z.string(),
                readiness: z.object({ state: z.string() })
            })
            .parse(await response.json());
        if (
            projection.state === "READY" && projection.readiness.state === "VERIFIED" &&
            projection.backtest_outcome === "NOT_SUBMITTED"
        ) {
            readyPreparations.set(
                `/backtest/preparations/${projection.command_id}`,
                preparationIdentity.parse(projection)
            );
        }
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
        await productNav.getByRole("link", { name: label, exact: true }).click();
    }
    function originalRun(value: z.infer<typeof observedRun>) {
        return immutableRun.parse({
            run_id: value.run_id,
            strategy_fingerprint: value.strategy_fingerprint,
            preparation_command_id: value.preparation_command_id,
            accepted_at: value.accepted_at
        });
    }
    async function cancelledView(runId: string, cancellation: z.infer<typeof cancelReceipt>) {
        await expect(page.getByText("已按你的请求取消。本次回测没有发布结果。", { exact: true })).toBeVisible();
        await expect(page.getByRole("heading", { name: "回测结果", exact: true })).toHaveCount(0);
        await expect(page.locator(".backtest-metrics")).toHaveCount(0);
        await expect.poll(() => runObservations.get(runId)).toMatchObject({
            state: "CANCELLED",
            cancel_requested_at: cancellation.requested_at,
            cancellation_reason: "USER_REQUESTED",
            report_status: { state: "NOT_APPLICABLE" }
        });
    }
    async function resultView(timeout = 120_000) {
        await expect(page.getByRole("heading", { name: "回测结果", exact: true })).toBeVisible({
            timeout
        });
        const view = page.getByRole("main", { name: "策略回测" });
        const metrics = view.locator(".backtest-metrics");
        await expect(metrics.getByText("净收益（USDT）", { exact: true })).toBeVisible();
        await expect(metrics.getByText("最大回撤", { exact: true })).toBeVisible();
        await expect(metrics.getByText("手续费（USDT）", { exact: true })).toBeVisible();
        await expect(view.getByText("成交明细", { exact: true })).toBeVisible();
        await expect(view.getByText("期末持仓", { exact: true })).toBeVisible();
        await expect(metrics).not.toContainText("暂不可用");
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
            metrics: await metrics.innerText(),
            tables: [
                await trades.innerText(),
                await positions.innerText(),
                await details.innerText()
            ]
        };
    }
    await page.goto("/");
    // 左栏导航壳（c16d6aa8）取代旧产品下拉菜单：产品入口直接可达。
    const productNav = page.getByRole("navigation", { name: "产品导航" });
    await expect(productNav.getByRole("link", { name: "策略", exact: true })).toBeVisible();
    await expect(productNav.getByRole("link", { name: "因子研究", exact: true })).toHaveCount(0);
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
        await navigateProduct("回测");
        const original = page
            .getByRole("row")
            .filter({ has: page.locator(`a[href="${previous.path}"]`) });
        if (previous.kind === "CANCELLED")
            await expect(original.getByText("已取消", { exact: true })).toBeVisible();
        await original.getByRole("link", { name: "查看回测", exact: true }).click();
        expect(new URL(page.url()).pathname).toBe(previous.path);
        if (previous.kind === "CANCELLED") {
            await cancelledView(previous.run.run_id, previous.cancellation);
        } else {
            const result = await resultView(Math.max(1, journeyDeadline - Date.now()));
            expect(result.path).toBe(previous.path);
            await expect.poll(() => runObservations.get(previous.run.run_id)).toMatchObject({
                state: "COMPLETED", report_status: { state: "VERIFIED" }
            });
        }
        const current = runObservations.get(previous.run.run_id);
        expect(current === undefined ? null : originalRun(current)).toEqual(previous.run);
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
        expect(backtestWrites).toEqual([]);
        expect(agentWrites).toEqual([]);
        return;
    }
    await page.getByRole("button", { name: "目录", exact: true }).click();
    await page.getByRole("tab", { name: "因子库", exact: true }).click();
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
    const interruptionKind = acceptance === "functional-cancel" ? "CANCELLED"
        : acceptance === "functional-running-recovery" ? "RUNNING" : null;
    const barrier = process.env.ONLYALPHA_BROWSER_BACKTEST_INPUT_BARRIER;
    async function inputBarrier(path: string, payload?: unknown) {
        if (!barrier) throw new Error("回测运行中验收需要冻结行情读取屏障。");
        const response = await fetch(`${barrier}/backtest-input/${path}`, {
            method: payload === undefined ? "GET" : "POST",
            body: payload === undefined ? undefined : JSON.stringify(payload),
            signal: AbortSignal.timeout(path === "stop" ? 22_000 : 2_000)
        });
        expect(response.ok).toBe(true);
        return response.json();
    }
    if (interruptionKind !== null) {
        await expect.poll(() => readyPreparations.has(originalPreparation)).toBe(true);
        const ready = preparationIdentity.parse(readyPreparations.get(originalPreparation));
        expect(await inputBarrier("arm", [interruptionKind, ready.reserved_run_id, ready.backtest_command_id])).toBe(true);
    }
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
    if (interruptionKind !== null) {
        const ready = preparationIdentity.parse(readyPreparations.get(originalPreparation));
        const runId = ready.reserved_run_id;
        const path = `/backtest/runs/${runId}`;
        const cancel = page.getByRole("button", { name: "取消回测", exact: true });
        await expect.poll(async () => {
            const run = runObservations.get(runId);
            if (run && ["COMPLETED", "FAILED", "CANCELLED"].includes(run.state))
                throw new Error(`冻结行情读取屏障前回测已终止（${run.state}）。`);
            if (new URL(page.url()).pathname !== path) {
                await observeOriginalRun();
                return false;
            }
            return run?.state === "RUNNING" && await cancel.isVisible() && await cancel.isEnabled()
                && await inputBarrier(runId) === "HELD";
        }, { timeout: Math.max(1, journeyDeadline - Date.now()) }).toBe(true);
        const current = observedRun.parse(runObservations.get(runId));
        const interruption = { path, run: originalRun(current), originalPreparation };
        expect(confirmationErrors).toEqual([]);
        expect(observationErrors).toEqual([]);
        expect(interruption.run.preparation_command_id).toBe(ready.command_id);
        for (const observed of confirmationObservations) expect(observed).toEqual(ready);
        if (interruptionKind === "RUNNING") {
            await writeFile(evidence, JSON.stringify({ kind: "RUNNING", ...interruption }));
            expect(await inputBarrier("stop", runId)).toBe(true);
            await testInfo.attach("running-before-host-stop", {
                body: JSON.stringify(interruption), contentType: "application/json"
            });
            expect(agentWrites).toEqual([]);
            return;
        }
        const cancellationPath = `/api/v2/backtest/runs/${runId}/cancellation`;
        const cancellationResponse = page.waitForResponse((response) =>
            new URL(response.url()).pathname === cancellationPath && response.request().method() === "POST"
        );
        await cancel.click();
        const response = await cancellationResponse;
        expect(response.status()).toBe(200);
        const accepted = z.object({
            run_id: z.uuid(),
            state: z.enum(["CANCEL_REQUESTED", "CANCELLED"]),
            cancel_requested_at: z.string(),
            cancellation_reason: z.literal("USER_REQUESTED")
        }).parse(await response.json());
        expect(accepted.run_id).toBe(runId);
        const cancellation = cancelReceipt.parse({
            command_id: await response.request().headerValue("idempotency-key"),
            requested_at: accepted.cancel_requested_at
        });
        await cancelledView(runId, cancellation);
        await expect.poll(() => inputBarrier(runId)).toBe("DISCONNECTED");
        expect(backtestWrites.filter((write) => write.endsWith("/cancellation"))).toEqual([cancellationPath]);
        await page.reload();
        await cancelledView(runId, cancellation);
        await page.getByRole("link", { name: "回测记录", exact: true }).click();
        const original = page.getByRole("row").filter({ has: page.locator(`a[href="${path}"]`) });
        await expect(original.getByText("已取消", { exact: true })).toBeVisible();
        await original.getByRole("link", { name: "查看回测", exact: true }).click();
        expect(new URL(page.url()).pathname).toBe(path);
        await cancelledView(runId, cancellation);
        expect(originalRun(observedRun.parse(runObservations.get(runId)))).toEqual(interruption.run);
        await writeFile(evidence, JSON.stringify({ kind: "CANCELLED", ...interruption, cancellation }));
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

// The final initial-phase journey sends SIGTERM while its original Attempt is reading frozen input.
test("normal backtest functional running recovery completes the same run after restart", async ({
    page
}, testInfo) => {
    await backtestJourney(page, testInfo, "functional-running-recovery");
});
