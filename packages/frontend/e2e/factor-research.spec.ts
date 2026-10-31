import {
    enableResearchAssistant,
    openModelSettings,
    reloadResearch,
    selectResearchHistory
} from "./support/factorChatUi";
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { once } from "node:events";
import { z } from "zod";
import {
    expect,
    test,
    type BrowserContext,
    type Page,
    type Response as BrowserResponse,
    type Request as BrowserRequest
} from "@playwright/test";
import {
    readPreparationProof,
    assertStudiesReuseGeneration,
    withCorruptedReadyTuple,
    withMissingPreparationFact,
    withMissingRuntimeRoot,
    terminateResearchInventory
} from "./support/researchPreparationAssertions";
const name = "放量动量研究候选";
const sourceSchema = z.object({
    integration_id: z.uuid(),
    integration_revision_fingerprint: z.string(),
    expected_type_id: z.string(),
    source_id: z.string(),
    environment: z.string()
});
const prerequisite = z.object({
    controlled_external_input: z.literal(true),
    source: sourceSchema,
    suggested_advice: z.object({
        timeframe_minutes: z.number(),
        instrument_id: z.string(),
        start_at: z.string(),
        development_end_at: z.string(),
        end_at: z.string(),
        protected_start_at: z.string(),
        protected_end_at: z.string(),
        horizon_bars: z.number(),
        expected_block_length: z.number(),
        replicates: z.number(),
        confidence_bps: z.number(),
        seed: z.string()
    })
});
const outcome = z.object({
    command_id: z.uuid(),
    research_command_id: z.uuid(),
    reserved_run_id: z.uuid(),
    run_id: z.uuid().nullable()
});
const restartSchema = z.object({
    session: z.uuid(),
    first: z.uuid(),
    second: z.uuid(),
    third: z.uuid(),
    firstRun: z.uuid(),
    thirdRun: z.uuid(),
    modelPort: z.number().int().min(1).max(65535),
    normalStudies: z.number().int().nonnegative(),
    factorCalls: z.number().int().nonnegative(),
    studyCalls: z.number().int().nonnegative()
});
function stopOwnedProcess(pid: number) {
    execFileSync("python", [
        "-c",
        "import os,signal,select,sys; pid=int(sys.argv[1]); fd=os.pidfd_open(pid); os.kill(pid,signal.SIGTERM); assert select.select([fd],[],[],20)[0], 'process did not exit'; os.close(fd)",
        String(pid)
    ]);
}
test.describe.serial("Human-led durable Factor Research", () => {
    let page: Page;
    let old: z.infer<typeof restartSchema>;
    let modelPort = 0,
        agentAbsentRun = "",
        agentAbsentNeedsLookup = false,
        agentAbsentConfirmationCount = 0;
    let fault: ReturnType<typeof terminateResearchInventory>;
    let queuedRun = "",
        queuedNeedsLookup = false,
        queuedConfirmationCount = 0;
    let stale: Page;
    let context: BrowserContext;
    let server: ReturnType<typeof createServer> | undefined;
    let input: z.infer<typeof prerequisite>;
    let factorCalls = 0,
        studyCalls = 0,
        normalStudies = 0;
    const controlledHttps = process.env.ONLYALPHA_BROWSER_CONTROLLED_SOURCE_HTTPS === "1";
    let missingStudy: z.infer<typeof outcome>;
    const missingCommands: string[] = [];
    let missingActive = false;
    const trackMissingCommands = (request: BrowserRequest) => {
        if (
            missingActive &&
            request.method() === "POST" &&
            (request.url().includes("/confirmation") ||
                request.url().includes("/api/v2/research/runs"))
        )
            missingCommands.push(request.url());
    };
    let session = "",
        firstCommand = "",
        firstReservedRun = "",
        firstRun = "";
    let second: z.infer<typeof outcome>, cancellationStudy: z.infer<typeof outcome>;
    let firstProof: ReturnType<typeof readPreparationProof>;
    const evidence = z.string().min(1).parse(process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE);
    const marketFile = z
        .string()
        .min(1)
        .parse(process.env.ONLYALPHA_BROWSER_CONTROLLED_MARKET_INPUT);
    const userData = z.string().min(1).parse(process.env.ONLYALPHA_BROWSER_USER_DATA_ROOT);
    const agentPid = z
        .number()
        .int()
        .positive()
        .parse(Number(process.env.ONLYALPHA_BROWSER_AGENT_PID));
    const hostPid = z
        .number()
        .int()
        .positive()
        .parse(Number(process.env.ONLYALPHA_BROWSER_HOST_PID));
    const restored = process.env.ONLYALPHA_BROWSER_RESTART_PHASE === "restored";
    const chat = () => page.getByRole("textbox", { name: "告诉助手你的想法", exact: true });
    async function readConfirmationAcknowledgement(response: BrowserResponse) {
        expect(await response.request().headerValue("idempotency-key")).toBe(
            cancellationStudy.research_command_id
        );
        if (response.ok()) {
            const ack = z
                .object({
                    state: z.enum(["ACCEPTED", "OUTCOME_UNKNOWN"]),
                    research_command_id: z.uuid(),
                    run_id: z.uuid().nullable()
                })
                .parse(await response.json());
            expect(ack.research_command_id).toBe(cancellationStudy.research_command_id);
            if (ack.state === "ACCEPTED") {
                const run = z.uuid().parse(ack.run_id);
                expect(run).toBe(cancellationStudy.reserved_run_id);
                return { run, needsLookup: false };
            }
            expect(ack.run_id).toBeNull();
        } else {
            expect(response.status()).toBe(503);
            z.object({
                error: z.object({
                    phase: z.literal("QUERY"),
                    code: z.literal("CHART_STUDY_QUERY_UNAVAILABLE")
                })
            }).parse(await response.json());
        }
        await expect(
            page.getByRole("button", { name: "核对原研究操作", exact: true })
        ).toBeVisible();
        return { run: "", needsLookup: true };
    }
    async function reconcileOriginalConfirmation(needsLookup: boolean) {
        const lookup = page.waitForResponse(async (r) => {
            if (
                r.request().method() !== "GET" ||
                !r
                    .url()
                    .endsWith(`/factor-study-preparations/commands/${cancellationStudy.command_id}`)
            )
                return false;
            if (!r.ok()) return true;
            const actual = z
                .object({
                    research_outcome: z.enum(["ACCEPTED", "OUTCOME_UNKNOWN", "NOT_SUBMITTED"]),
                    state: z.string()
                })
                .parse(await r.json());
            return (
                actual.research_outcome === "ACCEPTED" ||
                ["BLOCKED", "UNKNOWN", "CANCELLED", "CANCEL_REQUESTED"].includes(actual.state)
            );
        });
        await page
            .getByRole("button", {
                name: needsLookup ? "核对原研究操作" : "刷新研究状态",
                exact: true
            })
            .click();
        const response = await lookup;
        expect(response.ok()).toBe(true);
        const accepted = z
            .object({
                command_id: z.uuid(),
                research_command_id: z.uuid(),
                reserved_run_id: z.uuid(),
                research_outcome: z.literal("ACCEPTED"),
                run_id: z.uuid()
            })
            .parse(await response.json());
        expect(accepted.command_id).toBe(cancellationStudy.command_id);
        expect(accepted.research_command_id).toBe(cancellationStudy.research_command_id);
        expect(accepted.reserved_run_id).toBe(cancellationStudy.reserved_run_id);
        expect(accepted.run_id).toBe(cancellationStudy.reserved_run_id);
        return accepted.run_id;
    }
    async function waitPreparationReady(command: string) {
        const terminal = page.waitForResponse(async (r) => {
            if (
                r.request().method() !== "GET" ||
                !r.url().endsWith(`/factor-study-preparations/commands/${command}`)
            )
                return false;
            if (!r.ok()) return true;
            const v = z.object({ state: z.string() }).parse(await r.json());
            return ["READY", "BLOCKED", "UNKNOWN", "CANCELLED", "CANCEL_REQUESTED"].includes(
                v.state
            );
        });
        await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
        const response = await terminal;
        expect(response.ok()).toBe(true);
        const actual = z
            .object({
                state: z.string(),
                command_id: z.uuid(),
                readiness: z.object({ state: z.string() })
            })
            .parse(await response.json());
        expect(actual.command_id).toBe(command);
        expect(actual.state).toBe("READY");
        expect(actual.readiness.state).toBe("VERIFIED");
        await expect(page.getByRole("button", { name: "确认本次研究", exact: true })).toBeEnabled();
    }
    async function waitRunTerminal(run: string, target: Page = page) {
        const response = await target.waitForResponse(async (r) => {
            if (
                r.request().method() !== "GET" ||
                !r.url().endsWith(`/research/runs/${run}`) ||
                !r.ok()
            )
                return false;
            const v = z.object({ state: z.string() }).parse(await r.json());
            return ["COMPLETED", "FAILED", "CANCELLED"].includes(v.state);
        });
        return z
            .object({ run_id: z.uuid(), state: z.string(), report: z.unknown().nullable() })
            .parse(await response.json());
    }
    test.beforeAll(async ({ browser, baseURL }) => {
        if (baseURL === undefined) throw new Error("canonical browser base URL required");
        context = await browser.newContext({ baseURL });
        page = await context.newPage();
        page.on("request", trackMissingCommands);
        input = prerequisite.parse(JSON.parse(await readFile(marketFile, "utf8")));
        if (restored) {
            old = restartSchema.parse(JSON.parse(await readFile(evidence, "utf8")));
            normalStudies = old.normalStudies;
            factorCalls = old.factorCalls;
            studyCalls = old.studyCalls;
        }
        server = createServer((request, response) => {
            const chunks: Buffer[] = [];
            request.on("data", (chunk: Buffer) => chunks.push(chunk));
            request.on("end", () => {
                try {
                    if (
                        request.url !== "/v1/chat/completions" ||
                        request.headers.authorization !== "Bearer controlled-model-secret"
                    ) {
                        response.writeHead(401).end();
                        return;
                    }
                    const body = z
                        .object({
                            messages: z.array(z.object({ role: z.string(), content: z.string() }))
                        })
                        .parse(JSON.parse(Buffer.concat(chunks).toString()));
                    if (
                        body.messages.length === 1 &&
                        body.messages[0].content === "请只回复：连接成功。"
                    ) {
                        response.writeHead(200, { "Content-Type": "application/json" });
                        response.end(
                            JSON.stringify({ choices: [{ message: { content: "连接成功。" } }] })
                        );
                        return;
                    }
                    const studyMode = body.messages.some(
                        (m) =>
                            m.content.includes('"supported_profile"') &&
                            m.content.includes('"factor_proposal_fingerprint"')
                    );
                    let content: unknown;
                    if (studyMode) {
                        studyCalls++;
                        expect(
                            body.messages.some((m) =>
                                m.content.includes(input.source.integration_revision_fingerprint)
                            )
                        ).toBe(true);
                        const base = input.suggested_advice;
                        const { instrument_id, ...timing } = base;
                        const latestUser =
                            body.messages.filter((m) => m.role === "user").at(-1)?.content ?? "";
                        const short = latestUser.includes("每段30分钟");
                        const missing =
                            controlledHttps &&
                            latestUser.includes("整体前移一天，检查未完成行情输入");
                        if (!short && !missing) normalStudies++;
                        const shifted = missing
                            ? {
                                  start_at: "2025-12-31T06:00:00Z",
                                  development_end_at: "2026-01-02T22:00:00Z",
                                  end_at: "2026-01-05T14:00:00Z"
                              }
                            : short
                              ? {
                                    start_at: "2026-01-01T06:00:00Z",
                                    development_end_at: "2026-01-01T06:30:00Z",
                                    end_at: "2026-01-01T07:00:00Z"
                                }
                              : normalStudies === 1
                                ? {}
                                : normalStudies === 2
                                  ? {
                                        start_at: "2026-01-01T06:15:00Z",
                                        development_end_at: "2026-01-03T22:15:00Z",
                                        end_at: "2026-01-06T14:15:00Z"
                                    }
                                  : normalStudies === 3
                                    ? {
                                          start_at: "2026-01-01T06:30:00Z",
                                          development_end_at: "2026-01-03T22:30:00Z",
                                          end_at: "2026-01-06T14:30:00Z"
                                      }
                                    : normalStudies === 4
                                      ? {
                                            start_at: "2026-01-01T06:45:00Z",
                                            development_end_at: "2026-01-03T22:45:00Z",
                                            end_at: "2026-01-06T14:45:00Z"
                                        }
                                      : {
                                            start_at: "2026-01-01T07:00:00Z",
                                            development_end_at: "2026-01-03T23:00:00Z",
                                            end_at: "2026-01-06T15:00:00Z"
                                        };
                        content = {
                            message:
                                "建议采用已确认的固定开发与样本外区间，并用区块重采样评估序列依赖。请先准备环境，再单独确认本次研究。",
                            study: {
                                source: { ...input.source, instrument_id },
                                ...timing,
                                ...shifted,
                                rationale: missing
                                    ? "研究窗口前移一天，行情完整性须由正式准备流程核验。受控HTTP缺少的输入不代表市场不存在。"
                                    : "受控离线既有行情覆盖该非保护区间；按配对平稳块自助法分析时间序列相关及不确定性。"
                            }
                        };
                    } else {
                        factorCalls++;
                        content =
                            factorCalls === 1
                                ? {
                                      message: "希望用多少根已收盘K线观察动量和放量？",
                                      candidate: null
                                  }
                                : {
                                      message: "这是因子草稿，请核对用途、计算逻辑与公式。",
                                      candidate: {
                                          name,
                                          purpose: "研究成交量放大时历史动量与随后价格变化的关系",
                                          hypothesis: "放量可能增强已有动量的延续性",
                                          expression: {
                                              op: "mul",
                                              left: {
                                                  op: "sub",
                                                  left: {
                                                      op: "div",
                                                      left: { input: "close" },
                                                      right: {
                                                          input: "close",
                                                          lag: 20
                                                      }
                                                  },
                                                  right: { integer: 1 }
                                              },
                                              right: {
                                                  op: "div",
                                                  left: { input: "volume" },
                                                  right: { input: "volume", mean: 20 }
                                              }
                                          }
                                      }
                                  };
                    }
                    response.setHeader("content-type", "application/json");
                    response.setHeader("connection", "close");
                    response.end(
                        JSON.stringify({
                            choices: [{ message: { content: JSON.stringify(content) } }]
                        })
                    );
                } catch (e) {
                    response.writeHead(500).end(e instanceof Error ? e.message : String(e));
                }
            });
        });
        server.listen(restored ? old.modelPort : 0, "127.0.0.1");
        await once(server, "listening");
        const bound = server.address();
        if (bound === null || typeof bound === "string")
            throw new Error("controlled model port unavailable");
        modelPort = bound.port;
        if (restored) expect(modelPort).toBe(old.modelPort);
    });
    test.afterAll(async () => {
        if (server?.listening) {
            server.closeAllConnections();
            server.close();
            await once(server, "close");
        }
        if (typeof context !== "undefined") await context.close();
    });
    if (restored) {
        test("restart restores exact reports including Research completed without Agent", async () => {
            await page.goto("/factor-research");
            await expect(
                page.getByRole("heading", { name: "因子研究", exact: true })
            ).toBeVisible();
            await selectResearchHistory(page, "希望挖掘一个放量动量因子，用BTCUSDT做研究");
            await expect(
                page.getByRole("status").filter({ hasText: "计算内容已确认并保存" })
            ).toBeVisible();
            await page
                .getByRole("combobox", { name: "已登记的准备任务", exact: true })
                .selectOption(old.first);
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
            await page.getByText("不可变证据与精确输入", { exact: true }).click();
            await expect(
                page.locator("pre").filter({ hasText: "research_result_fingerprint" })
            ).toBeVisible();
            const originalThird = waitRunTerminal(old.thirdRun);
            await page
                .getByRole("combobox", { name: "已登记的准备任务", exact: true })
                .selectOption(old.third);
            expect((await originalThird).state).toBe("COMPLETED");
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
        });
        test("the original session suggests a new cancellation study through its same model endpoint", async () => {
            await chat().fill(
                "保持因子与保护样本不变，将开发和样本外窗口再整体后移一根15分钟K线，请建议下一次研究条件"
            );
            await page.getByRole("button", { name: "发送", exact: true }).click();
            await expect(
                page
                    .getByRole("region", { name: "研究方案", exact: true })
                    .getByRole("definition")
                    .filter({ hasText: /^2026-01-01T07:00:00Z 至 2026-01-03T23:00:00Z$/ })
            ).toBeVisible();
            const accepted = page.waitForResponse(
                (r) =>
                    r.request().method() === "POST" &&
                    r.url().endsWith("/factor-study-preparations") &&
                    r.ok()
            );
            await page.getByRole("button", { name: "准备并启用研究环境", exact: true }).click();
            cancellationStudy = outcome.parse(await (await accepted).json());
            expect(normalStudies).toBe(old.normalStudies + 1);
            expect(studyCalls).toBe(old.studyCalls + 1);
            expect(factorCalls).toBe(old.factorCalls);
        });
        test("the original new preparation becomes Ready before the inventory fault", async () => {
            await waitPreparationReady(cancellationStudy.command_id);
        });
        test("inventory outage preserves normal original report observation", async () => {
            const info = test.info();
            fault = terminateResearchInventory(cancellationStudy.command_id, userData);
            expect(fault.hostPid).toBe(hostPid);
            await info.attach("exact-research-inventory-fault", {
                body: JSON.stringify(fault),
                contentType: "application/json"
            });
            await page
                .getByRole("combobox", { name: "已登记的准备任务", exact: true })
                .selectOption(old.first);
            await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
            await expect(page.getByText("研究执行服务暂不可用", { exact: false })).toBeVisible();
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
            await page
                .getByRole("combobox", { name: "已登记的准备任务", exact: true })
                .selectOption(cancellationStudy.command_id);
            await expect(
                page.getByRole("button", { name: "确认本次研究", exact: true })
            ).toBeEnabled();
        });
        test("Human submits one original confirmation while Agent and inventory are unavailable", async () => {
            stopOwnedProcess(agentPid);
            await reloadResearch(page);
            await expect(
                page.getByRole("alert").filter({ hasText: "研究助手暂时无法连接" })
            ).toBeVisible();
            const path = `/${cancellationStudy.command_id}/confirmation`;
            page.on("request", (request) => {
                if (request.method() === "POST" && request.url().endsWith(path))
                    queuedConfirmationCount++;
            });
            const confirmed = page.waitForResponse(
                (r) => r.request().method() === "POST" && r.url().endsWith(path)
            );
            await chat().fill("确认本次研究");
            await page.getByRole("button", { name: "发送", exact: true }).click();
            const ack = await readConfirmationAcknowledgement(await confirmed);
            queuedRun = ack.run;
            queuedNeedsLookup = ack.needsLookup;
            expect(queuedConfirmationCount).toBe(1);
        });
        test("the original queued Run is recovered without resubmitting Human confirmation", async () => {
            queuedRun = await reconcileOriginalConfirmation(queuedNeedsLookup);
            expect(queuedConfirmationCount).toBe(1);
            await expect(page.getByRole("status").filter({ hasText: "研究排队中" })).toBeVisible();
        });
        test("Human cancels that exact queued Run while Agent and inventory remain unavailable", async () => {
            const info = test.info();
            const cancelled = page.waitForResponse(
                (r) =>
                    r.request().method() === "POST" &&
                    r.url().endsWith(`/runs/${queuedRun}/cancellation`)
            );
            await page.getByRole("button", { name: "取消本次研究", exact: true }).click();
            const ack = await cancelled;
            expect(ack.ok()).toBe(true);
            expect(
                z
                    .object({ run_id: z.uuid(), state: z.literal("CANCELLED") })
                    .parse(await ack.json()).run_id
            ).toBe(queuedRun);
            const cancelCommand = z
                .uuid()
                .parse(await ack.request().headerValue("idempotency-key"));
            await expect(page.getByRole("status").filter({ hasText: "研究已取消" })).toBeVisible();
            await info.attach("shipping-ui-original-run-cancellation", {
                body: JSON.stringify({
                    ...fault,
                    completed_ui_cancellation: true,
                    run_id: queuedRun,
                    preparation_command_id: cancellationStudy.command_id,
                    cancellation_command_id: cancelCommand
                }),
                contentType: "application/json"
            });
            expect(queuedConfirmationCount).toBe(1);
        });
        test("backend outage keeps the viewed original report and blocks new work", async () => {
            await page
                .getByRole("combobox", { name: "已登记的准备任务", exact: true })
                .selectOption(old.first);
            await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
            stopOwnedProcess(fault.hostPid);
            await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
            await expect(
                page.getByRole("alert").filter({ hasText: "Failed to fetch" })
            ).toBeVisible();
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
            await expect(
                page.getByRole("button", { name: "准备并启用研究环境", exact: true })
            ).toBeDisabled();
        });
    } else {
        test("chat, Factor confirmation and Study advice survive a lost preparation acknowledgement", async () => {
            await page.goto("/factor-research");
            await expect(
                page.getByRole("heading", { name: "因子研究", exact: true })
            ).toBeVisible();
            await enableResearchAssistant(page);
            if (server === undefined) throw new Error("controlled model server required");
            const address = server.address();
            if (!address || typeof address === "string")
                throw new Error("model fixture address unavailable");
            await openModelSettings(page);
            await page
                .getByRole("dialog", { name: "设置", exact: true })
                .getByRole("button", { name: "添加模型", exact: true })
                .click();
            await page
                .getByLabel("服务地址", { exact: true })
                .fill(`http://127.0.0.1:${String(address.port)}/v1`);
            await page.getByLabel("模型名称", { exact: true }).fill("controlled-research-model-v1");
            await page.getByLabel("模型版本说明", { exact: true }).fill("controlled-research-v1");
            await page.getByLabel("API 密钥", { exact: true }).fill("controlled-model-secret");
            await page.getByRole("button", { name: "测试连接", exact: true }).click();
            await expect(page.getByText("连接成功。", { exact: true })).toBeVisible();
            await page.getByRole("button", { name: "保存模型设置", exact: true }).click();
            await expect(page.getByRole("form", { name: "模型配置" })).toHaveCount(0);
            await page.getByRole("button", { name: "关闭设置", exact: true }).click();
            const created = page.waitForResponse(
                (r) =>
                    r.request().method() === "PUT" &&
                    /\/api\/v1\/agent\/sessions\/[^/]+$/.test(r.url()) &&
                    r.ok()
            );
            await page.getByRole("button", { name: "＋ 新建研究", exact: true }).click();
            await chat().fill("希望挖掘一个放量动量因子，用BTCUSDT做研究");
            await page.getByRole("button", { name: "发送", exact: true }).click();
            session = z.object({ id: z.uuid() }).parse(await (await created).json()).id;
            await expect(
                page.getByText("希望用多少根已收盘K线观察动量和放量？", { exact: true })
            ).toBeVisible();
            await chat().fill("使用20根已收盘K线，成交量相对20根均量，先给我预览");
            await page.getByRole("button", { name: "发送", exact: true }).click();
            await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
            await expect(
                page.getByRole("button", { name: "准备并启用研究环境", exact: true })
            ).toHaveCount(0);
            await chat().fill("确认因子");
            await page.getByRole("button", { name: "发送", exact: true }).click();
            await expect(
                page.getByRole("status").filter({ hasText: "计算内容已确认并保存" })
            ).toBeVisible();
            await page.getByRole("button", { name: "讨论研究条件", exact: true }).click();
            await expect(page.getByText("研究条件建议已登记", { exact: false })).toBeVisible();
            expect(studyCalls).toBe(1);
            await page.route("**/api/v2/factor-study-preparations", async (route) => {
                if (route.request().method() === "POST" && firstCommand === "") {
                    firstCommand = z
                        .uuid()
                        .parse(await route.request().headerValue("idempotency-key"));
                    const accepted = outcome.parse(await (await route.fetch()).json());
                    expect(accepted.command_id).toBe(firstCommand);
                    firstReservedRun = accepted.reserved_run_id;
                    await route.abort("failed");
                } else await route.continue();
            });
            await page.getByRole("button", { name: "准备并启用研究环境", exact: true }).click();
            await expect(
                page.getByRole("button", { name: "核对原研究操作", exact: true })
            ).toBeVisible();
            const recovered = page.waitForResponse(
                (r) =>
                    r.request().method() === "GET" &&
                    r.url().endsWith(`/factor-study-preparations/commands/${firstCommand}`)
            );
            await page.reload();
            const response = await recovered;
            expect(response.ok()).toBe(true);
            expect(outcome.parse(await response.json()).command_id).toBe(firstCommand);
            await expect(
                page.getByRole("region", { name: "准备与运行研究", exact: true })
            ).toBeVisible();
        });
        test("the original preparation becomes Ready for Human confirmation", async () => {
            await waitPreparationReady(firstCommand);
        });
        test("corrupted materialization blocks confirmation until the original proof is restored", async () => {
            await withCorruptedReadyTuple(
                firstCommand,
                userData,
                "dataset-materialization",
                async () => {
                    await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
                    await expect(page.getByRole("alert")).toBeVisible();
                    await expect(
                        page.getByRole("button", { name: "确认本次研究", exact: true })
                    ).toBeDisabled();
                }
            );
            await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
            await expect(
                page.getByRole("button", { name: "确认本次研究", exact: true })
            ).toBeEnabled();
        });
        for (const missing of ["novelty-group", "installed-proof"] as const) {
            test(`missing ${missing} blocks confirmation until the original proof is restored`, async () => {
                await withMissingPreparationFact(firstCommand, userData, missing, async () => {
                    await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
                    await expect(
                        page.getByText("这份准备的输入证明暂不可核验", { exact: false })
                    ).toBeVisible();
                    await expect(
                        page.getByRole("button", { name: "确认本次研究", exact: true })
                    ).toBeDisabled();
                });
                await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
                await expect(
                    page.getByRole("button", { name: "确认本次研究", exact: true })
                ).toBeEnabled();
            });
        }
        test("a separate Human chat confirmation produces the first immutable scientific report", async () => {
            const firstPreparationCommand = firstCommand;
            await page.route(
                `**/factor-study-preparations/${firstPreparationCommand}/confirmation`,
                async (route) => {
                    await route.fetch(); // Real canonical submit; lose only the response acknowledgment.
                    await route.abort("failed");
                }
            );
            const completedResponse = waitRunTerminal(firstReservedRun);
            await chat().fill("确认本次研究");
            await page.getByRole("button", { name: "发送", exact: true }).click();
            await expect(
                page.getByRole("button", { name: "核对原研究操作", exact: true })
            ).toBeVisible();
            await page.getByRole("button", { name: "核对原研究操作", exact: true }).click();
            expect((await completedResponse).state).toBe("COMPLETED");
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
            await withMissingPreparationFact(firstCommand, userData, "novelty-group", async () => {
                await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
                await expect(
                    page.getByRole("region", { name: "研究结果报告", exact: true })
                ).toBeVisible();
                await expect(
                    page.getByText("历史准入证明暂不可完整核验", { exact: false })
                ).toBeVisible();
            });
            await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
            expect(studyCalls).toBe(1);
            expect(factorCalls).toBe(2);
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
            await expect(page.getByText("Pearson 线性相关", { exact: true })).toHaveCount(2);
            await expect(page.getByText("Spearman 秩相关", { exact: true })).toHaveCount(2);
            firstProof = readPreparationProof(firstCommand, userData);
            firstRun = z.uuid().parse(firstProof.runId);
        });
        test("edited study conditions prepare a second exact experiment", async () => {
            await chat().fill(
                "将开发和样本外研究窗口整体后移一根15分钟K线，保护样本不动，因子保持不变"
            );
            await page.getByRole("button", { name: "发送", exact: true }).click();
            await expect(
                page.getByRole("status").filter({ hasText: "计算内容已确认并保存" })
            ).toBeVisible();
            await expect(
                page
                    .getByRole("region", { name: "研究方案", exact: true })
                    .getByRole("definition")
                    .filter({ hasText: /^2026-01-01T06:15:00Z 至 2026-01-03T22:15:00Z$/ })
            ).toBeVisible();
            const prepare = page.waitForResponse(
                (r) =>
                    r.request().method() === "POST" &&
                    r.url().endsWith("/factor-study-preparations") &&
                    r.ok()
            );
            await page.getByRole("button", { name: "准备并启用研究环境", exact: true }).click();
            second = outcome.parse(await (await prepare).json());
            await waitPreparationReady(second.command_id);
        });
        test("the second Human-confirmed report reuses its Generation", async () => {
            const completedResponse = waitRunTerminal(second.reserved_run_id);
            await chat().fill("确认本次研究");
            await page.getByRole("button", { name: "发送", exact: true }).click();
            expect((await completedResponse).state).toBe("COMPLETED");
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
            expect(studyCalls).toBe(2);
            expect(factorCalls).toBe(2);
            const secondProof = readPreparationProof(second.command_id, userData);
            assertStudiesReuseGeneration(firstProof, secondProof);
        });
        test("a fresh tab discovers the accepted report while current Runtime is unavailable", async () => {
            await withMissingRuntimeRoot(second.command_id, userData, async () => {
                // New browser page has no per-tab pending/Run locator. backend history must discover it.
                const fresh = await page.context().newPage();
                try {
                    const complete = waitRunTerminal(second.reserved_run_id, fresh);
                    await fresh.goto("/factor-research");
                    await selectResearchHistory(fresh, "希望挖掘一个放量动量因子，用BTCUSDT做研究");
                    expect((await complete).state).toBe("COMPLETED");
                    await expect(
                        fresh.getByRole("region", { name: "研究结果报告", exact: true })
                    ).toBeVisible();
                    await expect(
                        fresh.getByText("当前数据来源或研究环境暂不可用", { exact: false })
                    ).toBeVisible();
                } finally {
                    await fresh.close();
                }
            });
        });
        if (controlledHttps) {
            test("missing-input advice submits only one ordinary preparation", async () => {
                missingActive = true;
                await chat().fill(
                    "保持因子、周期、保护样本不变，将开发和样本外窗口整体前移一天，检查未完成行情输入"
                );
                await page.getByRole("button", { name: "发送", exact: true }).click();
                await expect(
                    page
                        .getByRole("region", { name: "研究方案", exact: true })
                        .getByRole("definition")
                        .filter({ hasText: /^2025-12-31T06:00:00Z 至 2026-01-02T22:00:00Z$/ })
                ).toBeVisible();
                const accepted = page.waitForResponse(
                    (r) =>
                        r.request().method() === "POST" &&
                        r.url().endsWith("/factor-study-preparations") &&
                        r.ok()
                );
                await page.getByRole("button", { name: "准备并启用研究环境", exact: true }).click();
                missingStudy = outcome.parse(await (await accepted).json());
                expect(missingStudy.run_id).toBeNull();
            });
            test("actual controlled external gaps remain pending without Research", async () => {
                const pending = page.waitForResponse(async (r) => {
                    if (
                        r.request().method() !== "GET" ||
                        !r
                            .url()
                            .endsWith(
                                `/factor-study-preparations/commands/${missingStudy.command_id}`
                            ) ||
                        !r.ok()
                    )
                        return false;
                    return ["INPUT_PENDING", "UNKNOWN", "READY", "BLOCKED", "CANCELLED"].includes(
                        z.object({ state: z.string() }).parse(await r.json()).state
                    );
                });
                await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
                const actual = z
                    .object({
                        command_id: z.uuid(),
                        state: z.enum(["INPUT_PENDING", "UNKNOWN"]),
                        run_id: z.null(),
                        research_outcome: z.literal("NOT_SUBMITTED")
                    })
                    .parse(await (await pending).json());
                expect(actual.command_id).toBe(missingStudy.command_id);
                await expect(
                    page
                        .getByRole("region", { name: "准备与运行研究", exact: true })
                        .getByRole("status")
                        .filter({
                            hasText:
                                actual.state === "INPUT_PENDING" ? "等待所需输入" : "原操作结果未知"
                        })
                ).toBeVisible();
                await expect(
                    page.getByRole("button", { name: "确认本次研究", exact: true })
                ).toHaveCount(0);
                expect(missingCommands).toEqual([]);
                const recorded = (
                    await readFile(
                        new URL("controlled-source-https.jsonl", `file://${marketFile}`),
                        "utf8"
                    )
                )
                    .trim()
                    .split("\n")
                    .map((line) => JSON.parse(line) as unknown);
                const requests = z
                    .array(
                        z.object({
                            method: z.literal("GET"),
                            status: z.literal(200),
                            host: z.literal("data-api.binance.vision"),
                            sni: z.literal("data-api.binance.vision"),
                            path: z.literal("/api/v3/klines"),
                            query: z.object({
                                symbol: z.tuple([z.literal("BTCUSDT")]),
                                interval: z.tuple([z.literal("15m")]),
                                startTime: z.tuple([z.string()]),
                                endTime: z.tuple([z.string()])
                            }),
                            raw_response_sha256: z.string().regex(/^[0-9a-f]{64}$/),
                            response_rows: z.number().int().nonnegative()
                        })
                    )
                    .parse(
                        recorded.filter(
                            (record) =>
                                z.object({ path: z.string().optional() }).parse(record).path ===
                                "/api/v3/klines"
                        )
                    );
                const emptyPayloadSha = createHash("sha256").update("[]").digest("hex");
                expect(
                    requests.some(
                        (request) =>
                            request.query.startTime[0] === "1767141900000" &&
                            request.query.endTime[0] === "1767225599999" &&
                            request.response_rows === 0 &&
                            request.raw_response_sha256 === emptyPayloadSha
                    )
                ).toBe(true);
                expect(
                    requests.every((request) => Number(request.query.endTime[0]) < 1767744000000)
                ).toBe(true);
                await test.info().attach("actual-controlled-provider-requests", {
                    body: JSON.stringify(requests),
                    contentType: "application/json"
                });
                await test.info().attach("controlled-input-incomplete-not-market-absence", {
                    body: JSON.stringify(actual),
                    contentType: "application/json"
                });
            });
            test("the incomplete original preparation can be stopped normally", async () => {
                const cancelled = page.waitForResponse(async (r) => {
                    if (
                        !r.ok() ||
                        !r
                            .url()
                            .includes(
                                `/factor-study-preparations/commands/${missingStudy.command_id}`
                            )
                    )
                        return false;
                    return (
                        z.object({ state: z.string() }).parse(await r.json()).state === "CANCELLED"
                    );
                });
                await page.getByRole("button", { name: "停止原准备任务", exact: true }).click();
                const actual = z
                    .object({
                        command_id: z.uuid(),
                        run_id: z.null(),
                        research_outcome: z.literal("NOT_SUBMITTED")
                    })
                    .parse(await (await cancelled).json());
                expect(actual.command_id).toBe(missingStudy.command_id);
                await expect(
                    page.getByRole("status").filter({ hasText: "已停止准备" })
                ).toBeVisible();
                expect(missingCommands).toEqual([]);
                missingActive = false;
            });
        }
        test("short sample advice is refused before any preparation or Research command", async () => {
            const forbidden: string[] = [];
            const onRequest = (request: BrowserRequest) => {
                if (
                    request.method() === "POST" &&
                    (request.url().includes("/api/v2/factor-study-preparations") ||
                        request.url().includes("/api/v2/research/runs"))
                )
                    forbidden.push(request.url());
            };
            page.on("request", onRequest);
            try {
                const unavailable = page.waitForResponse(async (response) => {
                    if (
                        response.request().method() !== "GET" ||
                        !response.url().includes("/api/v2/factor-study-preparation-context/") ||
                        !response.ok()
                    )
                        return false;
                    return (
                        z
                            .object({ new_work_status: z.object({ code: z.string().nullable() }) })
                            .parse(await response.json()).new_work_status.code ===
                        "RESEARCH_PREPARATION_INSUFFICIENT_BLOCK_SCOPE"
                    );
                });
                await chat().fill(
                    "保持因子不变，将研究改为每段30分钟，开发06:00至06:30，样本外06:30至07:00，检查有效样本不足"
                );
                await page.getByRole("button", { name: "发送", exact: true }).click();
                const actual = z
                    .object({
                        new_work_status: z.object({
                            state: z.literal("UNAVAILABLE"),
                            code: z.literal("RESEARCH_PREPARATION_INSUFFICIENT_BLOCK_SCOPE")
                        })
                    })
                    .parse(await (await unavailable).json());
                expect(actual.new_work_status.state).toBe("UNAVAILABLE");
                await expect(
                    page
                        .getByRole("region", { name: "研究方案", exact: true })
                        .getByRole("definition")
                        .filter({ hasText: /^2026-01-01T06:30:00Z 至 2026-01-01T07:00:00Z$/ })
                ).toBeVisible();
                await expect(page.getByText("研究样本范围不足", { exact: false })).toBeVisible();
                await expect(
                    page.getByRole("button", { name: "准备并启用研究环境", exact: true })
                ).toBeDisabled();
                if (controlledHttps) {
                    const oldCompleted = waitRunTerminal(second.reserved_run_id);
                    await page
                        .getByRole("combobox", { name: "已登记的准备任务", exact: true })
                        .selectOption(second.command_id);
                    expect((await oldCompleted).state).toBe("COMPLETED");
                }
                await expect(
                    page.getByRole("region", { name: "研究结果报告", exact: true })
                ).toBeVisible();
                expect(forbidden).toEqual([]);
            } finally {
                page.off("request", onRequest);
            }
        });
        test("valid chat changes and original report review submit one preparation command", async () => {
            await chat().fill(
                "再将开发和样本外研究窗口整体后移一根15分钟K线，保护样本不动，因子保持不变"
            );
            await page.getByRole("button", { name: "发送", exact: true }).click();
            await expect(
                page
                    .getByRole("region", { name: "研究方案", exact: true })
                    .getByRole("definition")
                    .filter({ hasText: /^2026-01-01T06:30:00Z 至 2026-01-03T22:30:00Z$/ })
            ).toBeVisible();
            await expect(page.getByText("研究样本范围不足", { exact: false })).toHaveCount(0);
            const history = page.getByRole("combobox", { name: "已登记的准备任务", exact: true });
            await expect(history.locator(`option[value="${firstCommand}"]`)).toHaveCount(1);
            await expect(history.locator(`option[value="${second.command_id}"]`)).toHaveCount(1);
            await history.selectOption(firstCommand);
            const oldReport = page.getByRole("region", { name: "研究结果报告", exact: true });
            await expect(oldReport.getByText("本报告原研究条件", { exact: true })).toBeVisible();
            await expect(
                oldReport.getByText(input.suggested_advice.instrument_id, { exact: true })
            ).toBeVisible();
            await expect(
                oldReport
                    .getByRole("paragraph")
                    .filter({ hasText: /^原样本区间.*2026-01-01T06:00:00/ })
            ).toBeVisible();
            const thirdPrepared = page.waitForResponse(
                (r) =>
                    r.request().method() === "POST" &&
                    r.url().endsWith("/factor-study-preparations") &&
                    r.ok()
            );
            await page.getByRole("button", { name: "准备并启用研究环境", exact: true }).click();
            cancellationStudy = outcome.parse(await (await thirdPrepared).json());
            expect(studyCalls).toBe(controlledHttps ? 5 : 4);
            expect(factorCalls).toBe(2);
        });
        test("the original accepted preparation becomes ready without another submission", async () => {
            await waitPreparationReady(cancellationStudy.command_id);
        });
        test("a second normal tab retains the original unsubmitted ready proposal", async () => {
            stale = await context.newPage();
            const originalReady = stale.waitForResponse(async (response) => {
                if (
                    response.request().method() !== "GET" ||
                    !response
                        .url()
                        .endsWith(
                            `/factor-study-preparations/commands/${cancellationStudy.command_id}`
                        ) ||
                    !response.ok()
                )
                    return false;
                return (
                    z.object({ state: z.string() }).parse(await response.json()).state === "READY"
                );
            });
            await stale.goto("/factor-research");
            await selectResearchHistory(stale, "希望挖掘一个放量动量因子，用BTCUSDT做研究");
            await stale
                .getByRole("combobox", { name: "已登记的准备任务", exact: true })
                .selectOption(cancellationStudy.command_id);
            await originalReady;
            await expect(
                stale.getByRole("button", { name: "确认本次研究", exact: true })
            ).toBeEnabled();
        });
        test("new advice makes the old tab confirmation explicitly stale and unsubmitted", async () => {
            await chat().fill(
                "再把开发和样本外区间整体后移一根15分钟K线，保护样本不变，请给我最新研究条件"
            );
            await page.getByRole("button", { name: "发送", exact: true }).click();
            await expect(
                page
                    .getByRole("region", { name: "研究方案", exact: true })
                    .getByRole("definition")
                    .filter({ hasText: /^2026-01-01T06:45:00Z 至 2026-01-03T22:45:00Z$/ })
            ).toBeVisible();
            // READY naturally stops polling. This ordinary second tab still holds the old proposal.
            await expect(
                stale.getByRole("button", { name: "确认本次研究", exact: true })
            ).toBeEnabled();
            const rejected = stale.waitForResponse(
                (r) =>
                    r.request().method() === "POST" &&
                    r.url().endsWith(`/${cancellationStudy.command_id}/confirmation`)
            );
            await stale
                .getByRole("textbox", { name: "告诉助手你的想法", exact: true })
                .fill("确认本次研究");
            await stale.getByRole("button", { name: "发送", exact: true }).click();
            const response = await rejected;
            expect(response.status()).toBe(503);
            const rejection = z
                .object({
                    error: z.object({
                        code: z.enum([
                            "FACTOR_STUDY_PROPOSAL_STALE",
                            "RESEARCH_PREPARATION_STUDY_STALE"
                        ])
                    })
                })
                .parse(await response.json());
            expect(rejection.error.code).toMatch(/STUDY_PROPOSAL_STALE|PREPARATION_STUDY_STALE/);
            await expect(
                stale.getByRole("button", { name: "核对原研究操作", exact: true })
            ).toBeVisible();
            const firstLookup = stale.waitForResponse(
                (r) =>
                    r.request().method() === "GET" &&
                    r
                        .url()
                        .endsWith(
                            `/factor-study-preparations/commands/${cancellationStudy.command_id}`
                        )
            );
            await stale.getByRole("button", { name: "核对原研究操作", exact: true }).click();
            const lookup = await firstLookup;
            expect(lookup.ok()).toBe(true);
            const closed = z
                .object({
                    command_id: z.uuid(),
                    state: z.literal("BLOCKED"),
                    phase: z.literal("STOPPED"),
                    research_outcome: z.literal("NOT_SUBMITTED"),
                    run_id: z.null(),
                    detail: z.object({
                        code: z.enum([
                            "FACTOR_STUDY_PROPOSAL_STALE",
                            "RESEARCH_PREPARATION_STUDY_STALE"
                        ])
                    })
                })
                .parse(await lookup.json());
            expect(closed.command_id).toBe(cancellationStudy.command_id);
            await expect(
                stale.getByText("原研究条件已过期，已核对本次研究未提交", { exact: false })
            ).toBeVisible();
        });
        test("the original stale preparation can be stopped before loading current advice", async () => {
            await expect(
                stale.getByRole("button", { name: "停止原准备任务", exact: true })
            ).toBeEnabled();
            await stale.getByRole("button", { name: "停止原准备任务", exact: true }).click();
            await expect(stale.getByRole("status").filter({ hasText: "已停止准备" })).toBeVisible();
            await reloadResearch(stale);
            await expect(
                stale
                    .getByRole("region", { name: "研究方案", exact: true })
                    .getByRole("definition")
                    .filter({ hasText: /^2026-01-01T06:45:00Z 至 2026-01-03T22:45:00Z$/ })
            ).toBeVisible();
            await stale.close();
        });
        test("valid revised advice submits one fresh preparation command", async () => {
            await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
            const accepted = page.waitForResponse(
                (r) =>
                    r.request().method() === "POST" &&
                    r.url().endsWith("/factor-study-preparations") &&
                    r.ok()
            );
            await page.getByRole("button", { name: "准备并启用研究环境", exact: true }).click();
            cancellationStudy = outcome.parse(await (await accepted).json());
        });
        test("the original revised preparation reaches Ready before Agent stops", async () => {
            await waitPreparationReady(cancellationStudy.command_id);
            expect(studyCalls).toBe(controlledHttps ? 6 : 5);
            expect(factorCalls).toBe(2);
            await page.screenshot({
                path: test.info().outputPath("factor-research-prepared-for-restart.png"),
                fullPage: true
            });
        });
        test("Human submits the original confirmation once while Agent is unavailable", async () => {
            stopOwnedProcess(agentPid);
            await reloadResearch(page);
            await expect(
                page.getByRole("alert").filter({ hasText: "研究助手暂时无法连接" })
            ).toBeVisible();
            const path = `/${cancellationStudy.command_id}/confirmation`;
            page.on("request", (request) => {
                if (request.method() === "POST" && request.url().endsWith(path))
                    agentAbsentConfirmationCount++;
            });
            const submitted = page.waitForResponse(
                (r) => r.request().method() === "POST" && r.url().endsWith(path)
            );
            await chat().fill("确认本次研究");
            await page.getByRole("button", { name: "发送", exact: true }).click();
            const response = await submitted;
            const ack = await readConfirmationAcknowledgement(response);
            agentAbsentRun = ack.run;
            agentAbsentNeedsLookup = ack.needsLookup;
            expect(agentAbsentConfirmationCount).toBe(1);
        });
        test("the original confirmation is proven accepted through its owning query without resubmission", async () => {
            agentAbsentRun = await reconcileOriginalConfirmation(agentAbsentNeedsLookup);
            expect(agentAbsentConfirmationCount).toBe(1);
        });
        test("actual Research completes without Agent and retains exact restart evidence", async () => {
            const completed = waitRunTerminal(agentAbsentRun);
            await page.getByRole("button", { name: "刷新研究状态", exact: true }).click();
            expect((await completed).state).toBe("COMPLETED");
            await expect(
                page.getByRole("region", { name: "研究结果报告", exact: true })
            ).toBeVisible();
            expect(agentAbsentConfirmationCount).toBe(1);
            await expect(
                page.getByRole("button", { name: "核对原研究操作", exact: true })
            ).toHaveCount(0);
            await expect(
                page.getByRole("alert").filter({ hasText: "研究助手暂时无法连接" })
            ).toBeVisible();
            await writeFile(
                evidence,
                JSON.stringify(
                    restartSchema.parse({
                        session,
                        first: firstCommand,
                        second: second.command_id,
                        third: cancellationStudy.command_id,
                        firstRun,
                        thirdRun: agentAbsentRun,
                        modelPort,
                        normalStudies,
                        factorCalls,
                        studyCalls
                    })
                )
            );
        });
    }
});
