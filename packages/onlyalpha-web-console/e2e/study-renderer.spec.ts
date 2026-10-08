import { expect, test } from "@playwright/test";

for (const width of [1440, 1024, 390]) {
    test(`CONTROLLED_TEST_EVIDENCE multi-pane renderer preserves identities, gaps and viewport at ${String(width)}px`, async ({
        page
    }) => {
        const errors: string[] = [];
        const productRequests: string[] = [];
        page.on("pageerror", (error) => errors.push(error.message));
        page.on("request", (request) => {
            const url = new URL(request.url());
            if (url.pathname.startsWith("/api/") || url.hostname.includes("binance"))
                productRequests.push(request.url());
        });
        await page.setViewportSize({ width, height: 1000 });
        await page.goto("http://127.0.0.1:4180/e2e/support/study-renderer.html");
        const chart = page.getByTestId("price-chart");
        await expect(chart).toHaveAttribute("data-study-series-count", "8");
        await expect(chart).toHaveAttribute("data-pane-count", "4");
        const from = await chart.getAttribute("data-visible-range-from"),
            to = await chart.getAttribute("data-visible-range-to");
        // Use the native plot canvas, excluding price-scale cells. The final
        // 10% contains admitted fixture points at every viewport width; the
        // wide chart's left region legitimately contains no point identity.
        const box = await chart.locator("canvas").first().boundingBox();
        if (box === null) throw new Error("Missing chart");
        await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.5);
        await expect(page.getByTestId("study-hover").first()).toContainText(
            "102.000000000000000001"
        );
        await expect(page.getByTestId("study-hover").first()).toContainText("READY");
        await page.getByRole("button", { name: "select controlled-2", exact: true }).click();
        await expect(
            page.getByTestId("study-hover").filter({ hasText: "onlyalpha.indicator.sma" }).nth(2)
        ).toHaveAttribute("data-selected", "true");
        await page.getByRole("button", { name: "visibility controlled-2", exact: true }).click();
        await expect(chart).toHaveAttribute("data-pane-count", "3");
        await expect(chart).toHaveAttribute("data-study-series-count", "6");
        await expect(page.getByTestId("study-hover")).toHaveCount(3);
        await page.getByRole("button", { name: "visibility controlled-2", exact: true }).click();
        await expect(chart).toHaveAttribute("data-pane-count", "4");
        await page.getByRole("button", { name: "placement controlled-2", exact: true }).click();
        await expect(chart).toHaveAttribute("data-pane-count", "3");
        await expect(chart).toHaveAttribute("data-study-series-count", "8");
        await page.getByRole("button", { name: "remove controlled-0", exact: true }).click();
        await expect(chart).toHaveAttribute("data-study-series-count", "6");
        await expect(chart).toHaveAttribute("data-visible-range-from", from ?? "");
        await expect(chart).toHaveAttribute("data-visible-range-to", to ?? "");
        // Moving panes must not retire the chart's crosshair callback. The
        // second native plot canvas is Volume, sharing the same time axis.
        const volumeBox = await chart.locator("canvas").nth(4).boundingBox();
        if (volumeBox === null) throw new Error("Missing native Volume canvas");
        await page.mouse.move(
            volumeBox.x + volumeBox.width * 0.9,
            volumeBox.y + volumeBox.height * 0.5
        );
        await expect(page.getByTestId("study-hover").first()).toContainText(
            "102.000000000000000001"
        );
        await page.getByRole("button", { name: "chart type", exact: true }).click();
        await expect(chart).toHaveAttribute("data-chart-type", "LINE");
        await expect(chart).toHaveAttribute("data-volume-point-count", "80");
        await page.getByRole("button", { name: "prepend history", exact: true }).click();
        await expect(chart).toHaveAttribute("data-volume-point-count", "81");
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
            width
        );
        await test.info().attach("controlled-renderer", {
            contentType: "image/png",
            body: await page.screenshot()
        });
        await page.getByRole("button", { name: "change context", exact: true }).click();
        await expect(chart).toHaveAttribute("data-study-series-count", "0");
        await expect(chart).toHaveAttribute("data-pane-count", "2");
        await expect(page.getByTestId("study-hover")).toHaveCount(0);
        await page.getByRole("button", { name: "mount / unmount", exact: true }).click();
        await expect(chart).toHaveCount(0);
        await page.getByRole("button", { name: "mount / unmount", exact: true }).click();
        await expect(chart).toHaveAttribute("data-pane-count", "2");
        expect(errors).toEqual([]);
        expect(productRequests).toEqual([]);
    });
}
