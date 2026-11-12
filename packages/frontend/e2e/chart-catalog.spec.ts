import { expect, test, type Page } from "@playwright/test";
import {
    controlledRealtime,
    fingerprint,
    status,
    studySample
} from "./support/temporaryMarketData";

// The workspace catalog dialog renders the CHART_STUDY_TRANSIENT surface: the
// official /api/v2/chart/studies/capabilities projection, never the Research
// exact-registered path. Determinism comes from re-fingerprinted variants of
// test-data/web/chart-studies/query.json so client admission self-verification
// (api/chartStudies/client.ts readChartStudyCapabilities) passes unchanged.

const variantLabels: readonly (readonly [string, string])[] = [
    ["SMA", "onlyalpha.indicator.sma"],
    ["变体乙", "onlyalpha.indicator.sma2"],
    ["变体丙", "onlyalpha.indicator.sma3"],
    ["变体丁", "onlyalpha.indicator.sma4"],
    ["变体戊", "onlyalpha.indicator.sma5"],
    ["变体己", "onlyalpha.indicator.sma6"],
    ["变体庚", "onlyalpha.indicator.sma7"],
    ["变体辛", "onlyalpha.indicator.sma8"]
];

// A Capability Identity variant: every field pairing the client admission
// re-verifies (descriptor mirror, calculation_type_reference, presentation
// mirror) moves together, then the canonical fingerprints are recomputed.
async function capabilityVariant(
    displayName: string,
    typeId: string
): Promise<Record<string, unknown>> {
    const capability = structuredClone(studySample.capability) as Record<string, unknown> & {
        capability_projection: Record<string, unknown>;
        descriptor: Record<string, unknown>;
        presentation: Record<string, unknown>;
    };
    const projection = capability.capability_projection;
    const projectionDescriptor = projection.descriptor as Record<string, unknown>;
    const projectionPresentation = projection.presentation as Record<string, unknown>;
    const implementation = projection.implementation as Record<string, unknown>;
    (implementation.calculation_type_reference as Record<string, unknown>).type_id = typeId;
    capability.type_id = typeId;
    capability.descriptor.type_id = typeId;
    projectionDescriptor.type_id = typeId;
    capability.presentation.display_name = displayName;
    projectionPresentation.display_name = displayName;
    capability.descriptor_fingerprint = await fingerprint(projectionDescriptor);
    capability.capability_projection_fingerprint = await fingerprint(projection);
    return capability;
}

async function catalogVariants(): Promise<readonly Record<string, unknown>[]> {
    const variants: Record<string, unknown>[] = [];
    for (const [displayName, typeId] of variantLabels)
        variants.push(await capabilityVariant(displayName, typeId));
    return variants;
}

const openCatalog = async (page: Page) => {
    await page.getByRole("button", { name: "目录", exact: true }).click();
    return page.getByRole("dialog", { name: "指标 / 因子目录" });
};

test("the transient catalog pages eight Capabilities and hands one draft over", async ({
    page
}) => {
    const variants = await catalogVariants();
    const researchRequests: string[] = [];
    page.on("request", (request) => {
        const path = new URL(request.url()).pathname;
        if (path.startsWith("/api/v2/research/")) researchRequests.push(path);
    });
    await controlledRealtime(page, { capabilities: () => variants });
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    const dialog = await openCatalog(page);
    await expect(
        dialog.getByText("CHART_STUDY_TRANSIENT · DISPLAY_ONLY · 不是 Research Result")
    ).toBeVisible();
    await expect(dialog.getByRole("status")).toContainText("8 类指标");
    const pagination = dialog.getByRole("navigation", { name: "目录分页" });
    await expect(pagination).toContainText("共 8 项 · 第 1 / 2 页");
    await expect(pagination.getByRole("button", { name: "上一页" })).toBeDisabled();
    await pagination.getByRole("button", { name: "下一页" }).click();
    await expect(pagination).toContainText("共 8 项 · 第 2 / 2 页");
    await expect(dialog.getByRole("heading", { name: "变体庚", exact: true })).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "变体辛", exact: true })).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "SMA", exact: true })).toHaveCount(0);
    await expect(pagination.getByRole("button", { name: "下一页" })).toBeDisabled();
    await pagination.getByRole("button", { name: "上一页" }).click();
    const technical = dialog.locator("details").first();
    await technical.locator("summary").click();
    await expect(technical).toContainText("onlyalpha.indicator.sma@1");
    const search = dialog.getByRole("searchbox", { name: "搜索指标或因子" });
    await search.fill("missing");
    await expect(dialog.getByText("没有匹配的指标。")).toBeVisible();
    await search.fill("变体辛");
    await expect(pagination).toContainText("共 1 项 · 第 1 / 1 页");
    await dialog.getByRole("button", { name: "选择 变体辛 · 配置草稿" }).click();
    const handoff = page.getByTestId("calculation-handoff");
    await expect(handoff).toHaveAttribute("data-registration-source", "CHART_STUDY_TRANSIENT");
    await expect(handoff).toHaveAttribute("data-type-id", "onlyalpha.indicator.sma8");
    await expect(handoff).toContainText("仅配置草稿，尚未计算");
    expect(researchRequests).toEqual([]);
});

test("the transient catalog stays inside a 390px viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const variants = await catalogVariants();
    await controlledRealtime(page, { capabilities: () => variants });
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    const dialog = await openCatalog(page);
    const box = await dialog.boundingBox();
    expect(box?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect((box?.x ?? 391) + (box?.width ?? 391)).toBeLessThanOrEqual(390);
    const pagination = dialog.getByRole("navigation", { name: "目录分页" });
    await expect(pagination).toContainText("共 8 项 · 第 1 / 2 页");
    await pagination.getByRole("button", { name: "下一页" }).click();
    await expect(pagination).toContainText("共 8 项 · 第 2 / 2 页");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        390
    );
});

test("a failed Capability read fails closed with the catalog alert", async ({ page }) => {
    await controlledRealtime(page);
    // Registered later, this route wins over the shared catch-all: the catalog
    // transport now behaves like an unavailable official service.
    await page.route("**/api/v2/chart/studies/capabilities", (route) => void route.abort());
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    const dialog = await openCatalog(page);
    // ChartStudyWebError failures map to the picker's INVALID presentation; the
    // Research TRANSPORT wording belongs to the retired exact-catalog path.
    await expect(dialog.getByRole("alert")).toHaveText("目录身份或契约验证失败；不可选择。");
    await expect(dialog.getByRole("button", { name: /配置草稿/ })).toHaveCount(0);
    await expect(page.getByTestId("calculation-handoff")).toHaveCount(0);
    await dialog.getByRole("button", { name: "关闭目录" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("market-data-status")).toContainText("● 实时");
});

test("a Capability Projection switch at selection hands over nothing", async ({ page }) => {
    const variants = await catalogVariants();
    const market = await controlledRealtime(page, {
        capabilities: () => variants,
        staleCapabilityOnConfirm: true
    });
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    const dialog = await openCatalog(page);
    await dialog.getByRole("searchbox", { name: "搜索指标或因子" }).fill("变体辛");
    market.armStaleVerify();
    await dialog.getByRole("button", { name: "选择 变体辛 · 配置草稿" }).click();
    // The re-read reports the same Identity under a switched projection; the
    // selection must not produce a draft under any label.
    await expect(dialog.getByRole("alert")).toHaveText(
        "目录或 Runtime Generation 已切换；旧目录与选择已失效，请刷新目录。"
    );
    await expect(page.getByTestId("calculation-handoff")).toHaveCount(0);
    expect(market.evaluateReads).toHaveLength(0);
});

test("the factor library tab swaps the transient list for the metadata board", async ({
    page
}) => {
    const variants = await catalogVariants();
    await controlledRealtime(page, { capabilities: () => variants });
    await page.goto("/");
    await expect(status(page)).toContainText("● 实时");
    const dialog = await openCatalog(page);
    await dialog.getByRole("tab", { name: "因子库" }).click();
    await expect(dialog.getByRole("heading", { name: "Factor / Indicator Library" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: /配置草稿/ })).toHaveCount(0);
    await dialog.getByRole("tab", { name: "指标" }).click();
    await expect(dialog.getByRole("button", { name: "选择 SMA · 配置草稿" })).toBeVisible();
});
