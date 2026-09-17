# Quantitative Plugins and Examples

ADR 0110 and ADR 0129 define the active boundary. Public reusable L1 Operators and L2 Indicators live in official plugins. Production
L3 Factors and L4 Strategies are private database-native authoring assets; Git repositories and distributions are optional
interoperability/materialization paths. The main repository keeps exactly two non-production reference packages:
`examples/onlyalpha-example-alpha/` and `examples/onlyalpha-example-strategies/`.

Core never imports these concrete implementations. Example Alpha registers through the public Calculation SPI; example Strategy
documents travel through Definition Resolve and verified Freeze rather than becoming callback or filesystem runtime authority.

The public examples intentionally remain distribution-based contract witnesses. ADR 0111's checkout and installed-distribution modes
remain available for optional interoperability and executable materialization, but they are not the required Private L3/L4 production
authoring workflow. ADR 0129 defines PostgreSQL-backed Draft/Revision authoring, exact L3 API binding, and structured L4 definitions;
no Core component recursively executes arbitrary paths or treats a package location as asset/runtime identity.

Every L1-L4 library also exposes one `onlyalpha.quant_assets` provider. The management catalog binds provider version to exact content and
creates immutable generation fingerprints. A changed provider must use a new provider version; semantic changes also bump their Calculation
or Strategy-asset semantic version. Refresh affects new authoring/admission only and never mutates an active Run or StrategyRevision.

ADR 0117 remains the executable materialization boundary: exact artifact bytes are validated in an independent clean Runtime
Generation before durable new-work activation. Public examples and any optional private materialization derive the same artifact
contract. Runtime rollback changes only the guarded new-work pointer, and historical StrategyRevisions resolve exact implementation
fingerprints without a latest-version fallback.
