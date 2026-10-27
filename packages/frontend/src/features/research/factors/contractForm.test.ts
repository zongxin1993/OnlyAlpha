import { describe, expect, it } from "vitest";
import {
    inspectContract,
    rowsFromContract,
    contractFromRows,
    changeRow,
    newRow,
    type ContractKind
} from "./contractForm";
function project(kind: ContractKind, text: string) {
    const result = rowsFromContract(kind, text);
    if (result === null) throw new Error("expected ordinary projection");
    return result;
}
function first(kind: ContractKind, text: string) {
    const result = project(kind, text).at(0);
    if (result === undefined) throw new Error("expected row");
    return result;
}
describe("lossless private Factor contract editing", () => {
    it("preserves raw text, omission, nullable spelling and exact defaults through no-op and revert", () => {
        const raw = ' { "close" : {"type":"DECIMAL","missing":false} } ';
        const rows = project("input_contract", raw);
        expect(contractFromRows("input_contract", rows, raw).text).toBe(raw);
        const changed = changeRow(first("input_contract", raw), "nullable", true);
        expect(JSON.parse(contractFromRows("input_contract", [changed], raw).text)).toEqual({
            close: { type: "DECIMAL", missing: true }
        });
        expect(
            contractFromRows("input_contract", [changeRow(changed, "nullable", false)], raw).text
        ).toBe(raw);
    });
    it("keeps required and default independent including implicit required and coordinated edits", () => {
        const raw = '{"period":{"type":"INTEGER"}}';
        const row = first("parameter_contract", raw);
        const enabled = changeRow(row, "hasDefault", true);
        const entered = changeRow(enabled, "defaultText", "20");
        const result = contractFromRows("parameter_contract", [entered], raw);
        expect(result.companion).toBe(true);
        expect(JSON.parse(result.text)).toEqual({
            period: { type: "INTEGER", required: true, default: 20 }
        });
        expect(
            contractFromRows("parameter_contract", [changeRow(entered, "hasDefault", false)], raw)
                .text
        ).toBe(raw);
        expect(
            contractFromRows("parameter_contract", [changeRow(row, "required", false)], raw).error
        ).toMatch(/非必填/);
    });
    it("preserves integer versus string decimal defaults, false, empty strings and explicit flags", () => {
        for (const raw of [
            '{"x":{"type":"DECIMAL","default":"0.10"}}',
            '{"x":{"type":"DECIMAL","default":20,"required":true}}',
            '{"x":{"type":"BOOLEAN","default":false}}',
            '{"x":{"type":"STRING","default":""}}',
            "{}"
        ]) {
            const rows = project("parameter_contract", raw);
            expect(rows).not.toBeNull();
            expect(contractFromRows("parameter_contract", rows, raw).text).toBe(raw);
        }
    });
    it("leaves arbitrary or ambiguous authoring objects advanced without losing content", () => {
        for (const raw of [
            '{"x":{"type":"DECIMAL","extension":{"nested":[null,1,"1"]}}}',
            '{"x":{"type":"DECIMAL","nullable":false,"missing":false}}',
            '{"x":null}',
            '{"x":{"type":"UNKNOWN"}}'
        ]) {
            expect(inspectContract(raw).error).toBe("");
            expect(rowsFromContract("input_contract", raw)).toBeNull();
        }
    });
    it("rejects duplicate keys before use, unsafe/fractional numbers, malformed roots and NUL without rounding", () => {
        for (const raw of [
            '{"x":{},"x":{}}',
            '{"x":{"type":"DECIMAL","type":"INTEGER"}}',
            '{"x":9007199254740993}',
            '{"x":1e2}',
            '{"x":1.5}',
            "[]",
            '{"x":"\\u0000"}',
            "{"
        ])
            expect(inspectContract(raw).error).not.toBe("");
        expect(inspectContract('{"x":"1e2"}').error).toBe("");
    });
    it("reports row-local errors without dropping duplicate or unfinished rows", () => {
        const a = changeRow(newRow("input_contract"), "name", "close");
        expect(contractFromRows("input_contract", [a, a], "{}").error).toMatch(/重复/);
        expect(contractFromRows("input_contract", [newRow("input_contract")], "{}").error).toMatch(
            /名称/
        );
    });
});

it("keeps a negative-zero default advanced instead of normalizing its representation", () => {
    const raw = '{ "scale":{"type":"INTEGER","default":-0} }';
    expect(inspectContract(raw).error).toBe("");
    expect(rowsFromContract("parameter_contract", raw)).toBeNull();
});
it("checks scalar depth at the same canonical boundary as containers", () => {
    const raw = '{"x":' + "[".repeat(32) + "0" + "]".repeat(32) + "}";
    expect(inspectContract(raw).error).toMatch(/深度/);
});
