import { Buffer } from "node:buffer";
import { expect, test } from "@playwright/test";
import { nativeErrorSchema } from "../src/api/errors.generated";
import {
    integrationTypeSchema,
    schemas as integrationSchemas
} from "../src/api/integrations/model";

// Real HTTP framing and routing regressions, without business setup/provider I/O.
const missing = "00000000-0000-4000-8000-000000000001";
const errors: readonly (readonly [string, number, string])[] = [
    ["/api/v2/integration-types/0", 404, "INTEGRATION_TYPE_NOT_FOUND"],
    ...["", "/draft", "/revisions", "/revisions/0"].map(
        (suffix) => [`/api/v2/integrations/0${suffix}`, 400, "INTEGRATION_REQUEST_INVALID"] as const
    ),
    [`/api/v2/integrations/${missing}`, 404, "INTEGRATION_NOT_FOUND"],
    [`/api/v2/integrations/${missing}/draft`, 404, "INTEGRATION_DRAFT_NOT_FOUND"],
    [
        `/api/v2/integrations/${missing}/revisions/${"0".repeat(64)}`,
        404,
        "INTEGRATION_REVISION_NOT_FOUND"
    ]
];
for (const [path, status, code] of errors) {
    test(`complete metadata HTTP error: ${path}`, async ({ page }) => {
        await page.goto("/");
        const response = await page.request.get(path);
        expect(response.status()).toBe(status);
        const text = await response.text();
        const headers = response.headers();
        if (Object.hasOwn(headers, "content-length")) {
            expect(Number(headers["content-length"])).toBe(Buffer.byteLength(text));
        }
        expect(nativeErrorSchema.parse(JSON.parse(text)).error).toMatchObject({
            phase: "QUERY",
            code
        });
    });
}
test("verified absent Integration has an empty revision collection", async ({ page }) => {
    await page.goto("/");
    const response = await page.request.get(`/api/v2/integrations/${missing}/revisions`);
    expect(response.status()).toBe(200);
    expect(integrationSchemas.revisions.parse(await response.json())).toEqual({ items: [] });
});
test("one-parameter metadata dispatch retains the registered descriptor", async ({ page }) => {
    await page.goto("/");
    const response = await page.request.get("/api/v2/integration-types/binance.spot.market_data");
    expect(response.status()).toBe(200);
    expect(integrationTypeSchema.parse(await response.json()).type_id).toBe(
        "binance.spot.market_data"
    );
});
const source_reference = {
    integration_id: "0",
    integration_revision_fingerprint: "0".repeat(64),
    expected_type_id: "0"
};
const bar_semantic = {
    schema_version: 3,
    price_type: "ASK",
    adjustment_policy: "RAW",
    formation: {
        schema_version: 1,
        kind: "FIXED_DURATION",
        alignment: "UTC",
        window_minutes: 1,
        stride_minutes: 1
    }
};
for (const [path, data] of [
    [
        "/api/v2/market-data/acquisitions",
        {
            source_reference,
            instrument_id: "0",
            start_ns: "0",
            end_ns: "0",
            bar_semantic: null,
            provenance: null
        }
    ],
    [
        "/api/v2/chart/studies/evaluate",
        {
            schema_version: 2,
            source_reference,
            instrument_id: "0",
            bar_semantic,
            window: { anchor_kind: "BEFORE_TIME", before_ns: "1", target_bar_count: 1 },
            calculation: {
                kind: "INDICATOR",
                type_id: "0",
                semantic_version: "0",
                typed_parameters: {},
                output_members: ["value"],
                expected_descriptor_fingerprint: "0".repeat(64),
                expected_implementation_fingerprint: "0".repeat(64),
                expected_capability_projection_fingerprint: "0".repeat(64)
            },
            expected_history_projection_fingerprint: "0".repeat(64),
            include_unclosed_preview: false,
            preview_stream_id: null
        }
    ]
] as const) {
    test(`complete verified Source list proves absent owner: ${path}`, async ({ page }) => {
        await page.goto("/");
        const response = await page.request.post(path, {
            headers: { Origin: "http://127.0.0.1:5173" },
            data
        });
        expect(response.status()).toBe(404);
        expect(nativeErrorSchema.parse(await response.json()).error).toMatchObject({
            phase: "COMMAND",
            code: "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED"
        });
    });
}
