import {
    parseResearchSubmissionKey,
    type ResearchSubmissionKey
} from "../../../domain/research/identity";

export class ResearchRunSubmissionIntent {
    private pending: {
        readonly specificationFingerprint: string;
        readonly submissionKey: ResearchSubmissionKey;
    } | null = null;

    constructor(private readonly createUuid: () => string = () => crypto.randomUUID()) {}

    keyFor(specificationFingerprint: string): ResearchSubmissionKey {
        if (this.pending?.specificationFingerprint === specificationFingerprint)
            return this.pending.submissionKey;
        const submissionKey = parseResearchSubmissionKey(this.createUuid());
        this.pending = { specificationFingerprint, submissionKey };
        return submissionKey;
    }

    confirm(specificationFingerprint: string): void {
        if (this.pending?.specificationFingerprint === specificationFingerprint)
            this.pending = null;
    }
}

export const shouldAdmitResolution = (
    requestRevision: number,
    currentRevision: number,
    aborted: boolean
): boolean => requestRevision === currentRevision && !aborted;
