# OnlyAlpha Agent Orchestrator

This independently buildable package is the deployment/runtime assembly boundary for the Agent workflow. B3.4.3-A provides only the
workflow executable-resource closure, current-manifest derivation, exact historical admission, and operational secret container. It
does not call a model, execute a Product API operation, drive a Session, persist progress, or own Research/Search facts.

## Workflow executable-resource closure V1

The closure is explicit in `onlyalpha_agent_orchestrator.closure`. Logical identities and exact packaged bytes, never absolute paths,
filesystem timestamps, import-discovery order, or ambient source trees, enter the existing ADR 0123 manifest authority.

Included resources:

- `onlyalpha.agent.orchestrator.__init__.py`: defines the independently packaged runtime's public assembly surface.
- `onlyalpha.agent.orchestrator.closure.py`: owns the reviewed declaration and package-resource loader, closing the declaration over itself.
- `onlyalpha.agent.orchestrator.runtime.py`: owns current-manifest assembly, historical admission, and secret isolation.
- `onlyalpha.application.product_command_receipt.py`: defines Product command identity used by Agent Tool occurrences.
- `onlyalpha.build_provenance.py`: exact-loads and validates the packaged source/distribution provenance bound by the manifest.
- `onlyalpha.canonical.py`: defines canonical serialization and fingerprints used by Agent identities.
- `onlyalpha.distribution.py`: defines the packaged provenance authority vocabulary consumed by the build-provenance reader.
- `onlyalpha.research.experiment.model.py`: defines exact Search identities consumed and produced by Agent translation/verification.
- `onlyalpha.research.agent.application.py`: performs deterministic Decision transformation, intent admission, and launch reconstruction.
- `onlyalpha.research.agent.authority_state.py`: defines the exact Search/Research authority views admitted by the reducer.
- `onlyalpha.research.agent.decision.py`: defines Agent Decisions, router actions, evidence observations, and launch identity.
- `onlyalpha.research.agent.decision_store.py`: enforces immutable Decision ordinals and launch lookup used for recovery.
- `onlyalpha.research.agent.errors.py`: defines the stable typed Agent failure carrier.
- `onlyalpha.research.agent.model.py`: defines Brief, Session, policy, resource, and workflow-manifest identities.
- `onlyalpha.research.agent.occurrence.py`: defines Model/Tool occurrence identity, validation, and recovery classification.
- `onlyalpha.research.agent.occurrence_service.py`: admits and validates Model/Tool Plans and Results before/after external I/O.
- `onlyalpha.research.agent.occurrence_store.py`: enforces occurrence uniqueness, ordinal continuity, and durable budget accounting.
- `onlyalpha.research.agent.semantic_translation.py`: translates Agent decisions into exact Product/Search semantics.
- `onlyalpha.research.agent.session_state.py`: reduces immutable facts into the next legal action or terminal outcome.
- `onlyalpha.research.agent.store.py`: exact-loads immutable resources and Session bindings and enforces put-once storage.
- `onlyalpha.research.agent.verification.py`: verifies Brief, Session, and orchestration-resource reference closure.
- `onlyalpha.research.agent.workflow.py`: owns the existing ADR 0123 manifest derivation and exact runtime admission primitive.

Intentionally excluded are Core package `__init__` re-export-only surfaces, `py.typed`, tests, documentation,
logging/metrics/UI/CLI formatting, HTTP/provider adapters, and unrelated Core/Search/Research implementations. None can change the
formal Agent workflow assembled by this package. Adding a future meaning-bearing runtime module requires an explicit closure change and
therefore changes the manifest.
