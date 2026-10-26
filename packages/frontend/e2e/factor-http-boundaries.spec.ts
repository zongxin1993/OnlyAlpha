import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { nativeErrorSchema } from "../src/api/errors.generated";

type RevisionPin = Record<string, unknown> & {
    factor_id: string;
    revision_fingerprint: string;
    source_sha256: string;
};
function isRevisionPin(value: unknown): value is RevisionPin {
    return (
        typeof value === "object" &&
        value !== null &&
        !Array.isArray(value) &&
        "factor_id" in value &&
        typeof value.factor_id === "string" &&
        "revision_fingerprint" in value &&
        typeof value.revision_fingerprint === "string" &&
        "source_sha256" in value &&
        typeof value.source_sha256 === "string"
    );
}

// Technical HTTP negatives against the real native Host. These requests are not
// business UI acceptance; the ordinary Factor flows remain in factors.spec.ts.
test("exact Factor reads reject missing content, mismatches and missing revisions without substituting head", async ({
    page
}) => {
    const operation = process.env.ONLYALPHA_DEV_VERIFICATION_OPERATION_ID;
    if (!operation) throw new Error("FROZEN_CANONICAL_OPERATION_REQUIRED");
    const pins: unknown = JSON.parse(
        readFileSync(
            `/workspace/test-results/native-web-e2e/${operation}/private-metadata-precondition.json`,
            "utf8"
        )
    );
    if (
        typeof pins !== "object" ||
        pins === null ||
        !("first" in pins) ||
        !("current" in pins) ||
        !isRevisionPin(pins.first) ||
        !isRevisionPin(pins.current)
    )
        throw new Error("EXACT_FACTOR_PRECONDITION_INVALID");
    const first = pins.first;
    const current = pins.current;
    expect(first.revision_fingerprint).not.toBe(current.revision_fingerprint);
    expect(first.source_sha256).not.toBe(current.source_sha256);
    await page.goto("/");
    await page.getByRole("button", { name: "因子", exact: true }).click();
    await expect(
        page
            .getByRole("dialog", { name: "指标 / 因子目录" })
            .getByRole("button", { name: /Retained native metadata/ })
    ).toBeVisible();
    const path = (revision: string) =>
        `/api/v2/private-assets/factors/${first.factor_id}/revisions/${revision}`;
    const registryBefore = await page.request.get("/api/v2/private-assets");
    expect(registryBefore.status()).toBe(200);
    const registry: unknown = await registryBefore.json();
    const missingContent = await page.request.get(path("0".repeat(64)));
    expect(missingContent.status()).toBe(400);
    const exact = await page.request.get(
        `${path(first.revision_fingerprint)}?content_fingerprint=${first.source_sha256}`
    );
    expect(exact.status()).toBe(200);
    expect(await exact.json()).toMatchObject(first);
    const mismatch = await page.request.get(
        `${path(first.revision_fingerprint)}?content_fingerprint=${current.source_sha256}`
    );
    expect(mismatch.status()).toBe(409);
    expect(nativeErrorSchema.parse(await mismatch.json()).error.code).toBe(
        "PRIVATE_ASSET_EXACT_READ_MISMATCH"
    );
    const missing = await page.request.get(
        `${path("0".repeat(64))}?content_fingerprint=${first.source_sha256}`
    );
    expect(missing.status()).toBe(404);
    expect(nativeErrorSchema.parse(await missing.json()).error.code).toBe(
        "PRIVATE_ASSET_EXACT_REVISION_UNAVAILABLE"
    );
    for (const pin of [first, current]) {
        const again = await page.request.get(
            `${path(pin.revision_fingerprint)}?content_fingerprint=${pin.source_sha256}`
        );
        expect(again.status()).toBe(200);
        expect(await again.json()).toMatchObject(pin);
    }
    const registryAfter = await page.request.get("/api/v2/private-assets");
    expect(registryAfter.status()).toBe(200);
    expect(await registryAfter.json()).toEqual(registry);
});
