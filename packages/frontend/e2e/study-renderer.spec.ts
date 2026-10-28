import { expect, test, type Page, type Locator } from "@playwright/test";

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
        await hoverChart(page, chart);
        await expect(
            page.getByTestId("study-hover").filter({ hasText: "onlyalpha.indicator.sma" }).nth(2)
        ).toHaveAttribute("data-selected", "true");
        await page.getByRole("button", { name: "visibility controlled-2", exact: true }).click();
        await expect(chart).toHaveAttribute("data-pane-count", "3");
        await expect(chart).toHaveAttribute("data-study-series-count", "6");
        await hoverChart(page, chart);
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
        // Volume's interaction canvas overlays its paint canvas and shares the time axis.
        const volumeCanvas = chart.locator("canvas").nth(5);
        // Pane metadata can precede native canvas reflow. A normal hover waits
        // for actionability/stable geometry before selecting the exact point.
        await volumeCanvas.hover();
        const volumeBox = await volumeCanvas.boundingBox();
        if (volumeBox === null) throw new Error("Missing native Volume canvas");
        await page.mouse.move(
            volumeBox.x + volumeBox.width * 0.9,
            volumeBox.y + volumeBox.height * 0.5
        );
        await expect(page.getByTestId("study-hover").first()).toContainText(
            "100.500000000000000001"
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
            body: await page.screenshot({
                path: test
                    .info()
                    .outputPath(
                        `controlled-${String(width)}-${String(test.info().attachments.length)}.png`
                    )
            })
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

test("CONTROLLED_TEST_EVIDENCE repeated preview with studies does not drift the viewport", async ({
    page
}) => {
    await page.goto("http://127.0.0.1:4180/e2e/support/study-renderer.html");
    const chart = page.getByTestId("price-chart");
    await expect(chart).toHaveAttribute("data-study-series-count", "8");
    const readRange = async () => ({
        from: Number(await chart.getAttribute("data-visible-range-from")),
        to: Number(await chart.getAttribute("data-visible-range-to"))
    });
    await chart.locator("canvas").nth(1).hover();
    const before = await readRange();
    await page.getByRole("button", { name: "preview tick", exact: true }).click();
    await expect(chart).toHaveAttribute("data-volume-point-count", "81");
    await expect.poll(async () => (await readRange()).from).toBeCloseTo(before.from + 1, 8);
    await expect.poll(async () => (await readRange()).to).toBeCloseTo(before.to + 1, 8);
    const first = await readRange();
    for (let tick = 0; tick < 5; tick++) {
        await page.getByRole("button", { name: "preview tick", exact: true }).click();
        await expect(chart).toHaveAttribute("data-volume-latest", "2.1234567890123456789");
        await chart.locator("canvas").nth(1).hover();
        expect(await readRange()).toEqual(first);
    }
});

for (const width of [1440, 1024, 390]) {
    test(`CONTROLLED_TEST_EVIDENCE unit axes, volume colors and display timezone at ${String(width)}px`, async ({
        page
    }) => {
        const requests: string[] = [],
            errors: string[] = [];
        page.on("request", (request) => {
            if (new URL(request.url()).pathname.startsWith("/api/")) requests.push(request.url());
        });
        page.on("pageerror", (error) => errors.push(error.message));
        await page.setViewportSize({ width, height: 1000 });
        await page.goto("http://127.0.0.1:4180/e2e/support/study-renderer.html");
        const chart = page.getByTestId("price-chart");
        await expect(chart).toHaveAttribute("data-pane-count", "4");
        await expect(chart).toHaveAttribute("data-study-series-count", "8");
        const from = await chart.getAttribute("data-visible-range-from");
        const to = await chart.getAttribute("data-visible-range-to");
        const box = await chart.locator("canvas").first().boundingBox();
        if (!box || box.height < 100) throw new Error("Native price canvas must remain usable");
        const select = page.getByRole("combobox", { name: "显示时区" });
        await expect(select).toHaveValue("UTC");
        await select.focus();
        await page.keyboard.press("ArrowDown");
        await page.keyboard.press("Enter");
        await expect(select).toHaveValue("USER_LOCAL");
        await select.selectOption("Asia/Shanghai");
        await expect(select).toHaveValue("Asia/Shanghai");
        await page.keyboard.press("Escape");
        await expect(chart).toHaveAttribute("data-visible-range-from", from ?? "");
        await expect(chart).toHaveAttribute("data-visible-range-to", to ?? "");
        await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.5);
        await expect(page.getByTestId("study-hover").first()).toContainText(
            "102.000000000000000001"
        );
        await expect(page.getByTestId("study-hover").first()).toContainText("UTC ns");
        await expect(
            page
                .getByRole("tooltip", { name: "K 线信息" })
                .locator("[data-observation-field=volume]")
        ).toHaveText("2.1234567890123456789");
        // Read native paint pixels only: no renderer state or product state injection.
        const volumeColors = await chart
            .locator("canvas")
            .nth(4)
            .evaluate((element) => {
                const canvas = element as HTMLCanvasElement;
                const pixels = canvas
                    .getContext("2d")
                    ?.getImageData(0, 0, canvas.width, canvas.height).data;
                let up = 0,
                    down = 0;
                if (pixels)
                    for (let i = 0; i < pixels.length; i += 4) {
                        if (pixels[i] === 200 && pixels[i + 1] === 51 && pixels[i + 2] === 42) up++;
                        if (pixels[i] === 47 && pixels[i + 1] === 125 && pixels[i + 2] === 71)
                            down++;
                    }
                return { up, down };
            });
        expect(volumeColors.up).toBeGreaterThan(20);
        expect(volumeColors.down).toBeGreaterThan(20);
        await test.info().attach(`task2-price-volume-timezone-${String(width)}`, {
            contentType: "image/png",
            body: await page.screenshot({
                path: test
                    .info()
                    .outputPath(
                        `controlled-${String(width)}-${String(test.info().attachments.length)}.png`
                    )
            })
        });
        await select.selectOption("USER_LOCAL");
        await expect(select).toHaveValue("USER_LOCAL");
        await page.getByRole("button", { name: "controlled units", exact: true }).click();
        await expect(chart).toHaveAttribute("data-pane-count", "6");
        await hoverChart(page, chart);
        await expect(page.getByTestId("study-hover").first()).toContainText("PERCENT · 独立纵轴");
        await expect(page.getByTestId("study-hover").nth(1)).toContainText("单位未知 · 独立纵轴");
        await expect(chart).toHaveAttribute("data-study-series-count", "8");
        await test.info().attach(`task2-independent-units-${String(width)}`, {
            contentType: "image/png",
            body: await page.screenshot({
                path: test
                    .info()
                    .outputPath(
                        `controlled-${String(width)}-${String(test.info().attachments.length)}.png`
                    )
            })
        });
        await page.getByRole("button", { name: "preview tick", exact: true }).click();
        await expect(chart).toHaveAttribute("data-volume-point-count", "81");
        await expect(chart).toHaveAttribute("data-volume-latest", "2.1234567890123456789");
        await expect(select).toBeVisible();
        const selectBox = await select.boundingBox();
        expect(selectBox?.height ?? 0).toBeGreaterThanOrEqual(24);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
            width
        );
        expect(requests).toEqual([]);
        expect(errors).toEqual([]);
    });
}

async function hoverChart(page: Page, chart: Locator) {
    const canvas = chart.locator("canvas").nth(1);
    await canvas.hover();
    const box = await canvas.boundingBox();
    if (!box) throw new Error("Visible plot required");
    await page.mouse.move(box.x + box.width * 0.9, box.y + box.height * 0.5);
}
