import { parseDecimalText } from "./decimal";
import { parseResearchResultFingerprint, parseStatisticsFingerprint } from "./identity";
import { formatUtcNanoseconds, nanosecondsToRequestText, parseUnixNanoseconds } from "./time";

describe("exact Web values", () => {
    it("admits exact identities and trims only presentation whitespace", () => {
        expect(parseResearchResultFingerprint(`  ${"a".repeat(64)} `)).toBe("a".repeat(64));
        expect(parseStatisticsFingerprint("b".repeat(64))).toBe("b".repeat(64));
        expect(() => parseResearchResultFingerprint("A".repeat(64))).toThrow(/lower-case SHA256/);
        expect(() => parseStatisticsFingerprint("short")).toThrow(/lower-case SHA256/);
    });

    it("keeps nanoseconds beyond Number safe range as bigint and request digits", () => {
        const exact = parseUnixNanoseconds("1780000000000000123");
        expect(exact).toBe(1_780_000_000_000_000_123n);
        expect(nanosecondsToRequestText(exact)).toBe("1780000000000000123");
        expect(formatUtcNanoseconds(exact)).toMatch(/\.000000123Z$/);
        expect(formatUtcNanoseconds(parseUnixNanoseconds("999999999999999999999999999999"))).toBe(
            "UTC date outside browser range"
        );
        expect(() => parseUnixNanoseconds("01")).toThrow(/canonical/);
        expect(() => parseUnixNanoseconds("1.0")).toThrow(/canonical/);
    });

    it("keeps canonical fixed Decimal as text", () => {
        expect(parseDecimalText("-12.3400")).toBe("-12.3400");
        expect(parseDecimalText("0")).toBe("0");
        expect(() => parseDecimalText("1e3")).toThrow(/canonical/);
        expect(() => parseDecimalText("01.2")).toThrow(/canonical/);
    });
});
