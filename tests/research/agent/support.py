from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.build_provenance import OnlyPackagedBuildProvenanceV1
from onlyalpha.distribution import OnlyArtifactSourceProvenanceAuthority
from onlyalpha.research.agent import (
    OnlyAgentBudgetV1,
    OnlyAgentDistributionProvenanceV1,
    OnlyAgentEvaluationContextReferenceV1,
    OnlyAgentModelExecutionPolicyPayloadV1,
    OnlyAgentModelSettingRuleV1,
    OnlyAgentModelSettingSupport,
    OnlyAgentOperationClassification,
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentPromptTemplatePayloadV1,
    OnlyAgentResearchBriefReferenceReadersV1,
    OnlyAgentResearchBriefV1,
    OnlyAgentRolePolicyPayloadV1,
    OnlyAgentSearchMethod,
    OnlyAgentSessionManifestV1,
    OnlyAgentStructuredHypothesisV1,
    OnlyAgentStructuredOutputSchemaPayloadV1,
    OnlyAgentToolClass,
    OnlyAgentToolOperationConstraintV1,
    OnlyAgentToolPolicyPayloadV1,
    OnlyAgentWorkflowExecutableResourceV1,
    OnlyAgentWorkflowImplementationManifestV1,
    OnlyAgentWorkflowResourceKind,
)

SOURCE_REVISION = "1" * 40


@dataclass(frozen=True)
class FingerprintValue:
    generation_fingerprint: str = ""
    snapshot_fingerprint: str = ""
    evaluation_kind: str = ""
    evaluation_schema_version: int = 1
    evaluation_fingerprint: str = ""

    @property
    def snapshot(self) -> FingerprintValue:
        return self


class PersistentExactReaders:
    def __init__(self, root: Path) -> None:
        self._path = root / "external-authorities.json"

    def initialize(self, *, catalog: str, dataset: str, evaluation: OnlyAgentEvaluationContextReferenceV1) -> None:
        self._path.write_text(
            json.dumps(
                {
                    "catalog": catalog,
                    "dataset": dataset,
                    "evaluation": evaluation.to_dict(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    def _load(self) -> dict[str, object]:
        value = json.loads(self._path.read_text(encoding="utf-8"))
        assert isinstance(value, dict)
        return value

    def generation(self, fingerprint: str) -> FingerprintValue:
        value = self._load()["catalog"]
        if value != fingerprint:
            raise LookupError(fingerprint)
        return FingerprintValue(generation_fingerprint=fingerprint)

    def load_verified_table(self, snapshot_fingerprint: str) -> FingerprintValue:
        value = self._load()["dataset"]
        if value != snapshot_fingerprint:
            raise LookupError(snapshot_fingerprint)
        return FingerprintValue(snapshot_fingerprint=snapshot_fingerprint)

    def load_evaluation_context_verified(self, reference: OnlyAgentEvaluationContextReferenceV1) -> FingerprintValue:
        value = self._load()["evaluation"]
        if value != reference.to_dict():
            raise LookupError(reference.evaluation_fingerprint)
        return FingerprintValue(
            evaluation_kind=reference.evaluation_kind,
            evaluation_schema_version=reference.evaluation_schema_version,
            evaluation_fingerprint=reference.evaluation_fingerprint,
        )


@dataclass(frozen=True)
class ContextFixture:
    resources: tuple[OnlyAgentOrchestrationResourceV1, ...]
    brief: OnlyAgentResearchBriefV1
    session: OnlyAgentSessionManifestV1
    readers: OnlyAgentResearchBriefReferenceReadersV1


def packaged_provenance(*, revision: str = SOURCE_REVISION, version: str = "0.9.9") -> OnlyPackagedBuildProvenanceV1:
    return OnlyPackagedBuildProvenanceV1(
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "OnlyAlpha",
        revision,
        "onlyalpha",
        version,
    )


def resource(kind: OnlyAgentOrchestrationResourceKind, payload: object) -> OnlyAgentOrchestrationResourceV1:
    return OnlyAgentOrchestrationResourceV1(kind, 1, "1.0.0", payload)  # type: ignore[arg-type]


def make_context(root: Path) -> ContextFixture:
    catalog = "a" * 64
    dataset = "b" * 64
    evaluation = OnlyAgentEvaluationContextReferenceV1("ONLYALPHA_RESEARCH_EVALUATION", 1, "c" * 64)
    exact_readers = PersistentExactReaders(root)
    exact_readers.initialize(catalog=catalog, dataset=dataset, evaluation=evaluation)
    readers = OnlyAgentResearchBriefReferenceReadersV1(exact_readers, exact_readers, exact_readers)

    prompt = resource(
        OnlyAgentOrchestrationResourceKind.PROMPT_TEMPLATE,
        OnlyAgentPromptTemplatePayloadV1(
            "ONLYALPHA_TEMPLATE",
            "1.0.0",
            "Hypothesis: {{ hypothesis }}",
            ("hypothesis",),
            "EXACT_DECLARED_VARIABLE_SUBSTITUTION",
        ),
    )
    schema = resource(
        OnlyAgentOrchestrationResourceKind.STRUCTURED_OUTPUT_SCHEMA,
        OnlyAgentStructuredOutputSchemaPayloadV1(
            "JSON_SCHEMA",
            "2020.12",
            {"additionalProperties": False, "required": ["action"], "type": "object"},
            "object",
            True,
            "EXACT_DECLARED_ENUMS",
            "EXACT_CONTEXT_IDENTITIES_ONLY",
        ),
    )
    model_policy = resource(
        OnlyAgentOrchestrationResourceKind.MODEL_EXECUTION_POLICY,
        OnlyAgentModelExecutionPolicyPayloadV1(
            (
                OnlyAgentModelSettingRuleV1(
                    "temperature",
                    OnlyAgentModelSettingSupport.REQUIRED,
                    "Explicit response-affecting value",
                ),
            ),
            "NO_AUTOMATIC_RETRY",
            True,
            "STRICT_STRUCTURED_OUTPUT_ONLY",
            ("api_key", "credentials", "secret_locator"),
        ),
    )
    allowed_tools = (
        OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
        OnlyAgentToolClass.RESEARCH_RUN_SUBMIT,
    )
    tool_policy = resource(
        OnlyAgentOrchestrationResourceKind.TOOL_POLICY,
        OnlyAgentToolPolicyPayloadV1(
            allowed_tools,
            (
                OnlyAgentToolOperationConstraintV1(
                    "catalog.exact-context.v1",
                    OnlyAgentToolClass.EXACT_CATALOG_CONTEXT_QUERY,
                    OnlyAgentOperationClassification.QUERY,
                    ("catalog_generation_fingerprint",),
                ),
            ),
            ("ARBITRARY_HTTP", "BROKER", "DIRECT_DATABASE", "GIT", "LIVE", "SHELL"),
        ),
    )
    role = resource(
        OnlyAgentOrchestrationResourceKind.ROLE_POLICY,
        OnlyAgentRolePolicyPayloadV1(
            "RESEARCH_PLANNER",
            "Plans research without owning scientific or execution facts",
            (prompt.resource_fingerprint,),
            (schema.resource_fingerprint,),
            (model_policy.resource_fingerprint,),
            allowed_tools,
            "ONE_EXACT_RESEARCH_BRIEF",
            "ONE_STRICT_RESEARCH_PLAN",
            "RETURN_OR_FAIL_CLOSED",
        ),
    )
    provenance = packaged_provenance()
    manifest = OnlyAgentWorkflowImplementationManifestV1(
        "ONLYALPHA_AGENT_V1",
        "1.0.0",
        provenance.source_revision,
        (
            OnlyAgentWorkflowExecutableResourceV1(
                "onlyalpha.agent.workflow",
                OnlyAgentWorkflowResourceKind.SOURCE,
                hashlib.sha256(b"def workflow(): return 'v1'\n").hexdigest(),
            ),
        ),
        (OnlyAgentDistributionProvenanceV1.from_packaged(provenance),),
    )
    workflow = resource(
        OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
        manifest,
    )
    resources = (prompt, schema, model_policy, tool_policy, role, workflow)
    brief = OnlyAgentResearchBriefV1(
        OnlyAgentStructuredHypothesisV1(
            "short_term_reversal",
            "Recent relative losers may mean-revert.",
            "Temporary liquidity pressure may reverse.",
            "Lower lagged returns associate with higher forward returns.",
            ("liquid instruments",),
            ("out-of-sample rank IC is non-positive",),
        ),
        catalog,
        dataset,
        evaluation,
        (OnlyAgentSearchMethod.REUSE_EXISTING,),
        OnlyAgentBudgetV1(2, 6),
    )
    session = OnlyAgentSessionManifestV1(
        brief.research_brief_fingerprint,
        manifest.workflow_id,
        manifest.workflow_semantic_version,
        manifest.implementation_fingerprint,
        manifest.source_revision,
        workflow.resource_fingerprint,
        tool_policy.resource_fingerprint,
        (role.resource_fingerprint,),
    )
    return ContextFixture(resources, brief, session, readers)
