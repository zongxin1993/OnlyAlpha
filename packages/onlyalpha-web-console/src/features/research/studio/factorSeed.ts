import type { ResearchCalculationCatalogItemTransport } from "../../../api/research/schemas";
import {
    calculationDraftFromCatalog,
    catalogKey,
    initialResearchDraft,
    type ResearchDraft
} from "./researchDraft";

export type FactorSeed =
    | { readonly kind: "READY"; readonly factorKey: string; readonly draft: ResearchDraft }
    | { readonly kind: "INVALID"; readonly detail: string }
    | null;

function hasControlCharacters(value: string): boolean {
    for (let index = 0; index < value.length; index += 1) {
        const code = value.charCodeAt(index);
        if (code < 32 || code === 127) return true;
    }
    return false;
}

function oneParameter(parameters: URLSearchParams, name: string): string | undefined {
    const values = parameters.getAll(name);
    if (values.length > 1) throw new Error(`${name} must be supplied exactly once.`);
    return values[0];
}

function utcDate(value: string | undefined, name: string): string | undefined {
    if (value === undefined) return undefined;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-"))
        throw new Error(`${name} must be a valid UTC date in YYYY-MM-DD form.`);
    const timestamp = `${value}T00:00:00Z`;
    const parsed = Date.parse(timestamp);
    if (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 10) !== value)
        throw new Error(`${name} must be a valid UTC calendar date.`);
    return timestamp;
}

export function readFactorSeed(
    parameters: URLSearchParams,
    catalog: readonly ResearchCalculationCatalogItemTransport[]
): FactorSeed {
    if (!parameters.has("factor")) return null;
    try {
        const key = oneParameter(parameters, "factor");
        const matches = catalog.filter((entry) => catalogKey(entry) === key);
        const item = matches.length === 1 ? matches[0] : undefined;
        if (item?.kind !== "FACTOR" || item.type_reference.kind !== "FACTOR")
            throw new Error(
                "The exact Factor type and version is not available in the current catalog."
            );
        const instruments = parameters.getAll("instrument");
        if (
            instruments.some(
                (instrument) =>
                    instrument.length === 0 ||
                    /[\s,]/u.test(instrument) ||
                    hasControlCharacters(instrument)
            )
        )
            throw new Error(
                "Instrument IDs must be non-empty exact IDs without whitespace, commas or control characters."
            );
        if (new Set(instruments).size !== instruments.length)
            throw new Error("The instrument selection contains duplicate exact IDs.");
        const start = utcDate(oneParameter(parameters, "from"), "from");
        const end = utcDate(oneParameter(parameters, "to"), "to");
        if (start !== undefined && end !== undefined && start >= end)
            throw new Error("The UTC interval must have from before to; to is exclusive.");
        const initial = initialResearchDraft();
        return {
            kind: "READY",
            factorKey: catalogKey(item),
            draft: {
                ...initial,
                dataset: {
                    ...initial.dataset,
                    universeKind:
                        instruments.length > 1 ? "EXPLICIT_INSTRUMENT_SET" : "SINGLE_INSTRUMENT",
                    instrumentsText: instruments.join(", "),
                    start: start ?? initial.dataset.start,
                    end: end ?? initial.dataset.end
                },
                calculations: [calculationDraftFromCatalog(item, 1, "factor_1")]
            }
        };
    } catch (error) {
        return {
            kind: "INVALID",
            detail: error instanceof Error ? error.message : "Invalid Factor Explorer selection."
        };
    }
}
