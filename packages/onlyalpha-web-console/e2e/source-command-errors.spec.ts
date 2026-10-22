import { expect, test } from "@playwright/test";
import { nativeErrorSchema } from "../src/api/errors.generated";

// Technical error recovery against the real native Host/store. This does not
// replace Source creation/configuration acceptance through the Shipping UI.
test("rejected lifecycle and publication leave authoritative Source reads usable", async ({
    page
}) => {
    await page.goto("/");
    const before = await page.request.get("/api/v2/market-data/sources");
    expect(before.status()).toBe(200);
    const original: unknown = await before.json();
    const integration = "00000000-0000-4000-8000-000000000001";
    const results: {
        commandStatus: number;
        code: string;
        phase: string;
        sourceStatus: number;
        sources: unknown;
    }[] = [];
    for (const operation of ["lifecycle", "revisions"]) {
        const response = await page.request.fetch(
            `/api/v2/integrations/${integration}/${operation}`,
            {
                method: operation === "lifecycle" ? "PUT" : "POST",
                headers: {
                    Origin: "http://127.0.0.1:5173",
                    "Idempotency-Key":
                        operation === "lifecycle"
                            ? "00000000-0000-4000-8000-000000000002"
                            : "00000000-0000-4000-8000-000000000003"
                },
                data:
                    operation === "lifecycle"
                        ? {
                              schema_version: 1,
                              expected_lifecycle_state: "ACTIVE",
                              lifecycle_state: "DISABLED"
                          }
                        : { schema_version: 1, expected_draft_version: 1 }
            }
        );
        const sources = await page.request.get("/api/v2/market-data/sources");
        const error = nativeErrorSchema.parse(await response.json()).error;
        results.push({
            commandStatus: response.status(),
            code: error.code,
            phase: error.phase,
            sourceStatus: sources.status(),
            sources: await sources.json()
        });
    }
    expect(results.map((result) => result.commandStatus)).toEqual([404, 404]);
    expect(results.map((result) => result.code)).toEqual([
        "INTEGRATION_NOT_FOUND",
        "INTEGRATION_NOT_FOUND"
    ]);
    expect(results.map((result) => result.phase)).toEqual(["COMMAND", "COMMAND"]);
    expect(results.map((result) => result.sourceStatus)).toEqual([200, 200]);
    for (const result of results) expect(result.sources).toEqual(original);
});
