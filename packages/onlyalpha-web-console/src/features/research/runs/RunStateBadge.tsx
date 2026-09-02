import type { ResearchRunState } from "../../../domain/research/model";

export function RunStateBadge({ state }: { readonly state: ResearchRunState }) {
    return <span className={`run-state run-state-${state.toLowerCase()}`}>{state}</span>;
}
