# Quantitative Plugins and Examples

ADR 0110, ADR 0129, ADR 0131 and ADR 0132 define the active boundary. Public reusable Operators and Indicators live in official
plugins. Production Factor and Strategy assets are private database-native authoring assets; Git repositories and distributions are optional
interoperability/materialization paths. The main repository keeps portable non-production seeds under `examples/private-assets/`.

Seeds are imported through the Private Asset Authority before validation or execution. Factor `source.py` becomes Revision content only;
Strategy `strategy.json` becomes a structured Draft/Revision. Neither seed path is execution or Runtime Authority.

ADR 0111's checkout and installed-distribution modes remain available for optional interoperability and executable materialization, but
they are not the required Private Factor/Strategy production authoring workflow. ADR 0129 and ADR 0132 define PostgreSQL-backed
Draft/Revision authoring, exact Factor API binding, and structured Strategy definitions;
no Core component recursively executes arbitrary paths or treats a package location as asset/runtime identity.

Public Operator/Indicator distributions expose `onlyalpha.quant_assets` providers. A validated Private Factor Revision derives a
snapshot-backed provider without a distribution identity. The management catalog binds provider version to exact content and
creates immutable generation fingerprints. A changed provider must use a new provider version; semantic changes also bump their Calculation
or Strategy-asset semantic version. Refresh affects new authoring/admission only and never mutates an active Run or StrategyRevision.

ADR 0117 remains the executable materialization boundary: exact artifact bytes are validated in an independent clean Runtime
Generation before durable new-work activation. Optional private materialization uses the same artifact contract. Runtime rollback
changes only the guarded new-work pointer, and historical StrategyRevisions resolve exact implementation
fingerprints without a latest-version fallback.
