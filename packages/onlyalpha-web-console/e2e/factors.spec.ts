import { expect, test } from "@playwright/test";

// The native runner establishes one already-published immutable Factor as a
// read-only precondition. Every observation below uses the ordinary workstation
// entry and real Product API; there are no mocked Product responses.
test("workstation discovers installed calculations and reads exact private Factor metadata", async ({
    page
}) => {
    const commands: string[] = [];
    page.on("request", (request) => {
        if (
            /\/api\/v2\/(research\/(runs|definitions)|backtest|strategy-freezes)/.test(
                request.url()
            ) &&
            request.method() !== "GET"
        )
            commands.push(request.url());
    });
    await page.goto("/");
    const trigger = page.getByRole("button", { name: "因子", exact: true });
    await trigger.click();
    const board = page.getByRole("dialog", { name: "指标 / 因子目录" });
    await expect(board.getByRole("heading", { name: "Factor / Indicator Library" })).toBeVisible();
    await expect(board.getByRole("heading", { name: "Registered calculations" })).toBeVisible();
    await expect(board.getByText("Loading registered calculations…")).toHaveCount(0);
    await expect(board.getByText("Parameters and outputs").first()).toBeVisible();
    await board.getByText("Parameters and outputs").first().click();
    await expect(board.getByText(/Outputs:/).first()).toBeVisible();
    await board
        .getByRole("searchbox", { name: "Search calculations and private Factors" })
        .fill("Retained native metadata");
    await expect(board.getByText("No registered calculations match this search.")).toBeVisible();
    await board.getByRole("button", { name: /Retained native metadata/ }).click();
    const metadata = board.getByRole("article", { name: "Exact Factor metadata" });
    await expect(metadata.getByText("Explicit saved hypothesis")).toBeVisible();
    await expect(metadata.getByText("Factor API", { exact: true })).toBeVisible();
    await expect(metadata.getByText("Revision", { exact: true })).toBeVisible();
    await expect(board.getByRole("button", { name: "Run Research", exact: true })).toBeDisabled();
    await expect(board.getByRole("button", { name: "Open published results" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(board).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(commands).toEqual([]);
});

test("Factor board preserves normal keyboard focus and fits the narrow workstation", async ({
    page
}) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const trigger = page.getByRole("button", { name: "因子", exact: true });
    await trigger.click();
    const board = page.getByRole("dialog", { name: "指标 / 因子目录" });
    await expect(
        board.getByRole("searchbox", { name: "Search calculations and private Factors" })
    ).toBeVisible();
    await page.keyboard.press("Tab");
    expect(await board.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
    await board.getByRole("button", { name: "关闭目录" }).click();
    await expect(trigger).toBeFocused();
});
