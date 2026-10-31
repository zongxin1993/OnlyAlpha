import { expect, type Page } from "@playwright/test";

export async function openModelSettings(page: Page) {
    await page.getByRole("button", { name: "全局设置", exact: true }).click();
    await page.getByRole("tab", { name: "模型", exact: true }).click();
}

export async function enableResearchAssistant(page: Page) {
    await page.getByRole("button", { name: "启用助手", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "启用研究助手", exact: true });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "允许并启用", exact: true }).click();
}

export async function selectResearchHistory(page: Page, label: string) {
    await page
        .getByRole("navigation", { name: "研究历史", exact: true })
        .getByText(label, { exact: true })
        .click();
}

export async function reloadResearch(page: Page) {
    await page.getByRole("button", { name: "更多研究操作", exact: true }).click();
    await page.getByRole("button", { name: "核对并重新载入", exact: true }).click();
    await page.getByRole("heading", { name: "因子研究", exact: true }).click();
}
