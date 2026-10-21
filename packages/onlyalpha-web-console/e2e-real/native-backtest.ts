import { chromium, expect } from "@playwright/test";
import type { Browser, BrowserContext, Page } from "@playwright/test";
import type { ChildProcess } from "node:child_process";
import { z } from "zod";
import { spawn } from "node:child_process";
import {
    openSync,
    closeSync,
    readFileSync,
    existsSync,
    mkdirSync,
    watch,
    writeFileSync
} from "node:fs";
import { join } from "node:path";
import { once } from "node:events";
const env = process.env;
function required(name: string): string {
    const value = env[name];
    if (value === undefined || value === "") throw new Error(`Missing harness input: ${name}`);
    return value;
}
const root = required("OA_NATIVE_ROOT"),
    out = required("OA_UI_EVIDENCE");
const progressSchema = z.object({ cursor: z.number().int().nonnegative() });
const workerArgs = [
    "-I",
    "-m",
    "onlyalpha.backtest.worker_main",
    "--user-data-root",
    root,
    "--backtest-product-config",
    required("OA_NATIVE_CONFIG"),
    "--runtime-generation-authority-root",
    required("OA_NATIVE_GENERATION_ROOT"),
    "--runtime-generation-fingerprint",
    required("OA_NATIVE_GENERATION"),
    "--poll-interval",
    "0.05"
];
let worker: ChildProcess | undefined;
let browser: Browser | undefined;
let context: BrowserContext | undefined;
let restartedApi: ChildProcess | undefined;
function startWorker() {
    const fd = openSync(join(out, `worker-${Date.now().toString()}.log`), "a");
    worker = spawn(required("OA_NATIVE_PYTHON"), workerArgs, { env, stdio: ["ignore", fd, fd] });
    closeSync(fd);
    return worker;
}
async function stopWorker() {
    if (worker?.exitCode !== null) return;
    worker.kill("SIGCONT");
    worker.kill("SIGTERM");
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
        await Promise.race([
            once(worker, "exit"),
            new Promise((_, reject) => {
                timer = setTimeout(() => {
                    reject(new Error("worker did not stop durably"));
                }, 15000);
            })
        ]);
    } finally {
        clearTimeout(timer);
    }
}
function pauseAt(runId: string, cursor: number): Promise<{ cursor: number }> {
    const base = join(root, "backtest/runtimes");
    mkdirSync(base, { recursive: true });
    return new Promise<{ cursor: number }>((resolve, reject) => {
        const timeout = setTimeout(() => {
            watcher.close();
            reject(new Error(`No durable progress barrier ${runId}/${cursor.toString()}`));
        }, 60000);
        const inspect = () => {
            const path = join(base, runId, "progress.json");
            if (!existsSync(path)) return;
            const p = progressSchema.parse(JSON.parse(readFileSync(path, "utf8")));
            if (p.cursor >= cursor) {
                if (worker === undefined) throw new Error("No worker at the progress barrier");
                worker.kill("SIGSTOP");
                clearTimeout(timeout);
                watcher.close();
                resolve(p);
            }
        };
        const watcher = watch(base, { recursive: true }, inspect);
        inspect();
    });
}
async function create(page: Page): Promise<string> {
    await page.getByRole("link", { name: "回测", exact: true }).click();
    await page.getByLabel("Strategy and dataset").selectOption({ index: 1 });
    for (const [label, value] of [
        ["Initial capital", "100000.00"],
        ["Order quantity", "2"],
        ["Entry limit price", "100.00"],
        ["Exit limit price", "32.00"],
        ["Maximum fill quantity per bar", "2"]
    ])
        await page.getByLabel(label, { exact: true }).fill(value);
    await page.getByRole("button", { name: "Create and run Backtest" }).click();
    await expect(page).toHaveURL(/\/backtest\/runs\/[0-9a-f-]{36}$/);
    const id = page.url().split("/").at(-1);
    if (id === undefined) throw new Error("Missing created Run identity");
    return id;
}
try {
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext();
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    const page = await context.newPage();
    page.on("console", (m) => {
        if (m.type() === "error") console.error("BROWSER", m.text());
    });
    await page.goto("http://127.0.0.1:4173");
    // Creation is performed in the Shipping UI. The worker starts only afterwards,
    // so the lifecycle barrier cannot miss early inputs or replace any user action.
    const cancelId = await create(page);
    const cancelBarrier = pauseAt(cancelId, 5);
    startWorker();
    const prefix = await cancelBarrier;
    await page.getByRole("button", { name: "Cancel Backtest", exact: true }).click();
    await expect(page.locator(".product-state strong")).toHaveText("CANCEL_REQUESTED");
    if (worker === undefined) throw new Error("Worker missing before cancellation acknowledgement");
    worker.kill("SIGCONT");
    await expect(page.locator(".product-state strong")).toHaveText("CANCELLED", { timeout: 60000 });
    await page.reload();
    await expect(page.locator(".product-state strong")).toHaveText("CANCELLED");
    await page.screenshot({ path: join(out, "cancelled.png"), fullPage: true });
    await stopWorker();
    const recoveredId = await create(page);
    const recoveryBarrier = pauseAt(recoveredId, 5);
    startWorker();
    await recoveryBarrier;
    await stopWorker();
    const progressBefore = progressSchema.parse(
        JSON.parse(
            readFileSync(join(root, "backtest/runtimes", recoveredId, "progress.json"), "utf8")
        )
    );
    if (progressBefore.cursor < 5) throw new Error("durable prefix was lost at graceful shutdown");
    process.kill(-Number(required("OA_NATIVE_API_PID")), "SIGTERM");
    await expect
        .poll(
            () => {
                const status = `/proc/${required("OA_NATIVE_API_PID")}/stat`;
                return !existsSync(status) || readFileSync(status, "utf8").includes(") Z ");
            },
            { timeout: 15000 }
        )
        .toBe(true);
    const apiFd = openSync(join(out, "api-restarted.log"), "a");
    restartedApi = spawn(
        required("OA_NATIVE_PYTHON"),
        [
            "-I",
            "-m",
            "onlyalpha_http_server.main",
            "--user-data-root",
            root,
            "--port",
            "8000",
            "--backtest-product-config",
            required("OA_NATIVE_CONFIG"),
            "--runtime-generation-authority-root",
            required("OA_NATIVE_GENERATION_ROOT")
        ],
        { env, stdio: ["ignore", apiFd, apiFd] }
    );
    closeSync(apiFd);
    await expect
        .poll(
            async () => {
                try {
                    return (await fetch("http://127.0.0.1:8000/health/ready")).status;
                } catch {
                    return 0;
                }
            },
            { timeout: 30000 }
        )
        .toBe(200);
    await page.reload();
    await expect(page).toHaveURL(new RegExp(recoveredId + "$"));
    startWorker();
    await expect(page.locator(".product-state strong")).toHaveText("COMPLETED", { timeout: 90000 });
    const result = page.getByRole("region", { name: "Backtest result" });
    // The owning result reader has a 30-second native verification bound; allow
    // five seconds for HTTP and rendering, rather than Playwright's default five.
    const resultStarted = performance.now();
    await expect(result).toContainText("Execution implementation: Rust", { timeout: 35000 });
    const resultReadMs = performance.now() - resultStarted;
    await expect(result).toContainText("Orders: 2 · Trades: 2");
    await expect(result).toContainText("99863.74");
    const orders = result.getByRole("table").nth(0);
    await expect(orders).toContainText("BUY");
    await expect(orders).toContainText("SELL");
    await expect(orders).toContainText("100.00");
    await expect(orders).toContainText("32.00");
    await expect(orders).not.toContainText("Not reported");
    const reloadStarted = performance.now();
    await page.reload();
    await expect(page.getByRole("region", { name: "Backtest result" })).toContainText("99863.74", {
        timeout: 35000
    });
    const reloadedResultReadMs = performance.now() - reloadStarted;
    await expect(
        page.getByText("Verified manifest linked to the exact completed Run.")
    ).toBeVisible();
    await expect(page.locator(".artifact-metadata-list li")).toHaveCount(4);
    await expect(page.getByRole("alert")).toHaveCount(0);
    const trades = page.getByRole("region", { name: "Backtest result" }).getByRole("table").nth(1);
    await expect(trades.getByRole("cell", { name: "2", exact: true })).toHaveCount(2);
    await expect(trades.getByRole("cell", { name: "100.00", exact: true })).toBeVisible();
    await expect(trades.getByRole("cell", { name: "0.20", exact: true })).toBeVisible();
    await page.screenshot({ path: join(out, "completed.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: join(out, "completed-mobile.png"), fullPage: true });
    const overflow = await page
        .locator("body")
        .evaluate((el) => el.scrollWidth > window.innerWidth);
    if (overflow) throw new Error("Shipping Backtest page overflows the mobile viewport");
    writeFileSync(
        join(out, "observations.json"),
        JSON.stringify({
            cancelId,
            recoveredId,
            cancelCursor: prefix.cursor,
            recoveredFrom: progressBefore.cursor,
            finalEquity: "99863.74",
            implementation: "Rust",
            resultReadMs,
            reloadedResultReadMs
        })
    );
    console.log("SHIPPING_NATIVE_BACKTEST_PASS", cancelId, recoveredId);
} finally {
    if (restartedApi?.exitCode === null) {
        restartedApi.kill("SIGTERM");
        await once(restartedApi, "exit");
    }
    if (context) await context.tracing.stop({ path: join(out, "trace.zip") });
    if (browser) await browser.close();
    await stopWorker();
}
