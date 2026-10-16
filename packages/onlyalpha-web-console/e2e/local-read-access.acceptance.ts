import { expect, test } from "@playwright/test";

test("shipping workspace uses authenticated Source history and AUTH-first native WS without writes", async ({
    page,
    request
}) => {
    const token = "ee".repeat(32); // Synthetic fixture only, never bundled or a production credential.
    const methods: string[] = [];
    const websocketEvents: string[] = [];
    const leaks: string[] = [];
    let resolvePreview!: () => void;
    const receivedPreview = new Promise<void>((resolve) => {
        resolvePreview = resolve;
    });
    page.on("request", (req) => {
        if (req.url().includes("/api/")) methods.push(req.method());
        if (req.url().includes(token)) leaks.push("url");
    });
    page.on("console", (message) => {
        if (message.text().includes(token)) leaks.push("console");
    });
    page.on("pageerror", (error) => {
        if (error.message.includes(token)) leaks.push("exception");
    });
    page.on("websocket", (socket) => {
        if (socket.url().includes(token)) leaks.push("websocket-url");
        socket.on("framesent", (frame) => {
            const value = JSON.parse(String(frame.payload)) as { operation: string };
            websocketEvents.push(value.operation);
        });
        socket.on("framereceived", (frame) => {
            const value = JSON.parse(String(frame.payload)) as { event: string };
            websocketEvents.push(value.event);
            if (value.event === "BAR_PREVIEW") resolvePreview();
            if (String(frame.payload).includes(token)) leaks.push("response");
        });
    });
    expect((await request.get("/api/v2/market-data/sources")).status()).toBe(401);
    await page.goto("/");
    await page.getByText("本地只读访问", { exact: true }).click();
    await page.getByLabel("本地行情凭据").fill(token);
    const sourceResponse = page.waitForResponse(
        (response) =>
            response.url().includes("/api/v2/market-data/sources") && response.status() === 200
    );
    await page.getByRole("button", { name: "连接只读行情" }).click();
    await sourceResponse;
    await expect(page.getByLabel("数据源").locator("option")).toHaveCount(2);
    await page.getByText("行情设置", { exact: true }).click();
    await page.getByLabel("数据源").selectOption({ index: 1 });
    await expect(page.getByLabel("时间周期")).toBeEnabled();
    await page.getByLabel("时间周期").selectOption("1");
    await page.getByRole("button", { name: "搜索商品", exact: true }).click();
    await page
        .getByRole("dialog", { name: "商品搜索" })
        .getByRole("searchbox", { name: "商品代码或名称" })
        .fill("BTCUSDT");
    const historyResponse = page.waitForResponse((response) => {
        const semantic = new URL(response.url()).searchParams.get("bar_semantic");
        return (
            response.url().includes("/api/v2/market-data/bars") &&
            response.status() === 200 &&
            semantic !== null &&
            (JSON.parse(semantic) as { formation: { window_minutes: number } }).formation
                .window_minutes === 1
        );
    });
    await page.getByRole("button", { name: /查看 BTCUSDT · TEST ·/ }).click();
    const history = (await (await historyResponse).json()) as {
        coverage: { status: string };
        bars: unknown[];
    };
    expect(history.coverage.status).toBe("COMPLETE");
    expect(history.bars).toHaveLength(1440);
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "1440"
    );
    await expect(page.locator("canvas").first()).toBeVisible();
    await receivedPreview;
    expect(websocketEvents.slice(0, 4)).toEqual([
        "AUTH",
        "AUTHENTICATED",
        "SUBSCRIBE_BAR",
        "SUBSCRIBED"
    ]);
    expect(methods).not.toContain("POST");
    expect(
        await page.evaluate(() => ({
            local: localStorage.length,
            session: sessionStorage.length,
            cookie: document.cookie
        }))
    ).toEqual({ local: 0, session: 0, cookie: "" });
    await page.getByText("本地只读访问", { exact: true }).click();
    await expect(page.getByLabel("本地行情凭据")).toHaveValue("");
    await page.getByRole("button", { name: "清除凭据" }).click();
    await expect(page.getByTestId("market-data-status")).toHaveAttribute(
        "data-loaded-bar-count",
        "0"
    );
    await expect(page.getByTestId("market-data-observation")).toHaveAttribute(
        "data-chart-context-key",
        ""
    );
    await expect(page.locator('[data-observation-field="close"]')).toHaveText("—");
    expect(leaks).toEqual([]);
    expect(
        (
            await request.post("/api/v2/market-data/acquisitions", {
                headers: { Authorization: `Bearer ${token}` },
                data: {}
            })
        ).status()
    ).toBe(403);
    expect((await request.get("/health")).status()).toBe(200); // Compares every PG/CH table's count + content hash.
});
