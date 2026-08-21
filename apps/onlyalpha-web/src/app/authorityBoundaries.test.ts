const productionModules = import.meta.glob<string>(
    [
        "../features/research/studio/definitionTransport.ts",
        "../features/research/studio/researchDraft.ts",
        "../features/research/studio/ResearchStudioPage.tsx",
        "../features/research/runs/ResearchRunPage.tsx",
        "../features/research/runs/ResearchRunsPage.tsx"
    ],
    { eager: true, query: "?raw", import: "default" }
);

const source = Object.values(productionModules).join("\n");

it("introduces no browser semantic runtime or parallel authority store", () => {
    const forbidden = [
        "eval(",
        "new Function(",
        "PredicateRuntime",
        "PredicateStore",
        "ScientificEvidenceStore",
        "CandidateStore",
        "SignalStore",
        "GraphStore",
        "ResultStore",
        "ArtifactStore"
    ];
    expect(forbidden.filter((item) => source.includes(item))).toEqual([]);
});

it("has exactly one Draft to Definition transport owner", () => {
    expect(source.match(/function buildResearchDefinitionTransport\(/g)).toHaveLength(1);
});
