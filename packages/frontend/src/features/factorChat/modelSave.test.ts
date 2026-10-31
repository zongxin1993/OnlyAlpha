/* eslint-disable @typescript-eslint/require-await */
import { afterEach, expect, it, vi } from "vitest";
import { request } from "./api";
import { finishModelSave, migrateModelSave } from "./modelSave";
vi.mock(import("./api"), async (original) => ({ ...(await original()), request: vi.fn() }));
const key = "onlyalpha.agent.model-save";
const legacy = "onlyalpha.agent.chat.pending";
const access = {
    schema_version: 1 as const,
    token: "token",
    expires_at: 4000000000,
    subject: "owner",
    agent_url: "https://agent.example",
    binding: "a".repeat(64)
};
const pending = {
    kind: "model",
    resource: "00000000-0000-4000-8000-000000000001",
    command: "00000000-0000-4000-8000-000000000002",
    binding: access.binding
};
afterEach(() => {
    sessionStorage.clear();
    vi.resetAllMocks();
});
it.each([
    { status: "UNKNOWN", outcome: null },
    { status: "ABANDONED", outcome: null }
])("does not erase an unproven termination %j", async (result) => {
    sessionStorage.setItem(key, JSON.stringify(pending));
    vi.mocked(request).mockResolvedValue(result);
    await expect(finishModelSave(access)).rejects.toThrow();
    expect(sessionStorage.getItem(key)).toBe(JSON.stringify(pending));
});
it("never clears a newer save while awaiting finalization", async () => {
    const newer = JSON.stringify({ ...pending, command: "00000000-0000-4000-8000-000000000003" });
    sessionStorage.setItem(key, JSON.stringify(pending));
    vi.mocked(request).mockImplementation(async () => {
        sessionStorage.setItem(key, newer);
        return { status: "ABANDONED", outcome: { abandoned: true } };
    });
    await expect(finishModelSave(access)).rejects.toThrow();
    expect(sessionStorage.getItem(key)).toBe(newer);
});
it("does not overwrite a different model save or any unrelated chat record during migration", () => {
    sessionStorage.setItem(
        key,
        JSON.stringify({ ...pending, command: "00000000-0000-4000-8000-000000000003" })
    );
    const raw = JSON.stringify(pending);
    sessionStorage.setItem(legacy, raw);
    expect(() => {
        migrateModelSave();
    }).toThrow();
    expect(sessionStorage.getItem(legacy)).toBe(raw);
    sessionStorage.setItem(legacy, JSON.stringify({ ...pending, kind: "message" }));
    migrateModelSave();
    expect(sessionStorage.getItem(legacy)).toContain('"kind":"message"');
});
