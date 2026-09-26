const productionModules = import.meta.glob<string>(
    [
        "../features/research/**/*.ts",
        "../features/research/**/*.tsx",
        "../features/data/**/*.ts",
        "../features/data/**/*.tsx",
        "../visualization/**/*.ts",
        "../visualization/**/*.tsx",
        "../charts/**/*.ts",
        "../charts/**/*.tsx",
        "!../**/*.test.ts",
        "!../**/*.test.tsx"
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

it("does not parse physical Artifact files or generate semantic fingerprints", () => {
    const forbidden = ["parquet-wasm", "pyarrow", "readParquet(", "crypto.subtle", "createHash("];
    expect(forbidden.filter((item) => source.toLowerCase().includes(item.toLowerCase()))).toEqual(
        []
    );
});

it("contains third-party renderer imports inside their OnlyAlpha adapters", () => {
    const allowed: Readonly<Record<string, readonly string[]>> = {
        "lightweight-charts": ["/visualization/financial/lightweight/", "/charts/lightweight/"],
        echarts: ["/visualization/scientific/echarts/"],
        "@viz-js/viz": ["/visualization/graph/graphviz/"]
    } as const;
    for (const [library, boundaries] of Object.entries(allowed)) {
        const outside = Object.entries(productionModules)
            .filter(([, moduleSource]) => moduleSource.includes(`"${library}"`))
            .map(([path]) => path)
            .filter((path) => !boundaries.some((boundary) => path.includes(boundary)));
        expect(outside).toEqual([]);
    }
});

it("has exactly one Draft to Definition transport owner", () => {
    expect(source.match(/function buildResearchDefinitionTransport\(/g)).toHaveLength(1);
});

it("gives the data source surface no second persistence or provider authority", () => {
    const dataSourceModules = Object.entries(productionModules)
        .filter(([path]) => path.includes("/features/data/"))
        .map(([, moduleSource]) => moduleSource)
        .join("\n");
    expect(dataSourceModules.length).toBeGreaterThan(0);
    const forbidden = [
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "api.binance.com",
        "api.binance.us",
        "data-api.binance.vision",
        "stream.binance.com",
        "stream.binance.us",
        "stream.testnet.binance.vision",
        "fstream.binance.com",
        "wss://",
        "clickhouse",
        "psycopg",
        "postgresql://",
        "createHash(",
        "crypto.subtle"
    ];
    expect(forbidden.filter((item) => dataSourceModules.includes(item))).toEqual([]);
});
