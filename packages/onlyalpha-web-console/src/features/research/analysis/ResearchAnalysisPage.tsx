import { useInfiniteQuery } from "@tanstack/react-query";
import { useRef, useState, type KeyboardEvent, type SyntheticEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useResearchApi } from "../../../app/providers";
import {
    parseResearchResultFingerprint,
    type ResearchResultFingerprint
} from "../../../domain/research/identity";
import type { ResearchRunSummary } from "../../../domain/research/model";
import { QueryError } from "../../../shared/components/QueryState";
import { WorkspaceIcon } from "../../../shared/components/WorkspaceIcon";
import { runsOptions } from "../runs/queries";
import { AnalysisEnginePanel, ResearchJourney } from "./AnalysisEnginePanel";
import {
    EconomicCalendarPanel,
    MarketPulseGrid,
    MarketTickerStrip,
    OpportunityRadar,
    RecentResearchPanel
} from "./AnalysisPanels";
import "./analysis.css";

type AnalysisTab = "analysis" | "research";

function admitSelection(raw: string | null) {
    if (raw === null) return { result: null, error: null };
    try {
        return { result: parseResearchResultFingerprint(raw), error: null };
    } catch {
        return {
            result: null,
            error: "INVALID_QUERY: select an exact lower-case SHA256 Research Result fingerprint."
        };
    }
}

export function ResearchAnalysisPage() {
    const client = useResearchApi();
    const runs = useInfiniteQuery(runsOptions(client));
    const [searchParams, setSearchParams] = useSearchParams();
    const [tab, setTab] = useState<AnalysisTab>("analysis");
    const rawResult = searchParams.get("result");
    const selection = admitSelection(rawResult);
    const loadedRuns = runs.data?.pages.flatMap((page) => page.runs) ?? [];
    function openAnalysis(result: ResearchResultFingerprint) {
        setSearchParams((previous) => {
            const next = new URLSearchParams(previous);
            next.set("result", result);
            return next;
        });
        setTab("analysis");
    }
    return (
        <main className="analysis-page" aria-label="Research analysis workstation">
            <OpportunityRadar />
            <div className="analysis-workstation">
                <AnalysisTabs selected={tab} onSelect={setTab} />
                <MarketTickerStrip />
                <div className="analysis-layout">
                    <aside className="analysis-market-rail" aria-label="Market context">
                        <MarketPulseGrid />
                        <EconomicCalendarPanel />
                    </aside>
                    <div
                        className="analysis-center"
                        role="tabpanel"
                        id="analysis-panel"
                        aria-labelledby={`analysis-tab-${tab}`}
                    >
                        <AnalysisControlBar
                            key={rawResult ?? "empty"}
                            result={selection.result}
                            runs={loadedRuns}
                            onOpen={openAnalysis}
                        />
                        {selection.error === null ? null : (
                            <p role="alert" className="error">
                                {selection.error}
                            </p>
                        )}
                        {runs.isError ? (
                            <div className="analysis-run-error">
                                <QueryError error={runs.error} retry={() => void runs.refetch()} />
                            </div>
                        ) : null}
                        {tab === "analysis" ? (
                            <AnalysisEnginePanel result={selection.result} />
                        ) : (
                            <ResearchJourney />
                        )}
                    </div>
                    <RecentResearchPanel
                        runs={loadedRuns}
                        loading={runs.isPending}
                        unavailable={runs.isError}
                        onSelectResult={() => {
                            setTab("analysis");
                        }}
                    />
                </div>
            </div>
        </main>
    );
}

function AnalysisTabs({
    selected,
    onSelect
}: {
    readonly selected: AnalysisTab;
    readonly onSelect: (tab: AnalysisTab) => void;
}) {
    const tabs = [
        { id: "analysis", label: "Instant Analysis", icon: "analysis" },
        { id: "research", label: "Research", icon: "research" }
    ] as const;
    const buttons = useRef<(HTMLButtonElement | null)[]>([]);
    function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
        let next: number;
        if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
        else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = tabs.length - 1;
        else return;
        event.preventDefault();
        const target = tabs[next];
        if (target === undefined) return;
        onSelect(target.id);
        buttons.current[next]?.focus();
    }
    return (
        <div className="analysis-tabs" role="tablist" aria-label="Analysis views">
            {tabs.map((tab, index) => (
                <button
                    key={tab.id}
                    ref={(button) => {
                        buttons.current[index] = button;
                    }}
                    type="button"
                    role="tab"
                    id={`analysis-tab-${tab.id}`}
                    aria-controls="analysis-panel"
                    aria-selected={selected === tab.id}
                    tabIndex={selected === tab.id ? 0 : -1}
                    onClick={() => {
                        onSelect(tab.id);
                    }}
                    onKeyDown={(event) => {
                        navigate(event, index);
                    }}
                >
                    <WorkspaceIcon name={tab.icon} />
                    {tab.label}
                </button>
            ))}
        </div>
    );
}

function AnalysisControlBar({
    result,
    runs,
    onOpen
}: {
    readonly result: ResearchResultFingerprint | null;
    readonly runs: readonly ResearchRunSummary[];
    readonly onOpen: (result: ResearchResultFingerprint) => void;
}) {
    const [value, setValue] = useState<string>(result ?? "");
    const [error, setError] = useState<string | null>(null);
    const completed = runs.filter((run) => run.state === "COMPLETED" && run.resultRef !== null);
    function submit(event: SyntheticEvent<HTMLFormElement>) {
        event.preventDefault();
        try {
            const fingerprint = parseResearchResultFingerprint(value);
            setError(null);
            onOpen(fingerprint);
        } catch {
            setError(
                "Enter an exact lower-case SHA256 Result fingerprint or select a completed Run."
            );
        }
    }
    return (
        <form
            className="analysis-control-bar"
            onSubmit={submit}
            noValidate
            aria-label="Analysis controls"
        >
            <div className="analysis-control-row">
                <label className="analysis-target">
                    <span className="visually-hidden">Completed Research Run</span>
                    <select
                        aria-label="Completed Research Run"
                        value={completed.find((run) => run.resultRef === value)?.runId ?? ""}
                        disabled={completed.length === 0}
                        onChange={(event) => {
                            setValue(
                                completed.find((run) => run.runId === event.target.value)
                                    ?.resultRef ?? ""
                            );
                            setError(null);
                        }}
                    >
                        <option value="">
                            {completed.length === 0
                                ? "No completed Runs available"
                                : "Select a completed Research Run"}
                        </option>
                        {completed.map((run) => (
                            <option key={run.runId} value={run.runId}>
                                {run.runId} · {run.finishedAt ?? "COMPLETED"}
                            </option>
                        ))}
                    </select>
                </label>
                <button
                    type="submit"
                    className="analysis-primary-action"
                    disabled={value.trim() === ""}
                >
                    <WorkspaceIcon name="analysis" />
                    Open Analysis
                </button>
                <Link className="secondary-link analysis-history" to="/research/runs">
                    <WorkspaceIcon name="clock" />
                    History
                </Link>
            </div>
            <details className="analysis-exact-input">
                <summary>Use an exact Result fingerprint</summary>
                <label htmlFor="analysis-result-fingerprint">Research Result fingerprint</label>
                <input
                    id="analysis-result-fingerprint"
                    value={value}
                    onChange={(event) => {
                        setValue(event.target.value);
                        setError(null);
                    }}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="64 lower-case hexadecimal characters"
                />
            </details>
            {error === null ? null : (
                <p className="field-error" role="alert">
                    {error}
                </p>
            )}
        </form>
    );
}
