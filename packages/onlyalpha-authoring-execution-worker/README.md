# OnlyAlpha Authoring Execution Worker

This component binds one exact Private Asset DB Revision and Candidate Catalog/Provider composition to the existing Product Research
Run, Attempt, Worker, Runtime and Evidence authorities. It does not define a second Research engine or persistence model.

The Product API admission composition and Worker composition must both use the exact candidate Catalog/Provider composition represented
by one Authoring Execution Generation. `OnlyAuthoringExecutionGenerationStore` must be committed and re-anchored to the exact Private
Asset DB Revision before either composition is exposed. The API uses `only_compose_authoring_research_admission`; the Worker uses
`only_compose_authoring_research_worker`. Both reject a missing or mismatched generation before a Run is persisted or claimed.

The normal Product API and normal Research Worker remain generation-neutral and accept/claim only non-authoring Runs. Promotion, Catalog
activation, Strategy Freeze, SIM and LIVE are separate authorities and are intentionally outside this component.
