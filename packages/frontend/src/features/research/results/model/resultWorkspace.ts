export type ResultWorkspaceTab =
    "OVERVIEW" | "MARKET" | "STATISTICS" | "CANDIDATES" | "GRAPH" | "EXACT_DATA";

export interface ResultWorkspaceSelection {
    readonly tab: ResultWorkspaceTab;
    readonly candidateFingerprint: string | null;
    readonly instrumentId: string | null;
    readonly seriesKey: string | null;
    readonly statisticsFingerprint: string | null;
    readonly graphMode: "SEMANTIC" | "EXACT";
    readonly exactTsEventNs: string | null;
}

export const initialResultWorkspaceSelection: ResultWorkspaceSelection = {
    tab: "OVERVIEW",
    candidateFingerprint: null,
    instrumentId: null,
    seriesKey: null,
    statisticsFingerprint: null,
    graphMode: "SEMANTIC",
    exactTsEventNs: null
};

export type ResultWorkspaceAction =
    | { readonly type: "TAB"; readonly value: ResultWorkspaceTab }
    | { readonly type: "CANDIDATE"; readonly value: string }
    | { readonly type: "INSTRUMENT"; readonly value: string }
    | { readonly type: "SERIES"; readonly value: string }
    | { readonly type: "STATISTICS"; readonly value: string }
    | { readonly type: "GRAPH_MODE"; readonly value: "SEMANTIC" | "EXACT" }
    | { readonly type: "EXACT_TIME"; readonly value: string }
    | {
          readonly type: "ADMIT_DEFAULTS";
          readonly candidateFingerprint: string | null;
          readonly instrumentId: string | null;
          readonly seriesKey: string | null;
          readonly statisticsFingerprint: string | null;
      };

export function reduceResultWorkspace(
    state: ResultWorkspaceSelection,
    action: ResultWorkspaceAction
): ResultWorkspaceSelection {
    switch (action.type) {
        case "TAB":
            return { ...state, tab: action.value };
        case "CANDIDATE":
            return {
                ...state,
                candidateFingerprint: action.value,
                seriesKey: null,
                statisticsFingerprint: null,
                exactTsEventNs: null
            };
        case "INSTRUMENT":
            return { ...state, instrumentId: action.value };
        case "SERIES":
            return { ...state, seriesKey: action.value };
        case "STATISTICS":
            return { ...state, statisticsFingerprint: action.value, exactTsEventNs: null };
        case "GRAPH_MODE":
            return { ...state, graphMode: action.value };
        case "EXACT_TIME":
            return { ...state, exactTsEventNs: action.value };
        case "ADMIT_DEFAULTS":
            return {
                ...state,
                candidateFingerprint: state.candidateFingerprint ?? action.candidateFingerprint,
                instrumentId: state.instrumentId ?? action.instrumentId,
                seriesKey: state.seriesKey ?? action.seriesKey,
                statisticsFingerprint: state.statisticsFingerprint ?? action.statisticsFingerprint
            };
    }
}
