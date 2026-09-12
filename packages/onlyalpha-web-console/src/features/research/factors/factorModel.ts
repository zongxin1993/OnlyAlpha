import type { ResearchCalculationCatalogItemTransport } from "../../../api/research/schemas";
import type { ResearchResultFingerprint } from "../../../domain/research/identity";
import type {
    ResearchCandidate,
    ResearchCandidateGraph,
    ResearchGraphNode,
    ResearchPublishedSeries,
    ResearchPublishedSeriesCatalog,
    ResearchStatisticsCatalog,
    ResearchStatisticsDescriptor
} from "../../../domain/research/model";
import type { UnixNanoseconds } from "../../../domain/research/time";
import { parseUnixNanoseconds } from "../../../domain/research/time";
import { publishedSeriesKey } from "../results/model/selectors";

export interface FactorSeriesOption {
    readonly key: string;
    readonly series: ResearchPublishedSeries;
    readonly node: ResearchGraphNode;
    readonly label: string;
}

export function factorCatalogItems(
    items: readonly ResearchCalculationCatalogItemTransport[],
    search: string
): readonly ResearchCalculationCatalogItemTransport[] {
    const terms = search.trim().toLowerCase().split(/\s+/);
    return items.filter((item) => {
        if (item.type_reference.kind !== "FACTOR") return false;
        const text = [
            `${item.type_reference.type_id}@${item.type_reference.semantic_version}`,
            ...item.outputs.flatMap((output) => [output.name, output.semantic_type])
        ]
            .join(" ")
            .toLowerCase();
        return terms.every((term) => text.includes(term));
    });
}

function contractError(detail: string): never {
    throw new Error(`CONTRACT_ERROR: ${detail}`);
}

function isFactorOutput(node: ResearchGraphNode, series: ResearchPublishedSeries): boolean {
    if (node.nodeFingerprint !== series.nodeFingerprint)
        return contractError("Published Factor node identity does not match its graph node");
    if (node.definition.kind !== "FACTOR") return false;
    const outputs = node.definition.outputs.filter((output) => output.name === series.outputName);
    if (outputs.length !== 1)
        return contractError("Published Factor output is missing or ambiguous in its graph node");
    const output = outputs[0];
    if (output === undefined) return contractError("Published Factor output is missing");
    if (!["FACTOR_VALUE", "FACTOR_SCORE"].includes(output.semanticType)) return false;
    if (!["DECIMAL", "INTEGER"].includes(output.dataType))
        return contractError("Published Factor output does not have a numeric data type");
    if (output.dataType !== series.valueKind)
        return contractError("Published Factor value kind does not match its exact graph output");
    return true;
}

export function admittedFactorSeries(
    result: ResearchResultFingerprint,
    candidate: ResearchCandidate,
    graph: ResearchCandidateGraph,
    published: ResearchPublishedSeriesCatalog
): readonly FactorSeriesOption[] {
    if (
        graph.researchResultFingerprint !== result ||
        published.researchResultFingerprint !== result
    )
        return contractError("Factor graph or Published Series belongs to a different Result");
    if (
        graph.candidateFingerprint !== candidate.candidateFingerprint ||
        graph.calculationFingerprint !== candidate.calculationFingerprint ||
        graph.graphFingerprint !== candidate.graphFingerprint
    )
        return contractError(
            "Factor graph does not match the exact Candidate calculation and graph"
        );
    const nodes = new Map(graph.graph.nodes.map((node) => [node.nodeFingerprint, node]));
    if (nodes.size !== graph.graph.nodes.length)
        return contractError("Factor graph contains duplicate node identities");
    const options: FactorSeriesOption[] = [];
    const keys = new Set<string>();
    for (const series of published.series) {
        if (
            series.candidateFingerprint !== null &&
            series.candidateFingerprint !== candidate.candidateFingerprint
        )
            continue;
        if (series.calculationFingerprint !== candidate.calculationFingerprint) {
            if (series.candidateFingerprint === null) continue;
            return contractError("Published Series does not match its Candidate calculation");
        }
        const node = nodes.get(series.nodeFingerprint);
        if (node === undefined)
            return contractError("Published Series references an unknown Candidate graph node");
        if (!isFactorOutput(node, series)) continue;
        const key = publishedSeriesKey(series);
        if (keys.has(key)) return contractError("Published Factor Series identity is duplicated");
        keys.add(key);
        options.push({
            key,
            series,
            node,
            label: `${node.alias === null ? "" : `${node.alias} · `}${node.definition.typeId}@${node.definition.semanticVersion} · ${series.outputName}`
        });
    }
    return options;
}

export function statisticsForFactor(
    result: ResearchResultFingerprint,
    candidate: ResearchCandidate,
    option: FactorSeriesOption,
    statistics: ResearchStatisticsCatalog
): readonly ResearchStatisticsDescriptor[] {
    if (statistics.researchResultFingerprint !== result)
        return contractError("Statistics belongs to a different Research Result");
    if (
        option.series.calculationFingerprint !== candidate.calculationFingerprint ||
        (option.series.candidateFingerprint !== null &&
            option.series.candidateFingerprint !== candidate.candidateFingerprint) ||
        option.key !== publishedSeriesKey(option.series) ||
        !isFactorOutput(option.node, option.series)
    )
        return contractError("Selected Factor Series does not match the exact Candidate");
    return statistics.statistics.filter(
        (descriptor) =>
            candidate.statisticsFingerprints.includes(descriptor.statisticsFingerprint) &&
            descriptor.feature.calculationFingerprint === option.series.calculationFingerprint &&
            descriptor.feature.nodeFingerprint === option.series.nodeFingerprint &&
            descriptor.feature.outputName === option.series.outputName
    );
}

function parseUtcDate(value: string): UnixNanoseconds | undefined {
    if (value === "") return undefined;
    if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith("0000-"))
        throw new Error("INVALID_TIME_RANGE: use a real UTC date in YYYY-MM-DD form");
    const milliseconds = Date.parse(`${value}T00:00:00.000Z`);
    if (
        !Number.isSafeInteger(milliseconds) ||
        new Date(milliseconds).toISOString().slice(0, 10) !== value
    )
        throw new Error("INVALID_TIME_RANGE: use a real UTC date in YYYY-MM-DD form");
    return parseUnixNanoseconds((BigInt(milliseconds) * 1_000_000n).toString());
}

/** Dates are UTC midnights; the end date is exclusive, never extended by a day. */
export function parseFactorDateRange(
    fromDate: string,
    toDate: string
): { readonly from?: UnixNanoseconds; readonly to?: UnixNanoseconds } {
    const from = parseUtcDate(fromDate);
    const to = parseUtcDate(toDate);
    if (from !== undefined && to !== undefined && from >= to)
        throw new Error("INVALID_TIME_RANGE: the exclusive end must be after the start");
    return {
        ...(from === undefined ? {} : { from }),
        ...(to === undefined ? {} : { to })
    };
}
