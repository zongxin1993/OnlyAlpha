const SHA256 = /^[0-9a-f]{64}$/;

export type ResearchResultFingerprint = string & {
    readonly __researchResultFingerprint: unique symbol;
};
export type StatisticsFingerprint = string & { readonly __statisticsFingerprint: unique symbol };

function parseSha256(value: string, name: string): string {
    const candidate = value.trim();
    if (!SHA256.test(candidate)) throw new Error(`${name} must be an exact lower-case SHA256`);
    return candidate;
}

export const parseResearchResultFingerprint = (value: string): ResearchResultFingerprint =>
    parseSha256(value, "Research Result fingerprint") as ResearchResultFingerprint;

export const parseStatisticsFingerprint = (value: string): StatisticsFingerprint =>
    parseSha256(value, "Statistics fingerprint") as StatisticsFingerprint;
