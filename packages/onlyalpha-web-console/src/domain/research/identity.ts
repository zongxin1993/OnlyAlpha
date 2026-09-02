const SHA256 = /^[0-9a-f]{64}$/;
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export type ResearchResultFingerprint = string & {
    readonly __researchResultFingerprint: unique symbol;
};
export type StatisticsFingerprint = string & { readonly __statisticsFingerprint: unique symbol };
export type Sha256Fingerprint = string & { readonly __sha256Fingerprint: unique symbol };
export type ResearchRunId = string & { readonly __researchRunId: unique symbol };
export type ResearchSubmissionKey = string & { readonly __researchSubmissionKey: unique symbol };

function parseSha256(value: string, name: string): string {
    const candidate = value.trim();
    if (!SHA256.test(candidate)) throw new Error(`${name} must be an exact lower-case SHA256`);
    return candidate;
}

export const parseResearchResultFingerprint = (value: string): ResearchResultFingerprint =>
    parseSha256(value, "Research Result fingerprint") as ResearchResultFingerprint;

export const parseStatisticsFingerprint = (value: string): StatisticsFingerprint =>
    parseSha256(value, "Statistics fingerprint") as StatisticsFingerprint;

export const parseSha256Fingerprint = (value: string): Sha256Fingerprint =>
    parseSha256(value, "Fingerprint") as Sha256Fingerprint;

function parseUuid4(value: string, name: string): string {
    if (!UUID4.test(value)) throw new Error(`${name} must be an exact canonical UUID4`);
    return value;
}

export const parseResearchRunId = (value: string): ResearchRunId =>
    parseUuid4(value, "Research Run ID") as ResearchRunId;

export const parseResearchSubmissionKey = (value: string): ResearchSubmissionKey =>
    parseUuid4(value, "Research submission key") as ResearchSubmissionKey;
