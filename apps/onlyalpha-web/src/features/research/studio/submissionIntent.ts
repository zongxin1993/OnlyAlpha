import {
    parseResearchSubmissionKey,
    type ResearchSubmissionKey
} from "../../../domain/research/identity";

export class ResearchRunSubmissionIntent {
    private pending: ResearchSubmissionKey | null = null;

    constructor(private readonly createUuid: () => string = () => crypto.randomUUID()) {}

    current(): ResearchSubmissionKey {
        this.pending ??= parseResearchSubmissionKey(this.createUuid());
        return this.pending;
    }

    complete(): void {
        this.pending = null;
    }
}

export const shouldAdmitResolution = (
    requestRevision: number,
    currentRevision: number,
    aborted: boolean
): boolean => requestRevision === currentRevision && !aborted;
