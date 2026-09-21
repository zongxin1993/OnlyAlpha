import { MutationSubmissionIntent } from "./submissionIntent";

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
