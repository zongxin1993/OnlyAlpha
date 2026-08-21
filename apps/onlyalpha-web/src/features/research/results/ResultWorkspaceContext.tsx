import { createContext, useContext, type Dispatch } from "react";
import type {
    ResearchArtifactSummary,
    ResearchCandidateCatalog,
    ResearchPublishedSeriesCatalog,
    ResearchStatisticsCatalog
} from "../../../domain/research/model";
import type { ResultWorkspaceAction, ResultWorkspaceSelection } from "./model/resultWorkspace";

export interface ResultWorkspaceValue {
    readonly summary: ResearchArtifactSummary;
    readonly candidates: ResearchCandidateCatalog | null;
    readonly published: ResearchPublishedSeriesCatalog | null;
    readonly statistics: ResearchStatisticsCatalog;
    readonly selection: ResultWorkspaceSelection;
    readonly dispatch: Dispatch<ResultWorkspaceAction>;
    readonly scientificUnavailable: boolean;
}

const Context = createContext<ResultWorkspaceValue | null>(null);
export const ResultWorkspaceProvider = Context.Provider;

export function useResultWorkspace(): ResultWorkspaceValue {
    const value = useContext(Context);
    if (value === null) throw new Error("Result Workspace context is unavailable");
    return value;
}
