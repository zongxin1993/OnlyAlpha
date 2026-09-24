import { expect, test, type Page, type Route } from "@playwright/test";

const id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const untestableId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const revision = "a".repeat(64);
const commandId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

const integrationType = {
    schema_version: 1,
    type_id: "test.market_data",
    category: "DATA_SOURCE",
    display_name: "Local Market Data",
    description: "Deterministic browser fixture",
    provider_id: "test",
    implementation_id: "test",
    implementation_version: "1",
    public_api_version: "1.1",
    capabilities: ["HISTORICAL_BARS", "LIVE_TICKS", "INSTRUMENTS"],
    fingerprint: "b".repeat(64),
    configuration_contract: {
        schema_version: 1,
        fingerprint: "c".repeat(64),
        fields: [
            {
                field_id: "timeout_seconds",
                display_name: "Timeout seconds",
                description: "Bounded request timeout",
                value_kind: "DURATION",
                required: false,
                secret: false,
                advanced: false,
                default: 5,
                enum_values: [],
                minimum: 1,
                maximum: 60,
                exclusive_minimum: false
            },
            {
                field_id: "token",
                display_name: "Token",
                description: "Credential",
                value_kind: "STRING",
                required: false,
                secret: true,
                advanced: true,
                default: null,
                enum_values: [],
                minimum: null,
                maximum: null,
                exclusive_minimum: false
            }
        ]
    },
    probe_contract: {
        probe_version: 1,
        probe_mode: "DEFAULT_INSTRUMENT",
        default_probe_instrument: "TEST",
        user_selectable_probe_instrument: true,
        probe_checks: ["CONNECTIVITY", "AUTHENTICATION", "REALTIME_DATA"],
        fingerprint: "d".repeat(64)
    }
};

const untestableType = {
    ...integrationType,
    type_id: "test.untestable",
    display_name: "Untestable Market Data",
    provider_id: "untestable",
    capabilities: ["HISTORICAL_BARS"],
    probe_contract: null
};

const integration = {
    schema_version: 1,
    integration_id: id,
    type_id: integrationType.type_id,
    display_name: "Fixture Market Data",
    lifecycle_state: "ACTIVE",
    current_revision_fingerprint: revision,
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z"
};

const untestableIntegration = {
    ...integration,
    integration_id: untestableId,
    type_id: untestableType.type_id,
    display_name: "Untestable Market Data",
    current_revision_fingerprint: null
};

const probeAttempt = {
    schema_version: 1,
    probe_attempt_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    integration_id: id,
    revision_fingerprint: revision,
    type_id: integrationType.type_id,
    type_descriptor_fingerprint: integrationType.fingerprint,
    probe_contract_fingerprint: "d".repeat(64),
    probe_configuration_fingerprint: "e".repeat(64),
    runtime_configuration_fingerprint: "f".repeat(64),
    started_at: "2026-09-21T00:00:00Z",
    completed_at: "2026-09-21T00:00:01.140Z",
    overall_status: "DEGRADED",
    probe_instrument: "TEST",
    checks: [
        {
            check: "CONNECTIVITY",
            status: "PASS",
            latency_ms: 12,
            failure_kind: null,
            error_code: null,
            detail: "",
            observations: []
        },
        {
            check: "AUTHENTICATION",
            status: "SKIPPED",
            latency_ms: 0,
            failure_kind: null,
            error_code: null,
            detail: "",
            observations: []
        },
        {
            check: "REALTIME_DATA",
            status: "FAIL",
            latency_ms: 5000,
            failure_kind: "OFFLINE",
            error_code: "REALTIME_STREAM_UNAVAILABLE",
            detail: "WebSocket connection timeout",
            observations: []
        }
    ]
};

const json = (route: Route, body: unknown) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });

async function mockDataSources(page: Page) {
    const state = {
        lifecycle: "ACTIVE",
        secretGeneration: 2,
        probed: false,
        lifecycleCalls: [] as string[],
        writeCalls: [] as string[]
    };
    await page.route("**/api/v2/**", (route) => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        const method = request.method();
        if (method !== "GET") state.writeCalls.push(`${method} ${path}`);
        if (path === "/api/v2/integration-types")
            return json(route, { items: [integrationType, untestableType] });
        if (path === "/api/v2/integrations" && method === "GET")
            return json(route, {
                items: [integration, untestableIntegration].map((item) => ({
                    ...item,
                    lifecycle_state: state.lifecycle,
                    category: "DATA_SOURCE",
                    draft_version: 4,
                    pinned_type_descriptor_fingerprint: integrationType.fingerprint
                }))
            });
        if (path === "/api/v2/integrations" && method === "POST")
            return json(route, {
                schema_version: 1,
                command_id: commandId,
                integration_id: id,
                replayed: false,
                outcome_kind: "INTEGRATION",
                outcome_id: id
            });
        if (path === `/api/v2/integrations/${untestableId}`)
            return json(route, { ...untestableIntegration, lifecycle_state: state.lifecycle });
        if (path === `/api/v2/integrations/${untestableId}/draft`)
            return json(route, {
                schema_version: 1,
                integration_id: untestableId,
                base_revision_fingerprint: null,
                pinned_type_descriptor_fingerprint: untestableType.fingerprint,
                type_descriptor: untestableType,
                public_configuration: {},
                probe_configuration: null,
                draft_version: 1,
                draft_fingerprint: "2".repeat(64),
                secret_statuses: [],
                created_at: "2026-09-21T00:00:00Z",
                updated_at: "2026-09-21T00:00:00Z"
            });
        if (path.startsWith(`/api/v2/integrations/${untestableId}/`))
            return json(route, { items: [] });
        if (path === `/api/v2/integrations/${id}`)
            return json(route, { ...integration, lifecycle_state: state.lifecycle });
        if (path === `/api/v2/integrations/${id}/draft` && method === "GET")
            return json(route, {
                schema_version: 1,
                integration_id: id,
                base_revision_fingerprint: revision,
                pinned_type_descriptor_fingerprint: integrationType.fingerprint,
                type_descriptor: integrationType,
                public_configuration: { timeout_seconds: 5 },
                probe_configuration: { instrument: "TEST" },
                draft_version: 4,
                draft_fingerprint: "1".repeat(64),
                secret_statuses: [
                    { field_id: "token", configured: true, generation: state.secretGeneration }
                ],
                created_at: "2026-09-21T00:00:00Z",
                updated_at: "2026-09-21T00:00:00Z"
            });
        if (path === `/api/v2/integrations/${id}/draft` && method === "PUT")
            return json(route, {
                schema_version: 1,
                command_id: commandId,
                integration_id: id,
                replayed: false,
                outcome_kind: "DRAFT",
                outcome_id: "5"
            });
        if (path.endsWith(`/integrations/${id}/revisions`) && method === "POST")
            return json(route, {
                schema_version: 1,
                command_id: commandId,
                integration_id: id,
                replayed: false,
                outcome_kind: "REVISION",
                outcome_id: revision
            });
        if (path.endsWith(`/integrations/${id}/revisions`)) return json(route, { items: [] });
        if (path === `/api/v2/integrations/${id}/lifecycle` && method === "PUT") {
            const body = JSON.parse(request.postData() ?? "{}") as { lifecycle_state?: string };
            state.lifecycle = body.lifecycle_state ?? state.lifecycle;
            state.lifecycleCalls.push(state.lifecycle);
            return json(route, {
                schema_version: 1,
                command_id: commandId,
                integration_id: id,
                replayed: false,
                outcome_kind: "INTEGRATION",
                outcome_id: id
            });
        }
        if (path === `/api/v2/integrations/${id}/operational-status`)
            return json(route, {
                schema_version: 1,
                integration_id: id,
                revision_fingerprint: revision,
                status: state.probed ? "DEGRADED" : "UNKNOWN",
                probe_attempt_id: state.probed ? probeAttempt.probe_attempt_id : null,
                checked_at: state.probed ? "2026-09-21T00:00:01Z" : null,
                probe_supported: true
            });
        if (path.endsWith("/probe") && method === "POST") {
            state.probed = true;
            return json(route, probeAttempt);
        }
        if (path.endsWith("/probe-attempts"))
            return json(route, { items: state.probed ? [probeAttempt] : [] });
        if (path.includes("/draft/secrets/")) {
            state.secretGeneration += 1;
            return json(route, {
                schema_version: 1,
                command_id: commandId,
                integration_id: id,
                replayed: false,
                outcome_kind: "DRAFT",
                outcome_id: "6"
            });
        }
        return json(route, { items: [] });
    });
    return state;
}

for (const width of [1440, 390]) {
    test(`data source entry, popover and manager at ${String(width)}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await mockDataSources(page);
        await page.goto("/");
        const trigger = page.getByRole("button", { name: /数据源/ });
        await expect(trigger).toBeVisible();
        await trigger.click();
        const popover = page.getByRole("dialog", { name: "数据源状态" });
        await expect(popover.getByText("Fixture Market Data")).toBeVisible();
        await expect(popover.getByText("Untestable Market Data")).toBeVisible();
        await expect(popover.getByText(/尚未有 canonical 来源绑定/)).toBeVisible();
        await popover.getByRole("button", { name: "管理数据源…" }).click();
        const modal = page.getByRole("dialog", { name: "管理数据源" });
        await expect(modal.getByRole("tab", { name: /已配置/ })).toBeVisible();
        await modal.getByRole("tab", { name: /数据源绑定/ }).click();
        await expect(modal.getByText(/尚无来源绑定资源/)).toBeVisible();
        await modal.getByRole("tab", { name: /添加数据源/ }).click();
        await expect(modal.getByRole("button", { name: /Local Market Data/ })).toBeVisible();
        await expect(modal.getByRole("button", { name: /Untestable Market Data/ })).toBeVisible();
        await expect
            .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
            .toBe(true);
        await page.keyboard.press("Escape");
        await expect(modal).toBeHidden();
        await expect(page.getByRole("region", { name: "主图" })).toBeVisible();
    });
}

test("configure, publish, probe and change lifecycle through the formal API", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const state = await mockDataSources(page);
    await page.goto("/data/sources");
    const card = page.getByRole("article", { name: "Fixture Market Data" });
    await card.getByRole("button", { name: "配置" }).click();
    await expect(page.getByRole("heading", { name: "Fixture Market Data" })).toBeVisible();
    await page.getByLabel("Timeout seconds").fill("9");
    await page.getByRole("button", { name: "保存草稿" }).click();
    await page.getByRole("button", { name: "发布 Revision" }).click();
    await page.getByRole("button", { name: "测试连接" }).click();
    const checks = page.getByRole("list", { name: "连接测试检查项" });
    const row = (name: string) => checks.getByRole("listitem").filter({ hasText: name });
    await expect(row("连接")).toContainText("通过");
    await expect(row("认证")).toContainText("未验证");
    await expect(row("实时数据")).toContainText("失败");
    await expect(row("实时数据")).toContainText("WebSocket connection timeout");
    await expect(row("参考数据")).toContainText("不适用");
    await expect(checks.getByRole("listitem")).toHaveCount(5);
    await page.getByLabel("更换 token").fill("ephemeral-value");
    await page.getByRole("button", { name: "更换凭据" }).click();
    await page.getByRole("button", { name: "禁用" }).click();
    await expect.poll(() => state.secretGeneration).toBe(3);
    await expect
        .poll(() => state.lifecycleCalls[state.lifecycleCalls.length - 1] ?? "")
        .toBe("DISABLED");
    expect(
        state.writeCalls.some(
            (call) => call.startsWith("PUT /api/v2/integrations/") && call.includes("/binding")
        )
    ).toBe(false);
});

test("an undeclared probe contract is explained instead of disabled", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockDataSources(page);
    await page.goto("/data/sources");
    const card = page.getByRole("article", { name: "Untestable Market Data" });
    await card.getByRole("button", { name: "配置" }).click();
    await expect(page.getByText("该类型未提供连接测试")).toBeVisible();
    await expect(page.getByTestId("probe-action")).toHaveCount(0);
});

test("binding tab exposes the missing capability without a fake save", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const state = await mockDataSources(page);
    await page.goto("/data/sources");
    await page.getByRole("tab", { name: /数据源绑定/ }).click();
    await expect(page.getByText(/尚无来源绑定资源/)).toBeVisible();
    await expect(page.getByRole("button", { name: /保存绑定/ })).toHaveCount(0);
    expect(state.writeCalls).toEqual([]);
    expect(await page.evaluate(() => window.localStorage.length)).toBe(0);
});
