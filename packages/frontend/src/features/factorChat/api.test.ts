import { describe, it, expect } from "vitest";
import { chatSchema } from "./api";
describe("conversation admission", () => {
    it("rejects fabricated numeric reports, executable previews and invalid identities", () => {
        expect(chatSchema.safeParse({ conversation_id: "latest", confirmed: true }).success).toBe(
            false
        );
        expect(
            chatSchema.safeParse({ schema_version: 1, research_result: { ic: 0.9 } }).success
        ).toBe(false);
    });
});
