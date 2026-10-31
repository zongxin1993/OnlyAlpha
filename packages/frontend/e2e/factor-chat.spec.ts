import {
    enableResearchAssistant,
    openModelSettings,
    reloadResearch,
    selectResearchHistory
} from "./support/factorChatUi";
import { createServer } from "node:http";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { once } from "node:events";
import { z } from "zod";
import { expect, test, request as apiRequest } from "@playwright/test";

function stopOwnedProcess(pid: number) {
    // Linux pidfd is an exit barrier; a sent signal alone does not prove stop.
    execFileSync("python", [
        "-c",
        "import os,signal,select,sys; pid=int(sys.argv[1]); fd=os.pidfd_open(pid); os.kill(pid,signal.SIGTERM); assert select.select([fd],[],[],20)[0], 'process did not exit'; os.close(fd)",
        String(pid)
    ]);
}

test("Independent Agent chat, stale proposal withdrawal and direct Human confirmation survive outages and restart", async ({
    page
}, info) => {
    const evidence = process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE;
    const agentPid = Number(process.env.ONLYALPHA_BROWSER_AGENT_PID);
    const hostPid = Number(process.env.ONLYALPHA_BROWSER_HOST_PID);
    if (!evidence || !agentPid || !hostPid)
        throw new Error("canonical Agent restart harness required");
    const prohibited: string[] = [];
    const legacy: string[] = [];
    page.on("request", (r) => {
        if (
            r.method() !== "GET" &&
            /\/api\/v2\/(research\/runs|research\/runtime-generations|agent\/|backtest)/.test(
                r.url()
            )
        )
            prohibited.push(r.url());
        if (r.url().includes("/api/v2/factor-chat")) legacy.push(r.url());
    });
    await page.goto("/");
    await page.getByRole("link", { name: "因子研究", exact: true }).click();
    await expect(page.getByRole("heading", { name: "因子研究", exact: true })).toBeVisible();
    if (process.env.ONLYALPHA_BROWSER_RESTART_PHASE === "restored") {
        const old = z
            .object({ name: z.string() })
            .parse(JSON.parse(await readFile(evidence, "utf8")));
        await selectResearchHistory(page, old.name);
        await expect(page.getByRole("heading", { name: old.name, exact: true })).toBeVisible();
        await expect(
            page.getByRole("status").filter({ hasText: "计算内容已确认并保存" })
        ).toBeVisible();
        await page.getByText("高级详情：代码与契约", { exact: true }).click();
        await expect(page.locator("pre").filter({ hasText: "def calculate" })).toContainText(
            "api.mul"
        );
        // Infrastructure fault only. Ordinary UI must still read Agent-owned history.
        stopOwnedProcess(hostPid);
        await reloadResearch(page);
        await expect(
            page.getByRole("alert").filter({ hasText: "研究服务暂时不可用" })
        ).toBeVisible();
        await expect(
            page.getByText("用20根已收盘K线，放量也按20根均量比较", { exact: true })
        ).toBeVisible();
        expect(prohibited).toEqual([]);
        expect(legacy).toEqual([]);
        return;
    }
    let calls = 0;
    let release: (() => void) | undefined;
    const modelEntered = new Promise<void>((resolve) => {
        release = resolve;
    });
    let returnModel: (() => void) | undefined;
    const modelBarrier = new Promise<void>((resolve) => {
        returnModel = resolve;
    });
    const server = createServer((request, response) => {
        const chunks: Buffer[] = [];
        request.on("data", (chunk: Buffer) => chunks.push(chunk));
        request.on("end", () => {
            if (
                request.url !== "/v1/chat/completions" ||
                request.headers.authorization !== "Bearer controlled-model-secret"
            ) {
                response.writeHead(401).end();
                return;
            }
            const body = z
                .object({ messages: z.array(z.object({ role: z.string(), content: z.string() })) })
                .parse(JSON.parse(Buffer.concat(chunks).toString()));
            if (body.messages.length === 1 && body.messages[0].content === "请只回复：连接成功。") {
                response.writeHead(200, { "Content-Type": "application/json" });
                response.end(JSON.stringify({ choices: [{ message: { content: "连接成功。" } }] }));
                return;
            }
            calls++;
            expect(body.messages.length).toBeGreaterThanOrEqual(2);
            const candidate = {
                name: calls >= 3 ? "放量动量改进候选" : "放量动量候选",
                purpose: "观察成交量放大时价格动量的关系",
                hypothesis: "放量时的历史动量可能持续",
                expression: {
                    op: "mul",
                    left: {
                        op: "sub",
                        left: {
                            op: "div",
                            left: { input: "close" },
                            right: { input: "close", lag: 20 }
                        },
                        right: { integer: 1 }
                    },
                    right: {
                        op: "div",
                        left: { input: "volume" },
                        right: { input: "volume", mean: 20 }
                    }
                }
            };
            const respond = () => {
                response.setHeader("content-type", "application/json");
                response.end(
                    JSON.stringify({
                        choices: [
                            {
                                message: {
                                    content: JSON.stringify({
                                        message:
                                            calls === 1
                                                ? "你希望观察多少根已收盘 K 线的动量？"
                                                : "这是因子草稿，请核对公式后确认。",
                                        candidate:
                                            calls === 1
                                                ? null
                                                : calls === 4
                                                  ? {
                                                        ...candidate,
                                                        name: "不支持的候选",
                                                        expression: { input: "future" }
                                                    }
                                                  : candidate
                                    })
                                }
                            }
                        ]
                    })
                );
            };
            if (calls === 3) {
                release?.();
                void modelBarrier.then(respond);
            } else respond();
        });
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    try {
        let grantAttempt: { command: string; body: unknown } | undefined;
        await page.route("**/api/v2/factor-proposal-grants", async (route) => {
            if (route.request().method() !== "POST") {
                await route.continue();
                return;
            }
            const value = {
                command: (await route.request().headerValue("idempotency-key")) ?? "",
                body: route.request().postDataJSON() as unknown
            };
            if (grantAttempt === undefined) {
                grantAttempt = value;
                await route.abort("failed");
            } else {
                expect(value).toEqual(grantAttempt);
                await route.continue();
            }
        });
        await enableResearchAssistant(page);
        await expect(
            page.getByRole("button", { name: "再次提交同一授权", exact: true })
        ).toBeVisible();
        await page.reload();
        await page.getByRole("button", { name: "再次提交同一授权", exact: true }).click();
        await expect(page.getByRole("button", { name: "启用助手", exact: true })).toHaveCount(0);
        const address = server.address();
        if (!address || typeof address === "string") throw new Error("address");
        await openModelSettings(page);
        await page
            .getByRole("dialog", { name: "设置", exact: true })
            .getByRole("button", { name: "添加模型", exact: true })
            .click();
        await page
            .getByLabel("服务地址", { exact: true })
            .fill(`http://127.0.0.1:${String(address.port)}/v1`);
        await page.getByLabel("模型名称", { exact: true }).fill("controlled-factor-model-v1");
        await page.getByLabel("模型版本说明", { exact: true }).fill("controlled-v1");
        await page.getByLabel("API 密钥", { exact: true }).fill("controlled-model-secret");
        await page.getByRole("button", { name: "测试连接", exact: true }).click();
        await expect(page.getByText("连接成功。", { exact: true })).toBeVisible();
        await page.getByRole("button", { name: "保存模型设置", exact: true }).click();
        await expect(page.getByRole("form", { name: "模型配置" })).toHaveCount(0);
        await page.getByRole("button", { name: "关闭设置", exact: true }).click();
        const observed: {
            dropped?: { url: string; command: string; body: unknown; authorization: string };
            confirmation?: string;
        } = {};
        await page.route("**/api/v1/agent/sessions/*", async (route) => {
            const r = route.request();
            if (r.method() === "PUT" && !observed.dropped) {
                observed.dropped = {
                    url: r.url(),
                    command: (await r.headerValue("idempotency-key")) ?? "",
                    body: r.postDataJSON() as unknown,
                    authorization: (await r.headerValue("authorization")) ?? ""
                };
                await route.abort("failed");
            } else await route.continue();
        });
        await page.getByRole("button", { name: "＋ 新建研究", exact: true }).click();
        await page
            .getByRole("textbox", { name: "告诉助手你的想法", exact: true })
            .fill("我想研究 BTCUSDT 的放量动量");
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await expect(
            page.getByRole("button", { name: "放弃未接受的操作", exact: true })
        ).toBeVisible();
        await page.reload();
        await page.getByRole("button", { name: "放弃未接受的操作", exact: true }).click();
        await expect(
            page.getByRole("button", { name: "放弃未接受的操作", exact: true })
        ).toHaveCount(0);
        // Additional protocol check after the user abandoned through Shipping UI.
        if (!observed.dropped) throw new Error("fault missing");
        const client = await apiRequest.newContext();
        try {
            const late = await client.put(observed.dropped.url, {
                headers: {
                    Origin: "http://127.0.0.1:5173",
                    Authorization: observed.dropped.authorization,
                    "Idempotency-Key": observed.dropped.command
                },
                data: observed.dropped.body
            });
            expect(late.status()).toBe(409);
        } finally {
            await client.dispose();
        }
        await page.getByRole("button", { name: "＋ 新建研究", exact: true }).click();
        const input = page.getByRole("textbox", { name: "告诉助手你的想法", exact: true });
        await input.fill("我想研究 BTCUSDT 的放量动量");
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await expect(
            page.getByText("你希望观察多少根已收盘 K 线的动量？", { exact: true })
        ).toBeVisible();
        await page.reload();
        await expect(
            page.getByText("你希望观察多少根已收盘 K 线的动量？", { exact: true })
        ).toBeVisible();
        expect(calls).toBe(1);
        await input.fill("用20根已收盘K线，放量也按20根均量比较");
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await expect(
            page.getByRole("heading", { name: "放量动量候选", exact: true })
        ).toBeVisible();
        await expect(
            page.getByRole("region", { name: "因子预览" }).locator("pre").first()
        ).toContainText("mean(volume, 20)");
        const stale = await page.context().newPage();
        await stale.goto(page.url());
        await expect(
            stale.getByRole("heading", { name: "放量动量候选", exact: true })
        ).toBeVisible();
        let withdrawalAttempt: { command: string; body: unknown } | undefined;
        await page.route("**/api/v2/factor-proposals/*/withdrawal", async (route) => {
            const value = {
                command: (await route.request().headerValue("idempotency-key")) ?? "",
                body: route.request().postDataJSON() as unknown
            };
            if (withdrawalAttempt === undefined) {
                withdrawalAttempt = value;
                await route.abort("failed");
            } else {
                expect(value).toEqual(withdrawalAttempt);
                await route.continue();
            }
        });
        await input.fill("改进用途说明，再给我一版");
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await expect(
            page.getByRole("button", { name: "再次提交同一撤回", exact: true })
        ).toBeVisible();
        expect(calls).toBe(2);
        await page.reload();
        await page.getByRole("button", { name: "再次提交同一撤回", exact: true }).click();
        await expect(
            page.getByRole("status").filter({ hasText: "此提案已撤回或更新" })
        ).toBeVisible();
        await input.fill("改进用途说明，再给我一版");
        await expect(
            page.getByRole("button", { name: "确认当前因子", exact: true })
        ).toBeDisabled();
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await modelEntered;
        await stale.getByRole("button", { name: "确认当前因子", exact: true }).click();
        await expect(stale.getByRole("alert")).toContainText("已撤回或被更新");
        returnModel?.();
        await expect(
            page.getByRole("heading", { name: "放量动量改进候选", exact: true })
        ).toBeVisible();
        await stale.close();
        expect(calls).toBe(3);
        await page.getByRole("button", { name: "＋ 新建研究", exact: true }).click();
        await input.fill("测试一个尚不支持的数据输入");
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await expect(
            page.getByRole("button", { name: "保留记录，返回研究历史", exact: true })
        ).toBeVisible();
        await page.getByText("原登记操作详情", { exact: true }).click();
        const rejectedCommand = await page.locator("details code").textContent();
        await page.getByRole("button", { name: "保留记录，返回研究历史", exact: true }).click();
        await expect(page.getByRole("button", { name: "＋ 新建研究", exact: true })).toBeEnabled();
        await selectResearchHistory(page, "不支持的候选");
        await expect(input).toBeDisabled();
        await page.getByText("原登记操作详情", { exact: true }).click();
        await expect(page.locator("details code")).toHaveText(rejectedCommand ?? "");
        await reloadResearch(page);
        await expect(
            page.getByRole("alert").filter({ hasText: "原登记未取得成功证明" })
        ).toBeVisible();
        await expect(input).toBeDisabled();
        await page.getByRole("button", { name: "保留记录，返回研究历史", exact: true }).click();
        await selectResearchHistory(page, "放量动量改进候选");
        await expect(
            page.getByRole("heading", { name: "放量动量改进候选", exact: true })
        ).toBeVisible();
        expect(calls).toBe(4);
        expect(
            await page.evaluate(() =>
                JSON.stringify(
                    [sessionStorage, localStorage].map((storage) =>
                        Object.keys(storage).map((key) => storage.getItem(key))
                    )
                )
            )
        ).not.toContain("controlled-model-secret");
        // Agent outage does not take over or disable backend-owned Human confirmation.
        stopOwnedProcess(agentPid);
        await reloadResearch(page);
        await expect(
            page.getByRole("alert").filter({ hasText: "研究助手暂时无法连接" })
        ).toBeVisible();
        await page.route("**/api/v2/factor-proposals/*/confirmation", async (route) => {
            const r = route.request();
            observed.confirmation = (await r.headerValue("idempotency-key")) ?? undefined;
            await route.fetch(); // Actual canonical commit, then lose only its HTTP acknowledgment.
            await route.abort("failed");
        });
        await page.getByRole("button", { name: "确认当前因子", exact: true }).click();
        await expect(
            page.getByRole("button", { name: "再次提交同一确认", exact: true })
        ).toBeVisible();
        await page.reload();
        await reloadResearch(page);
        await expect(
            page.getByRole("status").filter({ hasText: "计算内容已确认并保存" })
        ).toBeVisible();
        await expect(
            page.getByRole("button", { name: "再次提交同一确认", exact: true })
        ).toHaveCount(0);
        expect(observed.confirmation).toBeDefined();
        expect(calls).toBe(4);
        expect(prohibited).toEqual([]);
        expect(legacy).toEqual([]);
        await writeFile(evidence, JSON.stringify({ name: "放量动量改进候选" }));
        await page.screenshot({
            path: info.outputPath("factor-research-desktop.png"),
            fullPage: true
        });
        await page.setViewportSize({ width: 390, height: 844 });
        await page.screenshot({
            path: info.outputPath("agent-factor-confirmed.png"),
            fullPage: true
        });
        const viewport = await page.evaluate(() => ({
            width: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            overflowing: [...document.querySelectorAll("body *")]
                .map((element) => ({
                    tag: element.tagName,
                    className: element.getAttribute("class"),
                    right: element.getBoundingClientRect().right
                }))
                .filter((element) => element.right > window.innerWidth + 1)
                .slice(-15)
        }));
        expect(viewport.scrollWidth, JSON.stringify(viewport)).toBeLessThanOrEqual(viewport.width);
    } finally {
        returnModel?.();
        server.close();
        await once(server, "close");
    }
});
