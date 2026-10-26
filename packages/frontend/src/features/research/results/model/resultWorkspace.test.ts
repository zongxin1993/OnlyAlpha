import { initialResultWorkspaceSelection, reduceResultWorkspace } from "./resultWorkspace";

it("keeps one candidate selection and clears dependent presentation selectors", () => {
    const admitted = reduceResultWorkspace(initialResultWorkspaceSelection, {
        type: "ADMIT_DEFAULTS",
        candidateFingerprint: "candidate-a",
        instrumentId: "510300",
        seriesKey: "series-a",
        statisticsFingerprint: "statistics-a"
    });
    const selected = reduceResultWorkspace(admitted, {
        type: "CANDIDATE",
        value: "candidate-b"
    });
    expect(selected).toMatchObject({
        candidateFingerprint: "candidate-b",
        instrumentId: "510300",
        seriesKey: null,
        statisticsFingerprint: null,
        exactTsEventNs: null
    });
});
