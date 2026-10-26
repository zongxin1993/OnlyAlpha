import { createUuidV4, MutationSubmissionIntent } from "./submissionIntent";

const UUIDS = ["00000000-0000-4000-8000-000000000101", "00000000-0000-4000-8000-000000000102"];

afterEach(() => {
    vi.unstubAllGlobals();
});

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
    const getRandomValues = vi.fn((bytes: Uint8Array) => {
        bytes.set(Array.from({ length: 16 }, (_, index) => index));
        return bytes;
    });
    vi.stubGlobal("crypto", { getRandomValues });
    expect(createUuidV4()).toBe("00010203-0405-4607-8809-0a0b0c0d0e0f");
    expect(getRandomValues).toHaveBeenCalledOnce();
    expect(getRandomValues).toHaveBeenCalledWith(expect.any(Uint8Array));
});

it("uses native randomUUID when available", () => {
    const randomUUID = vi.fn(() => UUIDS[0]);
    const getRandomValues = vi.fn();
    vi.stubGlobal("crypto", { randomUUID, getRandomValues });
    expect(createUuidV4()).toBe(UUIDS[0]);
    expect(randomUUID).toHaveBeenCalledOnce();
    expect(getRandomValues).not.toHaveBeenCalled();
});

it("fails explicitly rather than inventing identity without a secure random source", () => {
    vi.stubGlobal("crypto", {});
    expect(() => createUuidV4()).toThrow(/getRandomValues/);
});
