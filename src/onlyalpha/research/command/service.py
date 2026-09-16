"""Idempotent submission and cancellation application service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from onlyalpha.application.product_command_authority import (
    OnlyProductCommandAdmissionAuthority,
    OnlyProductCommandAuthorityUnavailableError,
    OnlyProductCommandConflictError,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
    only_cancel_research_run_command_fingerprint,
)
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.research.evaluation.subject import (
    OnlyExactAuthoringGenerationReader,
    OnlyExactEvaluationIntentResolverV1,
    OnlyExactEvaluationIntentSubjectV1,
    OnlyResearchEvaluationSubjectSetV1,
)
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.run.errors import (
    OnlyResearchRunAdmissionError,
    OnlyResearchRunIntegrityError,
    OnlyResearchRunNotFoundError,
    OnlyResearchRunRevisionConflictError,
)
from onlyalpha.research.run.evidence import OnlyResearchAdmissionResolutionEvidence
from onlyalpha.research.run.generation import OnlyResearchRuntimeGenerationResolver
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId, OnlyResearchRunState
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .errors import (
    OnlyNoveltyResearchAdmissionError,
    OnlyResearchCancellationConflictError,
    OnlyResearchCommandConcurrencyError,
    OnlyResearchSubmissionConflictError,
)
from .model import (
    OnlyDerivedResearchSubmitCommandV2,
    OnlyNoveltyGatedResearchSubmitCommandV3,
    OnlyNoveltyGatedResearchSubmitCommandV4,
    OnlyResearchSubmitCommand,
    OnlyResearchSubmitDisposition,
    OnlyResearchSubmitOutcome,
    only_derived_research_run_id,
    only_novelty_gated_research_run_id,
    only_novelty_gated_research_run_id_v4,
)
from .novelty_admission import (
    OnlyResearchNoveltyAdmissionSubjectV1,
    OnlyResearchNoveltyAdmissionV1,
    OnlyResearchNoveltyAdmissionV2,
    only_novelty_same_subject_guard_key,
)
from .store import OnlyResearchCommandStore

if TYPE_CHECKING:
    from onlyalpha.research.memory.production import OnlyExperimentMemoryProductionBuilder
    from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
    from onlyalpha.research.novelty.decision import OnlyNoveltyDecisionGroupV1
    from onlyalpha.research.novelty.decision_store import OnlyNoveltyDecisionAuthority


class _AdmittedResolutionReader:
    """Internal exact reader over evidence already admitted by the Run authority."""

    def __init__(self, evidence: OnlyResearchAdmissionResolutionEvidence) -> None:
        self._evidence = evidence

    def resolve(self, _runtime: str, specification: OnlyResearchSpecification) -> object:
        if self._evidence.specification_fingerprint != specification.specification_fingerprint:
            raise OnlyResearchRunAdmissionError(
                "Admission evidence names another Specification",
                code="RESEARCH_ADMISSION_EVIDENCE_SPECIFICATION_MISMATCH",
            )
        return self._evidence


class OnlyResearchCommandService:
    def __init__(
        self,
        *,
        admission: OnlyResearchRunAdmissionService,
        store: OnlyResearchCommandStore,
        now_utc: Callable[[], datetime],
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        command_admissions: OnlyProductCommandAdmissionAuthority | None = None,
        runtime_generation_resolver: OnlyResearchRuntimeGenerationResolver | None = None,
        authoring_generation_reader: OnlyExactAuthoringGenerationReader | None = None,
        novelty_decisions: OnlyNoveltyDecisionAuthority | None = None,
        memory_builder: OnlyExperimentMemoryProductionBuilder | None = None,
        memory_revisions: OnlyExperimentMemoryRevisionStore | None = None,
        cancellation_cas_attempts: int = 3,
        allow_legacy_ungated: bool = False,
    ) -> None:
        if cancellation_cas_attempts < 1:
            raise ValueError("cancellation_cas_attempts must be positive")
        self._admission = admission
        self._store = store
        self._now_utc = now_utc
        self._runtime_generations = runtime_generations
        self._command_admissions = command_admissions
        self._runtime_generation_resolver = runtime_generation_resolver
        self._authoring_generation_reader = authoring_generation_reader
        self._novelty_decisions = novelty_decisions
        self._memory_builder = memory_builder
        self._memory_revisions = memory_revisions
        self._cancellation_cas_attempts = cancellation_cas_attempts
        if allow_legacy_ungated and any(
            item is not None for item in (novelty_decisions, memory_builder, memory_revisions)
        ):
            raise ValueError("legacy ungated mode cannot be combined with Read-to-Act authorities")
        self._allow_legacy_ungated = allow_legacy_ungated

    def submit_research_run(
        self,
        submission_key: OnlyProductCommandId,
        specification: OnlyResearchSpecification,
        provenance: OnlyResearchAuthoringProvenance | None = None,
        *,
        parent_runtime_work_id: str | None = None,
    ) -> OnlyResearchSubmitOutcome:
        strict = OnlyResearchSpecification.from_dict(specification.to_dict())
        if self._allow_legacy_ungated:
            return self._submit_legacy(submission_key, strict, provenance, parent_runtime_work_id)
        legacy: OnlyResearchSubmitCommand | OnlyDerivedResearchSubmitCommandV2
        if parent_runtime_work_id is None:
            legacy = OnlyResearchSubmitCommand(submission_key, strict, provenance)
        else:
            legacy = OnlyDerivedResearchSubmitCommandV2(
                submission_key,
                strict,
                parent_runtime_work_id,
                provenance,
            )
        existing = self._store.find_product_command_receipt(submission_key)
        if existing is not None:
            if existing.command_fingerprint == legacy.command_fingerprint:
                expected = only_derived_research_run_id(submission_key) if parent_runtime_work_id else None
                run = self._replay_receipt(
                    existing,
                    kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
                    fingerprint=legacy.command_fingerprint,
                    expected_run_id=expected,
                )
                self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
                return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.REUSED, run)
            return self._replay_novelty_receipt(existing, strict, provenance, parent_runtime_work_id)

        decisions, builder, revisions = self._require_novelty_authorities()
        from onlyalpha.research.memory.query import (
            OnlyExactEvaluationIntentHistorySelectorV1,
            OnlyMemoryHistoricalProofStatus,
            OnlyMemoryHistoricalQueryV1,
            only_query_experiment_memory_history,
        )
        from onlyalpha.research.novelty.decision import (
            OnlyNoveltyDecisionBundleV2,
            OnlyNoveltyDecisionError,
            OnlyNoveltyDecisionSchemaUnsupportedError,
            OnlyNoveltyProofRole,
        )
        from onlyalpha.research.novelty.decision_store import OnlyNoveltyDecisionNotFoundError
        from onlyalpha.research.novelty.model import OnlyNoveltyPolicyOutcome

        try:
            group = decisions.load_group_exact(submission_key)
        except OnlyNoveltyDecisionNotFoundError:
            pass
        except OnlyNoveltyDecisionSchemaUnsupportedError as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_DECISION_SCHEMA_UNSUPPORTED", "Novelty Decision Group schema is unsupported"
            ) from exc
        except OnlyNoveltyDecisionError as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "Novelty Decision Group failed strict verification"
            ) from exc
        else:
            return self._submit_novelty_group(
                submission_key,
                strict,
                provenance,
                parent_runtime_work_id,
                group,
                builder,
                revisions,
            )

        try:
            bundle = decisions.load_exact(submission_key)
        except OnlyNoveltyDecisionNotFoundError as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_DECISION_NOT_FOUND", "an exact Novelty Decision V2 is required"
            ) from exc
        except OnlyNoveltyDecisionSchemaUnsupportedError as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_DECISION_SCHEMA_UNSUPPORTED", "Novelty Decision schema is unsupported"
            ) from exc
        except OnlyNoveltyDecisionError as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "Novelty Decision failed strict verification"
            ) from exc
        if not isinstance(bundle, OnlyNoveltyDecisionBundleV2):
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_DECISION_SCHEMA_UNSUPPORTED", "Novelty Decision V2 is required for prospective action"
            )
        decision = bundle.decision
        if decision.outcome is not OnlyNoveltyPolicyOutcome.ADMIT:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_DECISION_NOT_ADMIT", f"Novelty Decision outcome is {decision.outcome.value}"
            )
        if decision.subject.product_command_id != submission_key.value:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_DECISION_BINDING_MISMATCH", "Novelty Decision names another Product Command"
            )
        try:
            decision_subject = OnlyExactEvaluationIntentSubjectV1.from_dict(
                decision.subject.resolved_subject["evaluation_subject"]  # type: ignore[arg-type]
            )
        except Exception as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "Novelty Decision has no valid canonical Evaluation Subject"
            ) from exc
        command = OnlyNoveltyGatedResearchSubmitCommandV3(
            submission_key,
            strict,
            decision.decision_fingerprint,
            parent_runtime_work_id,
            provenance,
        )
        self._admit_gated_command(command)
        expected_run_id = only_novelty_gated_research_run_id(submission_key)
        bound = False
        try:
            binding = self._bind_exact_v3(
                expected_run_id,
                decision_subject.runtime_generation_fingerprint,
                parent_runtime_work_id,
            )
            bound = True
            if not bool(getattr(binding, "active", False)):
                raise OnlyNoveltyResearchAdmissionError(
                    "RUNTIME_WORK_BINDING_RECOVERY_REQUIRED",
                    "the deterministic Runtime Work Binding was previously released",
                )
            if self._runtime_generation_resolver is None:
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_PROOF_UNAVAILABLE", "exact Runtime generation resolution is unavailable"
                )
            evidence = self._runtime_generation_resolver.resolve(
                decision_subject.runtime_generation_fingerprint, strict
            )
            if not isinstance(evidence, OnlyResearchAdmissionResolutionEvidence):
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_PROOF_UNAVAILABLE", "exact Runtime generation evidence is invalid"
                )
            prepared = self._admission.prepare(
                strict,
                provenance=provenance,
                exact_run_id=expected_run_id,
                exact_admission_evidence=evidence,
            )
            actual_subject = OnlyExactEvaluationIntentResolverV1(
                runtime_generations=self._runtime_generations,
                runtime_resolution=_AdmittedResolutionReader(evidence),
                authoring_generations=self._authoring_generation_reader,
            ).resolve(
                strict,
                runtime_work_id=prepared.run_id.value,
                authoring_provenance=provenance,
            )
            if actual_subject != decision_subject:
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_DECISION_BINDING_MISMATCH",
                    "actual Research intent resolves to another canonical Evaluation Subject",
                )
            manifest = builder.capture_manifest()
            projection = builder.publish_and_activate(manifest)
            current_query = OnlyMemoryHistoricalQueryV1(
                projection.revision_fingerprint,
                OnlyExactEvaluationIntentHistorySelectorV1(actual_subject),
            )
            current_proof = only_query_experiment_memory_history(revisions, current_query)
            decision_proof = next(
                (item for item in bundle.witness.proofs if item.role is OnlyNoveltyProofRole.EVALUATION),
                None,
            )
            if decision_proof is None:
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_READ_TO_ACT_CORRUPT", "Decision-time evaluation proof is missing"
                )
            frozen = decision_proof.proof
            if current_proof.proof_status not in {
                OnlyMemoryHistoricalProofStatus.MATCH,
                OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH,
            }:
                code = (
                    "NOVELTY_PROOF_INCOMPLETE"
                    if current_proof.proof_status is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
                    else "NOVELTY_PROOF_UNAVAILABLE"
                )
                raise OnlyNoveltyResearchAdmissionError(code, "action-time historical proof is not complete")
            if current_proof.proof_status.value != frozen.get("proof_status") or [
                item.to_dict() for item in current_proof.ordered_matches
            ] != frozen.get("ordered_matches"):
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_DECISION_STALE", "material exact historical proof changed after Decision time"
                )
            expected_frontier = self._postgres_frontier(manifest)
            guard = only_novelty_same_subject_guard_key(actual_subject.subject_fingerprint)
            admission = OnlyResearchNoveltyAdmissionV1(
                submission_key,
                command.command_fingerprint,
                decision.decision_fingerprint,
                decision.subject.canonical_intent_fingerprint,
                actual_subject.subject_fingerprint,
                decision_proof.result_fingerprint,
                current_proof.result_fingerprint,
                manifest.manifest_fingerprint,
                guard,
                prepared.run_id.value,
                prepared.run_id,
            )
            requested = OnlyProductCommandReceipt(
                command_id=submission_key,
                command_kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
                command_fingerprint=command.command_fingerprint,
                outcome_ref=OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind.RESEARCH_RUN,
                    prepared.run_id.value,
                ),
                accepted_at=prepared.queued_at,
            )
            record = self._store.create_queued_with_novelty_admission(
                prepared,
                requested,
                admission,
                expected_source_frontier=expected_frontier,
            )
        except Exception:
            accepted = self._store.find_product_command_receipt(submission_key)
            if accepted is not None and accepted.command_fingerprint == command.command_fingerprint:
                return self._replay_novelty_receipt(accepted, strict, provenance, parent_runtime_work_id)
            if bound:
                self._runtime_generations.release_work(
                    expected_run_id.value,
                    actor="research-novelty-admission-compensation",
                    occurred_at=self._now_utc(),
                )
            raise
        run = self._replay_receipt(
            record,
            kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint=command.command_fingerprint,
            expected_run_id=prepared.run_id,
        )
        self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
        return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.CREATED, run)

    def _submit_novelty_group(
        self,
        submission_key: OnlyProductCommandId,
        strict: OnlyResearchSpecification,
        provenance: OnlyResearchAuthoringProvenance | None,
        parent_runtime_work_id: str | None,
        group: OnlyNoveltyDecisionGroupV1,
        builder: OnlyExperimentMemoryProductionBuilder,
        revisions: OnlyExperimentMemoryRevisionStore,
    ) -> OnlyResearchSubmitOutcome:
        from onlyalpha.research.memory.query import (
            OnlyExactEvaluationIntentHistorySelectorV1,
            OnlyMemoryHistoricalProofStatus,
            OnlyMemoryHistoricalQueryV1,
            only_query_experiment_memory_history,
        )
        from onlyalpha.research.novelty.decision import (
            OnlyNoveltyDecisionGroupDisposition,
            OnlyNoveltyProofRole,
        )

        if (
            group.product_command_id != submission_key.value
            or group.specification_fingerprint != strict.specification_fingerprint
        ):
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_DECISION_BINDING_MISMATCH", "Decision Group names another Product Command or Specification"
            )
        if group.disposition is not OnlyNoveltyDecisionGroupDisposition.ACTIONABLE:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_DECISION_NOT_ADMIT", "every Decision Group member must be ADMIT"
            )
        generations = {item.runtime_generation_fingerprint for item in group.subject_set.subjects}
        if len(generations) != 1:
            raise OnlyNoveltyResearchAdmissionError(
                "RUNTIME_WORK_BINDING_CONFLICT", "Decision Group members require incompatible Runtime Generations"
            )
        generation = generations.pop()
        command = OnlyNoveltyGatedResearchSubmitCommandV4(
            submission_key,
            strict,
            group.group_fingerprint,
            parent_runtime_work_id,
            provenance,
        )
        self._admit_gated_command(command)
        expected_run_id = only_novelty_gated_research_run_id_v4(submission_key)
        bound = False
        try:
            binding = self._bind_exact_v3(expected_run_id, generation, parent_runtime_work_id)
            bound = True
            if not bool(getattr(binding, "active", False)):
                raise OnlyNoveltyResearchAdmissionError(
                    "RUNTIME_WORK_BINDING_RECOVERY_REQUIRED",
                    "the deterministic Runtime Work Binding was previously released",
                )
            if self._runtime_generation_resolver is None:
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_PROOF_UNAVAILABLE", "exact Runtime generation resolution is unavailable"
                )
            evidence = self._runtime_generation_resolver.resolve(generation, strict)
            if not isinstance(evidence, OnlyResearchAdmissionResolutionEvidence):
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_PROOF_UNAVAILABLE", "exact Runtime generation evidence is invalid"
                )
            prepared = self._admission.prepare(
                strict,
                provenance=provenance,
                exact_run_id=expected_run_id,
                exact_admission_evidence=evidence,
            )
            actual_set = OnlyResearchEvaluationSubjectSetV1.from_subjects(
                OnlyExactEvaluationIntentResolverV1(
                    runtime_generations=self._runtime_generations,
                    runtime_resolution=_AdmittedResolutionReader(evidence),
                    authoring_generations=self._authoring_generation_reader,
                ).resolve_all(
                    strict,
                    runtime_work_id=prepared.run_id.value,
                    authoring_provenance=provenance,
                )
            )
            if actual_set != group.subject_set:
                raise OnlyNoveltyResearchAdmissionError(
                    "NOVELTY_DECISION_BINDING_MISMATCH",
                    "actual Research intent resolves to another canonical Evaluation Subject Set",
                )
            manifest = builder.capture_manifest()
            projection = builder.publish_and_activate(manifest)
            members: list[OnlyResearchNoveltyAdmissionSubjectV1] = []
            for ordinal, (subject, bundle) in enumerate(zip(actual_set.subjects, group.members, strict=True)):
                decision_proof = next(
                    (item for item in bundle.witness.proofs if item.role is OnlyNoveltyProofRole.EVALUATION),
                    None,
                )
                if decision_proof is None:
                    raise OnlyNoveltyResearchAdmissionError(
                        "NOVELTY_READ_TO_ACT_CORRUPT", "Decision-time evaluation proof is missing"
                    )
                current_proof = only_query_experiment_memory_history(
                    revisions,
                    OnlyMemoryHistoricalQueryV1(
                        projection.revision_fingerprint,
                        OnlyExactEvaluationIntentHistorySelectorV1(subject),
                    ),
                )
                if current_proof.proof_status not in {
                    OnlyMemoryHistoricalProofStatus.MATCH,
                    OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH,
                }:
                    code = (
                        "NOVELTY_PROOF_INCOMPLETE"
                        if current_proof.proof_status is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
                        else "NOVELTY_PROOF_UNAVAILABLE"
                    )
                    raise OnlyNoveltyResearchAdmissionError(code, "action-time historical proof is not complete")
                frozen = decision_proof.proof
                if current_proof.proof_status.value != frozen.get("proof_status") or [
                    item.to_dict() for item in current_proof.ordered_matches
                ] != frozen.get("ordered_matches"):
                    raise OnlyNoveltyResearchAdmissionError(
                        "NOVELTY_DECISION_STALE", "material exact historical proof changed after Decision time"
                    )
                members.append(
                    OnlyResearchNoveltyAdmissionSubjectV1(
                        ordinal,
                        subject.subject_fingerprint,
                        bundle.decision.decision_fingerprint,
                        bundle.decision.subject.canonical_intent_fingerprint,
                        decision_proof.result_fingerprint,
                        current_proof.result_fingerprint,
                        only_novelty_same_subject_guard_key(subject.subject_fingerprint),
                    )
                )
            expected_frontier = self._postgres_frontier(manifest)
            admission = OnlyResearchNoveltyAdmissionV2(
                submission_key,
                command.command_fingerprint,
                group.group_fingerprint,
                actual_set.subject_set_fingerprint,
                manifest.manifest_fingerprint,
                prepared.run_id.value,
                prepared.run_id,
                tuple(members),
            )
            requested = OnlyProductCommandReceipt(
                command_id=submission_key,
                command_kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
                command_fingerprint=command.command_fingerprint,
                outcome_ref=OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind.RESEARCH_RUN,
                    prepared.run_id.value,
                ),
                accepted_at=prepared.queued_at,
            )
            record = self._store.create_queued_with_novelty_admission(
                prepared,
                requested,
                admission,
                expected_source_frontier=expected_frontier,
            )
        except Exception:
            accepted = self._store.find_product_command_receipt(submission_key)
            if accepted is not None and accepted.command_fingerprint == command.command_fingerprint:
                return self._replay_novelty_receipt(accepted, strict, provenance, parent_runtime_work_id)
            if bound:
                self._runtime_generations.release_work(
                    expected_run_id.value,
                    actor="research-novelty-admission-compensation",
                    occurred_at=self._now_utc(),
                )
            raise
        run = self._replay_receipt(
            record,
            kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint=command.command_fingerprint,
            expected_run_id=prepared.run_id,
        )
        self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
        return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.CREATED, run)

    def _submit_legacy(
        self,
        submission_key: OnlyProductCommandId,
        strict: OnlyResearchSpecification,
        provenance: OnlyResearchAuthoringProvenance | None,
        parent_runtime_work_id: str | None,
    ) -> OnlyResearchSubmitOutcome:
        command: OnlyResearchSubmitCommand | OnlyDerivedResearchSubmitCommandV2
        expected_run_id: OnlyResearchRunId | None = None
        if parent_runtime_work_id is None:
            command = OnlyResearchSubmitCommand(submission_key, strict, provenance)
        else:
            command = OnlyDerivedResearchSubmitCommandV2(submission_key, strict, parent_runtime_work_id, provenance)
            expected_run_id = only_derived_research_run_id(submission_key)
            self._admit_derived_command(command)
        existing = self._store.find_product_command_receipt(submission_key)
        if existing is not None:
            run = self._replay_receipt(
                existing,
                kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
                fingerprint=command.command_fingerprint,
                expected_run_id=expected_run_id,
            )
            self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
            return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.REUSED, run)
        if parent_runtime_work_id is None:
            if strict.schema_version == 2:
                prepared, evidence = self._admission.prepare_with_evidence(strict, provenance=provenance)
            else:
                prepared = self._admission.prepare(strict, provenance=provenance)
                evidence = None
            self._runtime_generations.bind_new_work(
                prepared.run_id.value,
                actor="research-product-admission",
                occurred_at=prepared.queued_at,
            )
        else:
            assert expected_run_id is not None
            parent = self._runtime_generations.require_work_binding(parent_runtime_work_id)
            generation = getattr(parent, "runtime_generation_fingerprint", None)
            if not isinstance(generation, str):
                raise OnlyResearchRunAdmissionError(
                    "Parent Runtime binding has no exact generation",
                    code="RESEARCH_RUNTIME_GENERATION_RESOLUTION_MISMATCH",
                )
            if self._runtime_generation_resolver is None:
                raise OnlyResearchRunAdmissionError(
                    "Exact Runtime generation admission resolver is unavailable",
                    code="RESEARCH_RUNTIME_GENERATION_RESOLUTION_UNAVAILABLE",
                )
            evidence = self._runtime_generation_resolver.resolve(generation, strict)
            if not isinstance(evidence, OnlyResearchAdmissionResolutionEvidence):
                raise OnlyResearchRunAdmissionError(
                    "Exact generation resolver did not return admission evidence",
                    code="RESEARCH_ADMISSION_EVIDENCE_INVALID",
                )
            prepared = self._admission.prepare(
                strict,
                provenance=provenance,
                exact_run_id=expected_run_id,
                exact_admission_evidence=evidence,
            )
            self._runtime_generations.bind_derived_work(
                parent_runtime_work_id,
                prepared.run_id.value,
                actor="research-product-derived-admission",
                occurred_at=prepared.queued_at,
            )
        requested = OnlyProductCommandReceipt(
            command_id=submission_key,
            command_kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command_fingerprint=command.command_fingerprint,
            outcome_ref=OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, prepared.run_id.value),
            accepted_at=prepared.queued_at,
        )
        try:
            if strict.schema_version == 2:
                if evidence is None:
                    raise OnlyResearchRunAdmissionError(
                        "Canonical Evaluation Subject evidence is unavailable",
                        code="EVALUATION_SUBJECT_AUTHORITY_CORRUPT",
                    )
                OnlyExactEvaluationIntentResolverV1(
                    runtime_generations=self._runtime_generations,
                    runtime_resolution=_AdmittedResolutionReader(evidence),
                    authoring_generations=self._authoring_generation_reader,
                ).resolve_all(
                    strict,
                    runtime_work_id=prepared.run_id.value,
                    authoring_provenance=provenance,
                )
            record = self._store.create_queued_with_receipt(prepared, requested)
        except Exception:
            if parent_runtime_work_id is None:
                self._runtime_generations.release_work(
                    prepared.run_id.value,
                    actor="research-product-admission-compensation",
                    occurred_at=self._now_utc(),
                )
            raise
        run = self._replay_receipt(
            record,
            kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint=command.command_fingerprint,
            expected_run_id=expected_run_id,
        )
        if run.run_id != prepared.run_id and parent_runtime_work_id is None:
            self._runtime_generations.release_work(
                prepared.run_id.value,
                actor="research-product-admission-concurrency-loser",
                occurred_at=self._now_utc(),
            )
        self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
        disposition = (
            OnlyResearchSubmitDisposition.CREATED
            if record.outcome_ref.outcome_id == prepared.run_id.value
            else OnlyResearchSubmitDisposition.REUSED
        )
        return OnlyResearchSubmitOutcome(disposition, run)

    def _require_novelty_authorities(
        self,
    ) -> tuple[
        OnlyNoveltyDecisionAuthority,
        OnlyExperimentMemoryProductionBuilder,
        OnlyExperimentMemoryRevisionStore,
    ]:
        if self._novelty_decisions is None or self._memory_builder is None or self._memory_revisions is None:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_RESEARCH_ADMISSION_REQUIRED", "Read-to-Act authorities are unavailable"
            )
        return self._novelty_decisions, self._memory_builder, self._memory_revisions

    def _admit_gated_command(
        self, command: OnlyNoveltyGatedResearchSubmitCommandV3 | OnlyNoveltyGatedResearchSubmitCommandV4
    ) -> None:
        authority = self._command_admissions
        if authority is None:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_RESEARCH_ADMISSION_REQUIRED", "Product Command Admission Authority is unavailable"
            )
        requested = OnlyProductCommandAdmissionV1(
            command.submission_key,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command.command_fingerprint,
        )
        try:
            authority.admit_exact(requested)
            if authority.load_admission(command.submission_key) != requested:
                raise OnlyResearchSubmissionConflictError()
        except OnlyProductCommandConflictError as exc:
            raise OnlyResearchSubmissionConflictError() from exc
        except OnlyProductCommandAuthorityUnavailableError as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_RESEARCH_ADMISSION_REQUIRED", "Product Command Admission Authority is unavailable"
            ) from exc

    def _bind_exact_v3(
        self,
        run_id: OnlyResearchRunId,
        generation: str,
        parent_runtime_work_id: str | None,
    ) -> object:
        if parent_runtime_work_id is None:
            self._runtime_generations.require_new_work_generation(generation)
            return self._runtime_generations.bind_work_exact(
                run_id.value,
                generation,
                actor="research-novelty-admission",
                occurred_at=self._now_utc(),
            )
        parent = self._runtime_generations.require_work_binding(parent_runtime_work_id)
        if getattr(parent, "runtime_generation_fingerprint", None) != generation:
            raise OnlyNoveltyResearchAdmissionError(
                "RUNTIME_WORK_BINDING_CONFLICT", "parent work uses another Runtime Generation"
            )
        return self._runtime_generations.bind_derived_work(
            parent_runtime_work_id,
            run_id.value,
            actor="research-novelty-derived-admission",
            occurred_at=self._now_utc(),
        )

    @staticmethod
    def _postgres_frontier(manifest: object) -> int:
        cuts = getattr(manifest, "cuts", ())
        boundaries = {
            item.cut_boundary
            for item in cuts
            if item.source_family
            in {
                "RESEARCH_RUN",
                "RESEARCH_ATTEMPT",
                "PRODUCT_COMMAND_ADMISSION",
                "PRODUCT_COMMAND_RECEIPT",
            }
        }
        if len(boundaries) != 1:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_PROOF_UNAVAILABLE", "PostgreSQL source cuts do not share one closed frontier"
            )
        boundary = boundaries.pop()
        prefix = "JOURNAL_INDEX:"
        if not boundary.startswith(prefix) or not boundary[len(prefix) :].isdigit():
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_PROOF_UNAVAILABLE", "PostgreSQL source frontier is unsupported"
            )
        return int(boundary[len(prefix) :])

    def _replay_novelty_receipt(
        self,
        receipt: OnlyProductCommandReceipt,
        specification: OnlyResearchSpecification,
        provenance: OnlyResearchAuthoringProvenance | None,
        parent_runtime_work_id: str | None,
    ) -> OnlyResearchSubmitOutcome:
        from onlyalpha.research.novelty.decision import OnlyNoveltyDecisionBundleV2, OnlyNoveltyProofRole

        admission = self._store.load_novelty_admission(receipt.command_id)
        if admission is None:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "V3 Product Receipt has no Read-to-Act Admission"
            )
        if isinstance(admission, OnlyResearchNoveltyAdmissionV2):
            return self._replay_novelty_group_receipt(
                receipt, admission, specification, provenance, parent_runtime_work_id
            )
        if not isinstance(admission, OnlyResearchNoveltyAdmissionV1):
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "Read-to-Act Admission schema is unsupported"
            )
        decisions, _, _ = self._require_novelty_authorities()
        bundle = decisions.load_exact(receipt.command_id)
        if not isinstance(bundle, OnlyNoveltyDecisionBundleV2):
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "V3 Product Receipt names no Decision V2"
            )
        command = OnlyNoveltyGatedResearchSubmitCommandV3(
            receipt.command_id,
            specification,
            bundle.decision.decision_fingerprint,
            parent_runtime_work_id,
            provenance,
        )
        expected_run_id = only_novelty_gated_research_run_id(receipt.command_id)
        try:
            subject = OnlyExactEvaluationIntentSubjectV1.from_dict(
                bundle.decision.subject.resolved_subject["evaluation_subject"]  # type: ignore[arg-type]
            )
            decision_proof = next(
                item for item in bundle.witness.proofs if item.role is OnlyNoveltyProofRole.EVALUATION
            )
        except Exception as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "accepted Decision/Admission relation is incomplete"
            ) from exc
        if (
            admission.command_fingerprint != command.command_fingerprint
            or admission.novelty_decision_fingerprint != bundle.decision.decision_fingerprint
            or admission.canonical_intent_fingerprint != bundle.decision.subject.canonical_intent_fingerprint
            or admission.evaluation_subject_fingerprint != subject.subject_fingerprint
            or admission.decision_time_proof_fingerprint != decision_proof.result_fingerprint
            or admission.same_subject_guard_key != only_novelty_same_subject_guard_key(subject.subject_fingerprint)
            or admission.run_id != expected_run_id
            or admission.runtime_work_id != expected_run_id.value
        ):
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "accepted Decision/Admission relation is inconsistent"
            )
        run = self._replay_receipt(
            receipt,
            kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint=command.command_fingerprint,
            expected_run_id=expected_run_id,
        )
        self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
        return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.REUSED, run)

    def _replay_novelty_group_receipt(
        self,
        receipt: OnlyProductCommandReceipt,
        admission: OnlyResearchNoveltyAdmissionV2,
        specification: OnlyResearchSpecification,
        provenance: OnlyResearchAuthoringProvenance | None,
        parent_runtime_work_id: str | None,
    ) -> OnlyResearchSubmitOutcome:
        from onlyalpha.research.novelty.decision import OnlyNoveltyProofRole

        decisions, _, _ = self._require_novelty_authorities()
        try:
            group = decisions.load_group_exact(receipt.command_id)
        except Exception as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "V4 Product Receipt names no valid Decision Group"
            ) from exc
        command = OnlyNoveltyGatedResearchSubmitCommandV4(
            receipt.command_id,
            specification,
            group.group_fingerprint,
            parent_runtime_work_id,
            provenance,
        )
        expected_run_id = only_novelty_gated_research_run_id_v4(receipt.command_id)
        try:
            expected_members = tuple(
                (
                    subject.subject_fingerprint,
                    bundle.decision.decision_fingerprint,
                    bundle.decision.subject.canonical_intent_fingerprint,
                    next(
                        item for item in bundle.witness.proofs if item.role is OnlyNoveltyProofRole.EVALUATION
                    ).result_fingerprint,
                )
                for subject, bundle in zip(group.subject_set.subjects, group.members, strict=True)
            )
        except Exception as exc:
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "accepted Decision Group relation is incomplete"
            ) from exc
        actual_members = tuple(
            (
                item.evaluation_subject_fingerprint,
                item.novelty_decision_fingerprint,
                item.canonical_intent_fingerprint,
                item.decision_time_proof_fingerprint,
            )
            for item in admission.members
        )
        if (
            admission.command_fingerprint != command.command_fingerprint
            or admission.decision_group_fingerprint != group.group_fingerprint
            or admission.subject_set_fingerprint != group.subject_set.subject_set_fingerprint
            or actual_members != expected_members
            or admission.run_id != expected_run_id
            or admission.runtime_work_id != expected_run_id.value
        ):
            raise OnlyNoveltyResearchAdmissionError(
                "NOVELTY_READ_TO_ACT_CORRUPT", "accepted Decision Group/Admission relation is inconsistent"
            )
        run = self._replay_receipt(
            receipt,
            kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint=command.command_fingerprint,
            expected_run_id=expected_run_id,
        )
        self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
        return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.REUSED, run)

    def _require_expected_binding(self, run_id: str, parent_runtime_work_id: str | None) -> None:
        child = self._runtime_generations.require_work_binding(run_id)
        if parent_runtime_work_id is None:
            return
        parent = self._runtime_generations.require_work_binding(parent_runtime_work_id)
        if getattr(parent, "runtime_generation_fingerprint", None) != getattr(
            child, "runtime_generation_fingerprint", None
        ):
            raise ValueError("RUNTIME_DERIVED_WORK_GENERATION_BINDING_CONFLICT")

    def _admit_derived_command(self, command: OnlyDerivedResearchSubmitCommandV2) -> None:
        authority = self._command_admissions
        if authority is None:
            raise OnlyResearchRunIntegrityError("Derived Research Product Admission Authority is unavailable")
        requested = OnlyProductCommandAdmissionV1(
            command.submission_key,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command.command_fingerprint,
        )
        try:
            authority.admit_exact(requested)
            actual = authority.load_admission(command.submission_key)
        except OnlyProductCommandConflictError as exc:
            raise OnlyResearchSubmissionConflictError() from exc
        except OnlyProductCommandAuthorityUnavailableError as exc:
            raise OnlyResearchRunIntegrityError("Derived Research Product Admission Authority is unavailable") from exc
        if actual != requested:
            raise OnlyResearchSubmissionConflictError()

    def request_research_run_cancellation(
        self,
        run_id: OnlyResearchRunId,
        command_id: OnlyProductCommandId | None = None,
    ) -> OnlyResearchRun:
        if command_id is not None:
            fingerprint = only_cancel_research_run_command_fingerprint(run_id.value)
            existing = self._store.find_product_command_receipt(command_id)
            if existing is not None:
                return self._release_if_terminal(
                    self._replay_receipt(
                        existing,
                        kind=OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
                        fingerprint=fingerprint,
                        expected_run_id=run_id,
                    )
                )
            accepted_at = self._now_utc()
            receipt = OnlyProductCommandReceipt(
                command_id=command_id,
                command_kind=OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
                command_fingerprint=fingerprint,
                outcome_ref=OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind.RESEARCH_RUN,
                    run_id.value,
                ),
                accepted_at=accepted_at,
            )
            actual = self._store.request_cancellation_with_receipt(run_id, receipt)
            return self._release_if_terminal(
                self._replay_receipt(
                    actual,
                    kind=OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
                    fingerprint=fingerprint,
                    expected_run_id=run_id,
                )
            )
        for _ in range(self._cancellation_cas_attempts):
            current = self._store.load(run_id)
            if current.state in {OnlyResearchRunState.CANCEL_REQUESTED, OnlyResearchRunState.CANCELLED}:
                return self._release_if_terminal(current)
            if current.state in {OnlyResearchRunState.COMPLETED, OnlyResearchRunState.FAILED}:
                raise OnlyResearchCancellationConflictError()
            target = (
                OnlyResearchRunState.CANCELLED
                if current.state is OnlyResearchRunState.QUEUED
                else OnlyResearchRunState.CANCEL_REQUESTED
            )
            transitioned = current.transition(target, at=self._now_utc())
            try:
                return self._release_if_terminal(self._store.commit_transition(current, transitioned))
            except OnlyResearchRunRevisionConflictError:
                continue
        raise OnlyResearchCommandConcurrencyError()

    def _release_if_terminal(self, run: OnlyResearchRun) -> OnlyResearchRun:
        if run.state in {
            OnlyResearchRunState.COMPLETED,
            OnlyResearchRunState.FAILED,
            OnlyResearchRunState.CANCELLED,
        }:
            self._runtime_generations.release_work(
                run.run_id.value,
                actor="research-product-terminal-command",
                occurred_at=run.finished_at or self._now_utc(),
            )
        return run

    def _replay_receipt(
        self,
        receipt: OnlyProductCommandReceipt,
        *,
        kind: OnlyProductCommandKind,
        fingerprint: str,
        expected_run_id: OnlyResearchRunId | None = None,
    ) -> OnlyResearchRun:
        if receipt.command_kind is not kind or receipt.command_fingerprint != fingerprint:
            raise OnlyResearchSubmissionConflictError()
        if receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN:
            raise OnlyResearchRunIntegrityError("Product Command Receipt outcome kind is incompatible")
        run_id = OnlyResearchRunId(receipt.outcome_ref.outcome_id)
        if expected_run_id is not None and run_id != expected_run_id:
            raise OnlyResearchSubmissionConflictError()
        try:
            return self._store.load(run_id)
        except OnlyResearchRunNotFoundError as exc:
            raise OnlyResearchRunIntegrityError("Product Command Receipt points to a missing Research Run") from exc


__all__ = ["OnlyResearchCommandService"]
