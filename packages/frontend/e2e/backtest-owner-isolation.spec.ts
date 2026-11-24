import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { z } from "zod";

const owner = z.strictObject({
    subject_id: z.string().min(1),
    credential: z.string().regex(/^[0-9a-f]{64}$/i),
    run_id: z.uuid()
});
type Owner = z.infer<typeof owner>;
const fixture = z.strictObject({ owners: z.tuple([owner, owner]) });
const sessionPath = "/api/v2/human/session";
const runPath = (run: string) => `/api/v2/backtest/runs/${run}`;

function waitFor(page: Page, method: string, path: string) {
    return page.waitForResponse(
        (response) =>
            new URL(response.url()).pathname === path && response.request().method() === method
    );
}

async function login(page: Page, user: Owner) {
    const initial = waitFor(page, "GET", sessionPath);
    await page.goto("/");
    expect((await initial).status()).toBe(401);
    const credential = page.getByLabel("登录凭据", { exact: true });
    await expect(credential).toBeVisible();
    await credential.focus();
    try {
        await page.keyboard.insertText(user.credential);
    } catch {
        throw new Error("无法输入测试登录凭据");
    }
    const authenticated = waitFor(page, "POST", sessionPath);
    const restored = waitFor(page, "GET", sessionPath);
    await credential.press("Enter");
    expect((await authenticated).status()).toBe(200);
    const response = await restored;
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ subject_id: user.subject_id, can_logout: true });
    await expect(page.getByText(`当前用户：${user.subject_id}`, { exact: true })).toBeVisible();
}

async function openOwnRun(page: Page, user: Owner, foreign: Owner) {
    await page
        .getByRole("navigation", { name: "产品导航" })
        .getByRole("link", { name: "回测", exact: true })
        .click();
    const link = page.locator(`a[href="/backtest/runs/${user.run_id}"]`);
    await expect(link).toBeVisible();
    await expect(page.locator(`a[href="/backtest/runs/${foreign.run_id}"]`)).toHaveCount(0);
    const detail = waitFor(page, "GET", runPath(user.run_id));
    await link.click();
    const response = await detail;
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ run_id: user.run_id });
    await expect(page.getByText("账户权益与回撤", { exact: true })).toBeVisible();
    return page.url();
}

test.use({ trace: "off", screenshot: "off", video: "off" });

test("两个登录用户各自查看回测，访问他人的同一条回测返回不可见", async ({ browser, baseURL }) => {
    const path = process.env.ONLYALPHA_BROWSER_HUMAN_FIXTURE;
    if (!path || !baseURL) throw new Error("需要正式工作台地址和双用户测试夹具");
    const {
        owners: [a, b]
    } = fixture.parse(JSON.parse(await readFile(path, "utf8")));
    expect(a.subject_id).not.toBe(b.subject_id);
    expect(a.run_id).not.toBe(b.run_id);
    if (a.credential === b.credential) throw new Error("测试用户的凭据必须独立");
    const aContext = await browser.newContext({ baseURL });
    const bContext = await browser.newContext({ baseURL });
    try {
        const first = await aContext.newPage();
        const second = await bContext.newPage();
        await login(first, a);
        await login(second, b);
        const firstDetail = await openOwnRun(first, a, b);
        await openOwnRun(second, b, a);
        const denied = waitFor(second, "GET", runPath(a.run_id));
        await second.goto(firstDetail);
        const response = await denied;
        expect(response.status()).toBe(404);
        expect(await response.json()).toMatchObject({ error: { code: "BACKTEST_RUN_NOT_FOUND" } });
        await expect(
            second.getByText("无法查看这次回测，请返回回测记录查看自己的任务。", { exact: true })
        ).toBeVisible();
        await expect(second.getByText("账户权益与回撤", { exact: true })).toHaveCount(0);
        const logout = waitFor(second, "DELETE", sessionPath);
        await second.getByRole("button", { name: "退出登录" }).click();
        expect((await logout).status()).toBe(204);
        await expect(second.getByLabel("登录凭据")).toBeVisible();
        const retained = waitFor(first, "GET", runPath(a.run_id));
        await first.reload();
        expect((await retained).status()).toBe(200);
        await expect(first.getByText("账户权益与回撤", { exact: true })).toBeVisible();
    } finally {
        await Promise.all([aContext.close(), bContext.close()]);
    }
});
