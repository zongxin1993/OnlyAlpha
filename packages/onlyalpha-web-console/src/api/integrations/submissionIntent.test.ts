import { createUuidV4, MutationSubmissionIntent } from "./submissionIntent";

const UUIDS = ["00000000-0000-4000-8000-000000000101", "00000000-0000-4000-8000-000000000102"];

it.each(["draft", "secret", "publish"])(
    "retains one command UUID after an unknown %s transport outcome",
    (operation) => {
        const values = [...UUIDS];
        const intent = new MutationSubmissionIntent(() => values.shift() ?? "");
        const first = intent.commandFor(`${operation}:payload`);
        expect(intent.commandFor(`${operation}:payload`)).toBe(first);
    }
);

it("rotates only after a definitive response", () => {
    const values = [...UUIDS];
    const intent = new MutationSubmissionIntent(() => values.shift() ?? "");
    const first = intent.commandFor("draft:payload");
    intent.definitive("draft:payload");
    expect(intent.commandFor("draft:payload")).not.toBe(first);
});

it("creates a UUID v4 when randomUUID is unavailable in a non-secure browser context", () => {
    expect(createUuidV4()).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
    );
});
