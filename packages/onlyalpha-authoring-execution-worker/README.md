# OnlyAlpha Authoring Execution Worker

This component binds one verified private-asset Git Snapshot and Candidate Catalog generation to the existing Product Research Run,
Attempt, Worker, Runtime and Evidence authorities. It does not define a second Research engine or persistence model.

For controlled local authoring, the Product API admission composition and Worker composition must both be created inside processes that
loaded the candidate from the exact clean Snapshot. For distributed operation, both processes must use the same immutable
content-addressed candidate artifact. `OnlyAuthoringExecutionGenerationStore` must be committed and verified before either composition is
exposed. The API uses `only_compose_authoring_research_admission`; the Worker uses
`only_compose_authoring_research_worker`. Both reject a missing or mismatched generation before a Run is persisted or claimed.

The normal Product API and normal Research Worker remain generation-neutral and accept/claim only non-authoring Runs. Promotion, Catalog
activation, Strategy Freeze, SIM and LIVE are separate authorities and are intentionally outside this component.
