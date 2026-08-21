import { ResearchRunSubmissionIntent, shouldAdmitResolution } from "./submissionIntent";
import { calculationDraftFromCatalog } from "./researchDraft";

it("reuses one idempotency key for uncertain retry and rotates after authoritative success", () => {
    const values = ["00000000-0000-4000-8000-000000000101", "00000000-0000-4000-8000-000000000102"];
    const intent = new ResearchRunSubmissionIntent(() => values.shift() ?? "");
    const first = intent.current();
    expect(intent.current()).toBe(first);
    intent.complete();
    expect(intent.current()).not.toBe(first);
});

it("admits only the latest non-aborted authoritative Resolution response", () => {
    expect(shouldAdmitResolution(3, 3, false)).toBe(true);
    expect(shouldAdmitResolution(2, 3, false)).toBe(false);
    expect(shouldAdmitResolution(3, 3, true)).toBe(false);
});

it("fails closed when a Catalog exposes an unsupported parameter type", () => {
    expect(() =>
        calculationDraftFromCatalog(
            {
                kind: "INDICATOR",
                type_reference: {
                    kind: "INDICATOR",
                    type_id: "test.invalid",
                    semantic_version: "1"
                },
                parameters: [
                    {
                        name: "value",
                        type: "UNKNOWN",
                        required: true,
                        default: { type: "NULL", value: null },
                        minimum: null,
                        maximum: null,
                        enum_values: [],
                        uppercase: false
                    }
                ],
                inputs: [],
                outputs: [],
                parameter_sweep_allowed: false
            },
            1,
            "invalid"
        )
    ).toThrow("Unsupported Calculation parameter type");
});
