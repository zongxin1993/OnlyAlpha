export type ResearchWebErrorCode =
    | "INVALID_QUERY"
    | "INVALID_TIME_RANGE"
    | "INVALID_PAGE_LIMIT"
    | "RESEARCH_ARTIFACT_NOT_FOUND"
    | "RESEARCH_ARTIFACT_CORRUPT"
    | "STATISTICS_NOT_FOUND"
    | "TRANSPORT_ERROR"
    | "CONTRACT_ERROR";

export class ResearchWebError extends Error {
    constructor(
        readonly code: ResearchWebErrorCode,
        message: string,
        readonly status?: number
    ) {
        super(message);
        this.name = "ResearchWebError";
    }
}

export function errorMessage(error: unknown): string {
    return error instanceof ResearchWebError
        ? `${error.code}: ${error.message}`
        : "Unexpected error";
}
