import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import { once } from "node:events";
import { z } from "zod";
import { expect, test } from "@playwright/test";

test("Human chat confirms one exact saved factor without Research and restores after restart", async ({
    page
}, info) => {
    const evidence = process.env.ONLYALPHA_BROWSER_RESTART_EVIDENCE;
    if (evidence === undefined) throw new Error("canonical restart harness required");
    const business: string[] = [];
    page.on("request", (r) => {
        if (
            r.method() !== "GET" &&
            /\/api\/v2\/(research\/runs|research\/runtime-generations|agent\/|backtest)/.test(
                r.url()
            )
        )
            business.push(r.url());
    });
    await page.goto("/");
    await page.getByRole("link", { name: "因子研究", exact: true }).click();
    await expect(page.getByRole("heading", { name: "因子研究", exact: true })).toBeVisible();
    if (process.env.ONLYALPHA_BROWSER_RESTART_PHASE === "restored") {
        const old = z
            .object({ name: z.string() })
            .parse(JSON.parse(await readFile(evidence, "utf8")));
        await page
            .getByRole("combobox", { name: "研究历史", exact: true })
            .selectOption({ label: old.name });
        await expect(page.getByRole("heading", { name: old.name, exact: true })).toBeVisible();
        await expect(
            page.getByRole("status").filter({ hasText: "计算内容已确认并保存" })
        ).toBeVisible();
        await page.getByText("高级详情：代码与契约", { exact: true }).click();
        await expect(page.locator("pre").filter({ hasText: "def calculate" })).toContainText(
            "api.mul"
        );
        expect(business).toEqual([]);
        return;
    }
    let calls = 0;
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
            calls += 1;
            const body = z
                .object({ messages: z.array(z.object({ role: z.string(), content: z.string() })) })
                .parse(JSON.parse(Buffer.concat(chunks).toString()));
            if (body.messages.length < 2) {
                response.writeHead(400).end();
                return;
            }
            const candidate = {
                name: "放量动量候选",
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
            response.setHeader("content-type", "application/json");
            response.end(
                JSON.stringify({
                    id: `controlled-${String(calls)}`,
                    model: "controlled-factor-model-v1",
                    choices: [
                        {
                            message: {
                                content: JSON.stringify({
                                    message:
                                        calls === 1
                                            ? "你希望观察多少根已收盘 K 线的动量？"
                                            : "这是因子草稿，请核对公式后确认。",
                                    candidate: calls === 1 ? null : candidate
                                })
                            }
                        }
                    ]
                })
            );
        });
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    try {
        const address = server.address();
        if (address === null || typeof address === "string") throw new Error("address");
        await page.getByText("模型设置", { exact: true }).click();
        await page.getByRole("button", { name: "添加模型", exact: true }).click();
        await expect(page.getByRole("heading", { name: "聊天模型", exact: true })).toBeVisible();
        await page
            .getByLabel("服务地址", { exact: true })
            .fill(`http://127.0.0.1:${String(address.port)}/v1`);
        await page.getByLabel("模型名称", { exact: true }).fill("controlled-factor-model-v1");
        await page.getByLabel("模型版本说明", { exact: true }).fill("controlled-v1");
        await page.getByRole("button", { name: "保存草稿", exact: true }).click();
        await page.getByLabel("更换 API 密钥", { exact: true }).fill("controlled-model-secret");
        await page.getByRole("button", { name: "更换凭据", exact: true }).click();
        await page.getByRole("button", { name: "发布 Revision", exact: true }).click();
        await expect(page.getByRole("alert")).toHaveCount(0);
        await page.getByRole("button", { name: "← 返回列表", exact: true }).click();
        const observed: {
            dropped?: { url: string; command: string; body: Record<string, unknown> };
            messageRequest?: { url: string; command: string; body: Record<string, unknown> };
        } = {};
        await page.route("**/api/v2/factor-chats/*/commands", async (route) => {
            const r = route.request();
            const body = z.record(z.string(), z.unknown()).parse(r.postDataJSON());
            const command = await r.headerValue("idempotency-key");
            if (command === null) throw new Error("Command required");
            if (
                body.operation === "CREATE" &&
                body.abandon !== true &&
                observed.dropped === undefined
            ) {
                observed.dropped = { url: r.url(), command, body };
                await route.abort("failed");
                return;
            }
            if (body.operation === "MESSAGE")
                observed.messageRequest = { url: r.url(), command, body };
            await route.continue();
        });
        await page.getByRole("button", { name: "新建对话", exact: true }).click();
        await expect(
            page.getByRole("button", { name: "放弃未接受的操作", exact: true })
        ).toBeVisible();
        await page.reload();
        await page.getByRole("button", { name: "放弃未接受的操作", exact: true }).click();
        await expect(
            page.getByRole("button", { name: "放弃未接受的操作", exact: true })
        ).toHaveCount(0);
        // Additional protocol regression after the user completed abandonment through the normal UI.
        if (observed.dropped === undefined) throw new Error("fault not observed");
        const abandoned = observed.dropped;
        const late = await page.request.post(abandoned.url, {
            headers: { Origin: "http://127.0.0.1:5173", "Idempotency-Key": abandoned.command },
            data: abandoned.body
        });
        expect(late.status()).toBe(409);
        await page.getByRole("button", { name: "新建对话", exact: true }).click();
        const input = page.getByLabel("告诉 Agent 你的想法", { exact: true });
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
        await input.fill("确认因子");
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await expect(
            page.getByRole("status").filter({ hasText: "计算内容已确认并保存" })
        ).toBeVisible();
        expect(calls).toBe(2);
        // Protocol replay is checked separately from ordinary user submission above.
        if (observed.messageRequest === undefined) throw new Error("message command not observed");
        const original = observed.messageRequest;
        const replay = await page.request.post(original.url, {
            headers: { Origin: "http://127.0.0.1:5173", "Idempotency-Key": original.command },
            data: original.body
        });
        expect(replay.ok()).toBe(true);
        expect(calls).toBe(2);
        await page.reload();
        await expect(
            page.getByRole("status").filter({ hasText: "计算内容已确认并保存" })
        ).toBeVisible();
        expect(calls).toBe(2);
        expect(business).toEqual([]);
        await writeFile(evidence, JSON.stringify({ name: "放量动量候选" }));
        await page.setViewportSize({ width: 390, height: 844 });
        expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
        ).toBe(true);
        await page.screenshot({
            path: info.outputPath("factor-chat-confirmed.png"),
            fullPage: true
        });
    } finally {
        server.close();
        await once(server, "close");
    }
});
