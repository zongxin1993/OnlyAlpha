import responses from "../../../../test-data/web/catalog-navigation/responses.json";

/** Controlled transport metadata. It does not attest a production generation. */
export function chartCatalogFixture() {
    const fixture = structuredClone(responses);
    const capability = fixture.context.ordered_calculation_capabilities[0];
    const witness = fixture.readiness.ordered_calculation_readiness_capabilities[0];
    const provider = fixture.context.ordered_providers[0];
    const parameter = capability?.type_descriptor.parameters[0];
    const output = capability?.type_descriptor.outputs[0];
    if (
        capability === undefined ||
        witness === undefined ||
        provider === undefined ||
        parameter === undefined ||
        output === undefined
    )
        throw new Error("Incomplete Catalog test fixture");
    return {
        ...fixture,
        runtime: fixture.active.runtime_generation_fingerprint,
        catalog: fixture.binding.catalog_generation_fingerprint,
        capability,
        witness,
        provider,
        parameter,
        output
    };
}
