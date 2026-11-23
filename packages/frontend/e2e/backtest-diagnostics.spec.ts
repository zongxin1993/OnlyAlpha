import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { z } from "zod";

const execute = promisify(execFile);
const event = z.object({
    event_kind: z.string(),
    operation: z.string().optional(),
    process_instance_id: z.string(),
    span_id: z.string().optional(),
    run_id: z.string().optional(),
    request_id: z.string().optional(),
    lock_type: z.string().optional(),
    outcome: z.string().optional(),
    mono_ns: z.number()
});
const probeReply = z.object({
    cursor: z.number().int().nonnegative(),
    available_bytes: z.number().int().nonnegative(),
    events: z.array(event),
    sql: z.object({ state: z.string(), finished: z.boolean().optional() }).optional()
});
type Event = z.infer<typeof event>;
const factorName = "回测性能诊断价量动量";
const strategyName = "回测性能诊断普通回测";
async function navigateProduct(page: Page, label: string) {
    await page
        .getByRole("navigation", { name: "产品导航" })
        .getByRole("link", { name: label, exact: true })
        .click();
}
async function prepareFirstRun(page: Page) {
    await page.goto("/");
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
    await navigateProduct(page, "策略");
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
    const readyStarted = Date.now();
    await expect(start).toBeEnabled({ timeout: 120_000 });
    expect(Date.now() - readyStarted).toBeLessThanOrEqual(120_000);
    return {
        start,
        preparationPath: new URL(page.url()).pathname,
        preparationReadyMs: Date.now() - readyStarted
    };
}

// 独立取证，不修改 backtest.spec.ts 的300/120秒门槛；本例成功只证明采集闭合。
test("one backtest diagnostic observes publication contention and one terminal GET", async ({
    page
}, testInfo) => {
    test.setTimeout(1_160_000); // 20分钟整体预算中为原20秒排空和协调器留余量。
    page.setDefaultTimeout(30_000);
    const eventsPath = z.string().min(1).parse(process.env.ONLYALPHA_BROWSER_DIAGNOSTIC_LOG);
    const namespace = z.string().min(1).parse(process.env.ONLYALPHA_BROWSER_DIAGNOSTIC_NAMESPACE);
    const evidencePath = z.string().min(1).parse(process.env.ONLYALPHA_BROWSER_DIAGNOSTIC_EVIDENCE);
    const started = Date.now();
    const deadline = started + 1_160_000;
    const remaining = () => Math.max(1, deadline - Date.now());
    const controls: Event[] = [];
    let cursor = 0;
    let available = 0;
    let run = "";
    let terminalRequests = 0;
    const report: Record<string, unknown> = {
        schema_version: 1,
        diagnostic_only: true,
        original_web_gate_seconds: 300,
        original_preparation_gate_seconds: 120,
        drain_gate_seconds: 20
    };
    async function save() {
        await writeFile(
            evidencePath,
            JSON.stringify(
                {
                    ...report,
                    run_id: run || null,
                    elapsed_ms: Date.now() - started,
                    terminal_requests: terminalRequests
                },
                null,
                2
            )
        );
    }
    async function observe(sql = false) {
        const { stdout } = await execute(
            "python",
            [
                resolve("../../scripts/backtest_diagnostic.py"),
                "--events",
                eventsPath,
                "--namespace",
                namespace,
                "--run",
                run,
                "--cursor",
                String(cursor),
                ...(sql ? ["--sql"] : [])
            ],
            { timeout: Math.min(5_000, remaining()), maxBuffer: 4 * 1024 * 1024 }
        );
        const reply = probeReply.parse(JSON.parse(stdout));
        cursor = reply.cursor;
        available = reply.available_bytes;
        controls.push(...reply.events);
        if (controls.some((row) => row.event_kind === "diagnostic_loss"))
            throw new Error("diagnostic loss observed");
        return reply.sql;
    }
    const key = (row: Event) => {
        if (row.span_id === undefined) throw new Error("diagnostic operation span missing");
        return `${row.process_instance_id}/${row.span_id}`;
    };
    const ended = (row: Event) =>
        controls.some((end) => end.event_kind === "operation_end" && key(end) === key(row));
    try {
        const first = await prepareFirstRun(page);
        report.preparation_ready_ms = first.preparationReadyMs;
        report.original_preparation_gate_passed = true;
        await first.start.focus();
        await expect(first.start).toBeFocused();
        await page.keyboard.press("Enter");
        await expect
            .poll(
                async () => {
                    const match = /^\/backtest\/runs\/([0-9a-f-]+)$/.exec(
                        new URL(page.url()).pathname
                    );
                    if (match?.[1]) {
                        run = z.uuid().parse(match[1]);
                        return true;
                    }
                    const observe = page.getByRole("button", { name: "查看任务进度", exact: true });
                    if ((await observe.isVisible()) && (await observe.isEnabled()))
                        await observe.click();
                    return false;
                },
                { timeout: Math.min(300_000, remaining()), intervals: [500, 1000, 2000] }
            )
            .toBe(true);
        report.original_preparation = first.preparationPath;
        report.run_visible_ms = Date.now() - started;
        await save();
        await navigateProduct(page, "回测");
        const originalRow = () =>
            page.getByRole("row").filter({ has: page.locator(`a[href="/backtest/runs/${run}"]`) });
        await expect(originalRow()).toBeVisible();
        await expect
            .poll(
                async () => {
                    await observe();
                    return controls.some(
                        (row) =>
                            row.operation === "generation.hold" &&
                            row.run_id === run &&
                            row.lock_type === "shared" &&
                            row.event_kind === "lock_acquired" &&
                            !controls.some(
                                (release) =>
                                    [
                                        "lock_release_begin",
                                        "lock_released",
                                        "operation_end"
                                    ].includes(release.event_kind) && key(release) === key(row)
                            )
                    );
                },
                { timeout: remaining(), intervals: [500, 1000, 2000] }
            )
            .toBe(true);
        report.shared_hold_observed_ms = Date.now() - started;
        await save();
        await navigateProduct(page, "策略");
        await page
            .getByRole("row")
            .filter({ hasText: strategyName })
            .getByRole("link", { name: "配置回测", exact: true })
            .click();
        await page.getByRole("combobox", { name: "回测行情数据源", exact: true }).click();
        await expect(page.getByRole("option")).toHaveCount(1);
        await page
            .getByRole("combobox", { name: "回测行情数据源", exact: true })
            .press("ArrowDown");
        await page.getByRole("combobox", { name: "回测行情数据源", exact: true }).press("Enter");
        const preparationStarted = Date.now();
        let preparationState = "unknown";
        let preparationCommand: string | undefined;
        page.on("response", (response) => {
            if (
                response.status() !== 200 ||
                !/^\/api\/v2\/backtest\/preparations\/commands\/[0-9a-f-]+$/.test(
                    new URL(response.url()).pathname
                )
            )
                return;
            void response
                .json()
                .then((body: unknown) => {
                    const value = z.object({ command_id: z.uuid(), state: z.string() }).parse(body);
                    if (`/backtest/preparations/${value.command_id}` !== first.preparationPath) {
                        preparationCommand = value.command_id;
                        preparationState = value.state;
                    }
                })
                .catch(() => {
                    preparationState = "unreadable";
                });
        });
        await page.getByRole("button", { name: "确认策略并准备回测", exact: true }).click();
        try {
            await expect
                .poll(() => preparationState, {
                    timeout: Math.min(120_000, remaining()),
                    intervals: [500, 1000, 2000]
                })
                .toMatch(/^(BLOCKED|FAILED|READY)$/);
        } catch {
            report.contention_preparation_gate_passed = false;
        }
        report.contention_preparation = {
            command_id: preparationCommand ?? null,
            state: preparationState,
            elapsed_ms: Date.now() - preparationStarted,
            cancellation: "not_attempted"
        };
        await page.screenshot({
            path: testInfo.outputPath("contending-preparation.png"),
            fullPage: true
        });
        await save();
        await navigateProduct(page, "回测");
        await expect(originalRow()).toBeVisible();
        let sqlState = "unknown";
        await expect
            .poll(
                async () => {
                    const sql = await observe(true);
                    sqlState = sql?.state ?? "unknown";
                    return (
                        ["COMPLETED", "FAILED", "CANCELLED"].includes(sqlState) &&
                        sql?.finished === true
                    );
                },
                { timeout: remaining(), intervals: [1000, 2000] }
            )
            .toBe(true);
        report.sql_terminal = { state: sqlState, observed_ms: Date.now() - started };
        report.original_web_gate_passed = Date.now() - started > 300_000 ? false : null;
        // Drain the incremental cursor before marking existing roots. Never choose a request by time proximity.
        do {
            await observe();
        } while (cursor < available);
        const existingRoots = new Set(
            controls
                .filter(
                    (row) =>
                        row.operation === "http.backtest.get" &&
                        row.run_id === run &&
                        row.event_kind === "operation_start"
                )
                .map(key)
        );
        const terminalPath = `/api/v2/backtest/runs/${run}`;
        const leave = () => {
            void page
                .context()
                .close()
                .catch(() => {
                    report.client_context_close_failed = true;
                });
        };
        page.on("request", (request) => {
            if (request.method() === "GET" && new URL(request.url()).pathname === terminalPath) {
                terminalRequests++;
                if (terminalRequests > 1) {
                    report.duplicate_terminal_request = true;
                    leave();
                }
            }
        });
        page.on("requestfailed", (request) => {
            if (new URL(request.url()).pathname === terminalPath) {
                report.client_terminal = { state: "request_failed", body: "unknown" };
                leave();
            }
        });
        page.on("response", (response) => {
            if (new URL(response.url()).pathname === terminalPath) {
                report.client_terminal = {
                    state: "headers_received",
                    status: response.status(),
                    body: "unknown_after_departure"
                };
                leave();
            }
        });
        try {
            await originalRow().getByRole("link", { name: "查看回测", exact: true }).click();
        } catch (error) {
            if (!(terminalRequests === 1 && report.client_terminal !== undefined)) throw error;
        }
        report.terminal_clicked_ms = Date.now() - started;
        await save();
        await expect
            .poll(
                async () => {
                    await observe();
                    const roots = controls.filter(
                        (row) =>
                            row.operation === "http.backtest.get" &&
                            row.run_id === run &&
                            row.event_kind === "operation_start" &&
                            !existingRoots.has(key(row))
                    );
                    if (roots.length > 1)
                        throw new Error("multiple terminal server operations observed");
                    const terminal = roots.at(0);
                    const cleanup = controls.find(
                        (row) =>
                            row.operation === "backtest.terminal.cleanup" &&
                            row.run_id === run &&
                            row.event_kind === "operation_start"
                    );
                    const finalize = controls.find(
                        (row) =>
                            row.operation === "backtest.finalize" &&
                            row.run_id === run &&
                            row.event_kind === "operation_start"
                    );
                    const ingress =
                        terminal === undefined
                            ? undefined
                            : controls.find(
                                  (row) =>
                                      row.operation === "http.ingress.dispatch" &&
                                      row.request_id === terminal.request_id &&
                                      row.event_kind === "operation_start"
                              );
                    return (
                        terminal?.request_id !== undefined &&
                        ingress !== undefined &&
                        ended(ingress) &&
                        ended(terminal) &&
                        cleanup !== undefined &&
                        ended(cleanup) &&
                        finalize !== undefined &&
                        ended(finalize)
                    );
                },
                { timeout: remaining(), intervals: [1000, 2000] }
            )
            .toBe(true);
        await expect
            .poll(() => report.client_terminal !== undefined, {
                timeout: Math.min(30_000, remaining()),
                intervals: [500, 1000]
            })
            .toBe(true);
        report.server_tail_closed = true;
        expect(terminalRequests).toBe(1);
        expect(report.duplicate_terminal_request).toBeUndefined();
    } finally {
        await save();
    }
});
