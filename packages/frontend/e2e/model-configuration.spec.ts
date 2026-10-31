import { networkInterfaces } from "node:os";
import { createServer } from "node:http";
import { once } from "node:events";
import { expect, test, request as apiRequest, type Page } from "@playwright/test";
import { z } from "zod";
import { enableResearchAssistant, openModelSettings } from "./support/factorChatUi";

const modelPath = /\/api\/v1\/agent\/models\/[^/]+$/;
const receipt = z.object({
    id: z.uuid(),
    owner: z.string(),
    name: z.string(),
    credential_generation: z.uuid()
});

async function openModelEditor(page: Page) {
    await page.goto("/factor-research");
    await expect(page.getByRole("heading", { name: "因子研究", exact: true })).toBeVisible();
    await openModelSettings(page);
    await page
        .getByRole("dialog", { name: "设置", exact: true })
        .getByRole("button", { name: "添加模型", exact: true })
        .click();
}

async function fillModel(page: Page, name: string, endpoint: string) {
    const form = page.getByRole("form", { name: "模型配置", exact: true });
    await form.getByLabel("配置名称", { exact: true }).fill(name);
    await form.getByLabel("服务地址", { exact: true }).fill(endpoint);
    await form.getByLabel("模型名称", { exact: true }).fill("fixture-factor-model");
    await form.getByLabel("模型版本说明", { exact: true }).fill("fixture-v1");
    await form.getByLabel("API 密钥", { exact: true }).fill("fixture-model-key-not-a-secret");
}

test("LAN HTTP model testing and saving recover the original accepted save after a lost acknowledgement", async ({
    page
}) => {
    const writes: { url: string; command: string }[] = [];
    let accepted: z.infer<typeof receipt> | undefined;
    await page.route("**/api/v1/agent/models/*", async (route) => {
        const request = route.request();
        if (request.method() !== "PUT") {
            await route.continue();
            return;
        }
        const command = (await request.headerValue("idempotency-key")) ?? "";
        writes.push({ url: request.url(), command });
        // The real Agent commits once; only the browser acknowledgement is lost.
        // route.fetch() uses the browser cookie jar even for credentials: omit.
        // Forward the original UI request through an empty transport so the
        // backend Human cookie cannot cross into the Agent boundary.
        const transport = await apiRequest.newContext();
        try {
            const response = await transport.fetch(request);
            expect(response.status()).toBe(200);
            accepted = receipt.parse(await response.json());
            expect(new URL(request.url()).pathname).toBe(`/api/v1/agent/models/${accepted.id}`);
            expect(accepted.credential_generation).toBe(command);
        } finally {
            await transport.dispose();
        }
        await route.abort("failed");
    });
    await openModelEditor(page);
    const name = "回执核对模型";
    const server = createServer((request, response) => {
        expect(request.url).toBe("/v1/chat/completions");
        expect(request.headers.authorization).toBe("Bearer fixture-model-key-not-a-secret");
        const chunks: Buffer[] = [];
        request.on("data", (chunk: Buffer) => chunks.push(chunk));
        request.on("end", () => {
            const body = z
                .object({ messages: z.array(z.object({ content: z.string() })) })
                .parse(JSON.parse(Buffer.concat(chunks).toString()));
            const content =
                body.messages.length === 1
                    ? "连接成功。"
                    : JSON.stringify({ message: "局域网模型聊天已连接。", candidate: null });
            response.writeHead(200, { "Content-Type": "application/json" });
            response.end(JSON.stringify({ choices: [{ message: { content } }] }));
        });
    });
    server.listen(0, "0.0.0.0");
    await once(server, "listening");
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("controlled provider unavailable");
    const lanAddress = Object.values(networkInterfaces())
        .flat()
        .find(
            (entry) =>
                entry?.family === "IPv4" &&
                !entry.internal &&
                /^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)/.test(entry.address)
        )?.address;
    if (!lanAddress) throw new Error("canonical container LAN address required");
    await fillModel(page, name, `http://${lanAddress}:${String(address.port)}/v1`);
    await expect(page.getByRole("button", { name: "保存模型设置", exact: true })).toBeDisabled();
    try {
        await page.getByRole("button", { name: "测试连接", exact: true }).click();
        await expect(page.getByText("连接成功。", { exact: true })).toBeVisible();
        await expect(page.getByRole("region", { name: "待核对的操作", exact: true })).toHaveCount(
            0
        );
        await expect(page.getByRole("button", { name: "保存模型设置", exact: true })).toBeEnabled();
        const [resolution] = await Promise.all([
            page.waitForResponse(
                (response) =>
                    response.request().method() === "POST" &&
                    /\/api\/v1\/agent\/commands\/[^/]+\/abandon$/.test(
                        new URL(response.url()).pathname
                    )
            ),
            page.getByRole("button", { name: "保存模型设置", exact: true }).click()
        ]);
        expect(resolution.status()).toBe(200);
        if (!accepted) throw new Error("canonical Agent model save was not observed");
        const saved = accepted;
        expect(await resolution.json()).toMatchObject({ status: "ACCEPTED", outcome: saved });
        await expect(page.getByText("模型设置已保存", { exact: true })).toBeVisible();
        await expect(page.getByRole("form", { name: "模型配置", exact: true })).toHaveCount(0);
        await expect(page.getByRole("button", { name: "核对保存结果", exact: true })).toHaveCount(
            0
        );
        await expect(
            page.getByRole("button", { name: "放弃未接受的保存", exact: true })
        ).toHaveCount(0);
        await page.reload();
        await openModelSettings(page);
        await expect(
            page.getByRole("dialog", { name: "设置", exact: true }).getByText(name, { exact: true })
        ).toBeVisible();
        await page.getByRole("button", { name: "关闭设置", exact: true }).click();
        await expect(
            page.locator(".factor-composer-footer").getByText(name, { exact: true })
        ).toBeVisible();
        expect(writes).toHaveLength(1);
        expect(writes[0].command).toBe(saved.credential_generation);
        await enableResearchAssistant(page);
        await page
            .getByRole("textbox", { name: "告诉助手你的想法", exact: true })
            .fill("测试本地模型的普通对话");
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await expect(page.getByText("局域网模型聊天已连接。", { exact: true })).toBeVisible();
    } finally {
        server.close();
        await once(server, "close");
    }
});

test("A rejected connection test explains the address and never creates a pending save", async ({
    page
}) => {
    const writes: string[] = [];
    page.on("request", (request) => {
        if (request.method() === "PUT" && modelPath.test(new URL(request.url()).pathname))
            writes.push(request.url());
    });
    await openModelEditor(page);
    await fillModel(page, "无效的公网 HTTP 模型", "http://8.8.8.8:58080/v1");
    const [rejection] = await Promise.all([
        page.waitForResponse(
            (response) =>
                response.request().method() === "POST" &&
                new URL(response.url()).pathname === "/api/v1/agent/models/test"
        ),
        page.getByRole("button", { name: "测试连接", exact: true }).click()
    ]);
    expect(rejection.status()).toBe(400);
    await expect(page.getByText(/公网地址请使用 HTTPS/)).toBeVisible();
    await expect(page.getByRole("button", { name: "保存模型设置", exact: true })).toBeDisabled();
    await expect(page.getByRole("region", { name: "待核对的操作", exact: true })).toHaveCount(0);
    expect(writes).toEqual([]);
});
