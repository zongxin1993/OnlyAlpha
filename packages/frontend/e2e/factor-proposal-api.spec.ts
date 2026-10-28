// A3 API/security integration against the Shipping Host. This is not A4 Web acceptance.
import { spawnSync } from "node:child_process";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { z } from "zod";

const contextSchema = z.object({
    schema_version: z.literal(1),
    owner: z.string(),
    service_subject: z.string(),
    factor_id: z.string(),
    draft_fingerprint: z.string().nullable(),
    display_fingerprint: z.string().nullable(),
    proposal_fingerprint: z.string().nullable()
});
const receiptSchema = z.object({
    schema_version: z.literal(1),
    command_id: z.string(),
    operation_fingerprint: z.string(),
    effect: z.looseObject({ proposal_fingerprint: z.string() })
});
const viewSchema = z.object({
    fingerprint: z.string(),
    is_current: z.boolean(),
    snapshot: z.object({
        owner: z.string(),
        preview: z.object({ formula: z.string(), execution_admitted: z.literal(false) })
    }),
    confirmation: receiptSchema.nullable()
});

// Exercise the actual independently installed Agent HTTP adapter against the Shipping Host.
// Credentials travel on stdin and are never emitted into the browser or test output.
function agentRequest(
    token: string,
    method: string,
    path: string,
    body?: unknown,
    command?: string
): unknown {
    const result = spawnSync(
        "python",
        [
            "-c",
            `
import json,sys
from onlyalpha_agent.backend import Connection, request
v=json.load(sys.stdin)
print(json.dumps(request(Connection("http://127.0.0.1:5173",v["token"]),v["method"],v["path"],v.get("body"),v.get("command"))))
`
        ],
        {
            input: JSON.stringify({ token, method, path, body, command }),
            encoding: "utf8",
            maxBuffer: 131072
        }
    );
    expect(result.status, result.stderr).toBe(0);
    return JSON.parse(result.stdout) as unknown;
}

test("A3 technical API separates service staging from Human acceptance", async ({
    page,
    playwright
}) => {
    await page.goto("/");
    const grant = randomUUID();
    const token = `oa-proposal-v1.${grant}.${randomBytes(32).toString("hex")}`;
    const humanHeaders = { Origin: "http://127.0.0.1:5173", "Idempotency-Key": randomUUID() };
    const created = await page.request.post("/api/v2/factor-proposal-grants", {
        headers: humanHeaders,
        data: {
            schema_version: 1,
            grant_id: grant,
            service_subject: "discovery",
            credential_sha256: createHash("sha256").update(token).digest("hex"),
            proposal_limit: 2,
            expires_at: "2099-01-01T00:00:00Z"
        }
    });
    expect(created.status(), await created.text()).toBe(200);
    const service = await playwright.request.newContext({
        baseURL: "http://127.0.0.1:5173",
        extraHTTPHeaders: { Authorization: `Bearer ${token}` }
    });
    try {
        const sid = randomUUID();
        const context = contextSchema.parse(
            agentRequest(token, "GET", `/api/v2/factor-proposal-context/${sid}`)
        );
        expect(context.owner).toBe("local-developer");
        const command = randomUUID();
        const body = {
            schema_version: 1,
            origin: {
                session_id: sid,
                event_fingerprint: "b".repeat(64),
                result_fingerprint: "c".repeat(64),
                workflow_fingerprint: "d".repeat(64),
                model_revision: "e".repeat(64)
            },
            candidate: {
                name: "量价观察",
                purpose: "A3 controlled input",
                hypothesis: "价格变化可能持续",
                expression: {
                    op: "sub",
                    left: { input: "close" },
                    right: { input: "close", lag: 20 }
                }
            },
            expected_draft_fingerprint: context.draft_fingerprint,
            expected_display_fingerprint: context.display_fingerprint,
            expected_proposal_fingerprint: context.proposal_fingerprint
        };
        const receipt = receiptSchema.parse(
            agentRequest(token, "POST", "/api/v2/factor-proposals", body, command)
        );
        const fp = receipt.effect.proposal_fingerprint;
        const observed = await service.get(`/api/v2/factor-proposals/commands/${command}`);
        expect(receiptSchema.parse(await observed.json())).toEqual(receipt);
        const replay = await service.post("/api/v2/factor-proposals", {
            headers: { "Idempotency-Key": command },
            data: body
        });
        expect(receiptSchema.parse(await replay.json())).toEqual(receipt);
        const denied = await service.post(`/api/v2/factor-proposals/${fp}/confirmation`, {
            headers: { "Idempotency-Key": randomUUID() },
            data: { schema_version: 1, proposal_fingerprint: fp }
        });
        expect([401, 403]).toContain(denied.status());
        const pending = viewSchema.parse(
            await (await page.request.get(`/api/v2/factor-proposals/${fp}`)).json()
        );
        expect(pending.confirmation).toBeNull();
        expect(pending.snapshot.preview.formula).toBe("(close − lag(close, 20))");
        const confirmation = randomUUID();
        const accepted = await page.request.post(`/api/v2/factor-proposals/${fp}/confirmation`, {
            headers: { ...humanHeaders, "Idempotency-Key": confirmation },
            data: { schema_version: 1, proposal_fingerprint: fp }
        });
        expect(accepted.status(), await accepted.text()).toBe(200);
        const result = receiptSchema.parse(await accepted.json());
        const recovered = await service.get(`/api/v2/factor-proposals/${fp}`);
        expect(viewSchema.parse(await recovered.json()).confirmation).toEqual(result);
        const revoked = await page.request.post("/api/v2/factor-proposal-grants/revocations", {
            headers: { ...humanHeaders, "Idempotency-Key": randomUUID() },
            data: { schema_version: 1, grant_id: grant }
        });
        expect(revoked.status(), await revoked.text()).toBe(200);
        expect((await service.get(`/api/v2/factor-proposals/${fp}`)).status()).toBe(401);
        expect(
            viewSchema.parse(
                await (await page.request.get(`/api/v2/factor-proposals/${fp}`)).json()
            ).confirmation
        ).toEqual(result);
    } finally {
        await service.dispose();
    }
});
