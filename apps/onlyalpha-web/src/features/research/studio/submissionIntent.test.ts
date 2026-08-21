import { ResearchRunSubmissionIntent, shouldAdmitResolution } from "./submissionIntent";
import { calculationDraftFromCatalog } from "./researchDraft";

const S1 = "a".repeat(64);
const S2 = "b".repeat(64);

it("reuses one idempotency key for the same pending authoritative Specification", () => {
    const values = ["00000000-0000-4000-8000-000000000101"];
    const intent = new ResearchRunSubmissionIntent(() => values.shift() ?? "");
    const first = intent.keyFor(S1);
    expect(intent.keyFor(S1)).toBe(first);
});

it("rotates after authoritative success so the same Specification can Run Again", () => {
    const values = ["00000000-0000-4000-8000-000000000101", "00000000-0000-4000-8000-000000000102"];
    const intent = new ResearchRunSubmissionIntent(() => values.shift() ?? "");
    const first = intent.keyFor(S1);
    intent.confirm(S1);
    expect(intent.keyFor(S1)).not.toBe(first);
});

it("starts a new intent when the authoritative Specification changes", () => {
    const values = ["00000000-0000-4000-8000-000000000101", "00000000-0000-4000-8000-000000000102"];
    const intent = new ResearchRunSubmissionIntent(() => values.shift() ?? "");
    const first = intent.keyFor(S1);
    expect(intent.keyFor(S2)).not.toBe(first);
});

it("does not clear a newer pending intent when an older response is confirmed", () => {
    const values = ["00000000-0000-4000-8000-000000000101", "00000000-0000-4000-8000-000000000102"];
    const intent = new ResearchRunSubmissionIntent(() => values.shift() ?? "");
    intent.keyFor(S1);
    const second = intent.keyFor(S2);
    intent.confirm(S1);
    expect(intent.keyFor(S2)).toBe(second);
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
