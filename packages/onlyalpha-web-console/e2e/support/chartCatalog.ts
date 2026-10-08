import { readFileSync } from "node:fs";

type Capability = Record<string, unknown> & {
    type_id: string;
    implementation_fingerprint: string;
};
interface Responses {
    active: { schema_version: number; runtime_generation_fingerprint: string };
    binding: {
        schema_version: number;
        runtime_generation_fingerprint: string;
        catalog_generation_fingerprint: string;
    };
    context: Record<string, unknown> & { ordered_calculation_capabilities: Capability[] };
    readiness: Record<string, unknown> & {
        ordered_calculation_readiness_capabilities: (Record<string, unknown> & {
            readiness_contract_versions: number[];
        })[];
    };
}

export function chartCatalogFixture() {
    const fixture = JSON.parse(
        readFileSync(
            new URL("../../../../test-data/web/catalog-navigation/responses.json", import.meta.url),
            "utf8"
        )
    ) as Responses;
    return {
        ...fixture,
        runtime: fixture.active.runtime_generation_fingerprint,
        catalog: fixture.binding.catalog_generation_fingerprint,
        capability: fixture.context.ordered_calculation_capabilities[0],
        witness: fixture.readiness.ordered_calculation_readiness_capabilities[0]
    };
}
