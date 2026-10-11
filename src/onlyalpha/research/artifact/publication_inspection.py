"""Current immutable-prefix inspection, not historical absence or execution permission."""

from __future__ import annotations

import errno
import fcntl
import os
from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager

from onlyalpha.research._durability import _OnlyBoundPublicationTree
from onlyalpha.research.artifact.calculation_v2_store import OnlyParquetResearchCalculationArtifactStoreV2
from onlyalpha.research.calculation.errors import OnlyResearchCalculationError, OnlyResearchCalculationResultStoreError
from onlyalpha.research.calculation.execution import OnlyResearchCalculationImplementationBinding
from onlyalpha.research.calculation.execution_evidence_v2 import (
    OnlyResearchCalculationExecutionEvidenceStoreV2,
    OnlyResearchCalculationExecutionEvidenceV2,
)
from onlyalpha.research.calculation.execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1
from onlyalpha.research.calculation.result_v2 import OnlyResearchCalculationResultV2
from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
from onlyalpha.research.result.errors import OnlyResearchResultStoreError
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.result.result import OnlyResearchResult
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore


def _require_bound_owners(trees: list[_OnlyBoundPublicationTree]) -> None:
    try:
        for tree in trees:
            tree.require_namespace()
    except (OSError, ValueError) as exc:
        code = (
            "RESEARCH_PUBLICATION_STORE_UNAVAILABLE"
            if isinstance(exc, OSError) and exc.errno not in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EISDIR}
            else "RESEARCH_PUBLICATION_CORRUPT"
        )
        raise OnlyResearchCalculationError(code, "owning publication binding changed") from exc


@contextmanager
def _only_inspect_calculation_publication_prefix(
    *,
    artifacts: OnlyParquetResearchCalculationArtifactStoreV2,
    results: OnlyJsonResearchResultStore,
    evidence: OnlyResearchCalculationExecutionEvidenceStoreV2,
    calculations: OnlyParquetResearchCalculationResultStoreV2,
    calculation_fingerprint: str,
    result_plan: OnlyResearchResultPlan,
    implementation_bindings: tuple[OnlyResearchCalculationImplementationBinding, ...],
    runtime_provenance: OnlyResearchRuntimeExecutionProvenanceV1,
) -> Iterator[
    tuple[
        OnlyResearchCalculationResultV2 | None,
        OnlyResearchCalculationExecutionEvidenceV2 | None,
        OnlyResearchResult | None,
    ]
]:
    """Inspect all related producers/plans before returning restrictive reuse refs.

    Four regular lock files must be preprovisioned. Aliased locks are deduplicated
    by retained FD inode; non-contiguous aliases would reverse the publication
    order and are refused before any lock acquisition. No Source/context issuance,
    numerical work, ACK or write is allowed inside this session.
    """
    if (
        results._readiness_result_store is not calculations
        or results._readiness_evidence_store is not evidence
        or evidence._result_store is not calculations
    ):
        raise OnlyResearchCalculationError(
            "RESEARCH_PUBLICATION_CORRUPT", "inspection owners do not share the configured live readers"
        )
    roots = (artifacts._root, results._root, evidence._semantic_root, calculations._root)
    with ExitStack() as owners:
        trees = []
        descriptors = []
        identities = []
        try:
            for root in roots:
                tree = owners.enter_context(closing(_OnlyBoundPublicationTree(root, root)))
                trees.append(tree)
                tree.bind_directory(root)
                descriptor = tree.bind_file(root / ".source-cut.lock")
                descriptors.append(descriptor)
                lock_stat = os.fstat(descriptor)
                identities.append((lock_stat.st_dev, lock_stat.st_ino))
            for identity in set(identities):
                positions = [index for index, value in enumerate(identities) if value == identity]
                if positions != list(range(positions[0], positions[-1] + 1)):
                    raise ValueError("non-contiguous publication lock alias creates an order cycle")
            acquired = set()
            for descriptor, identity in zip(descriptors, identities, strict=True):
                if identity not in acquired:
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                    owners.callback(fcntl.flock, descriptor, fcntl.LOCK_UN)
                    acquired.add(identity)
            for tree in trees:
                tree.require_namespace()
        except (OSError, ValueError) as exc:
            code = (
                "RESEARCH_PUBLICATION_STORE_UNAVAILABLE"
                if isinstance(exc, OSError) and exc.errno not in {errno.ENOTDIR, errno.ELOOP, errno.EISDIR}
                else "RESEARCH_PUBLICATION_CORRUPT"
            )
            raise OnlyResearchCalculationError(code, "owning publication lock admission failed") from exc

        with ExitStack() as selected:
            retained = selected.enter_context(artifacts._inspect_retained_bound(calculation_fingerprint, trees[0]))
            for artifact in retained:
                manifest = artifact.manifest
                live = selected.enter_context(
                    results.inspect_readiness_verified(manifest.result.research_result_plan_fingerprint)
                )
                if (
                    live.manifest.research_result_fingerprint != manifest.result.research_result_fingerprint
                    or live.manifest.plan != manifest.result.plan
                ):
                    raise OnlyResearchCalculationError(
                        "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "retained Artifact/live Result relation differs"
                    )
                for reference, producer in zip(manifest.calculations, manifest.selected_evidence, strict=True):
                    calculation = selected.enter_context(
                        calculations.inspect_verified(reference.calculation_fingerprint)
                    )
                    if (
                        calculation.manifest.calculation_result_fingerprint != reference.calculation_result_fingerprint
                        or calculation.manifest.calculation_graph != reference.calculation_graph
                        or calculation.manifest.dataset_snapshot_fingerprint != reference.dataset_snapshot_fingerprint
                    ):
                        raise OnlyResearchCalculationError(
                            "RESEARCH_EXECUTION_IDENTITY_MISMATCH",
                            "retained Artifact/live Calculation relation differs",
                        )
                    verified = selected.enter_context(evidence.inspect_verified(producer.evidence_fingerprint))
                    if verified != producer:
                        raise OnlyResearchCalculationError(
                            "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "retained Artifact/exact live producer differs"
                        )
            try:
                current_result = selected.enter_context(results.inspect_readiness_verified(result_plan.fingerprint))
            except OnlyResearchResultStoreError as exc:
                if exc.code != "RESEARCH_RESULT_NOT_FOUND":
                    raise
                current_result = None
            else:
                assert current_result is not None
                if current_result.manifest.plan != result_plan:
                    raise OnlyResearchCalculationError(
                        "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "current Result Plan differs"
                    )
            try:
                current_calculation = selected.enter_context(calculations.inspect_verified(calculation_fingerprint))
            except OnlyResearchCalculationResultStoreError as exc:
                if exc.code != "RESULT_NOT_FOUND":
                    raise
                for candidate in selected.enter_context(evidence._inspect_retained()):
                    if candidate.calculation_fingerprint == calculation_fingerprint:
                        raise OnlyResearchCalculationError(
                            "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "retained Evidence references missing Calculation"
                        ) from exc
                    selected.enter_context(evidence.inspect_verified(candidate.evidence_fingerprint))
                current_calculation = None
            current_evidence = None
            if current_calculation is not None:
                calculation_manifest = current_calculation.manifest
                exact = OnlyResearchCalculationExecutionEvidenceV2(
                    calculation_manifest.calculation_fingerprint,
                    calculation_manifest.dataset_snapshot_fingerprint,
                    calculation_manifest.calculation_graph_fingerprint,
                    calculation_manifest.calculation_result_fingerprint,
                    calculation_manifest.result_content_fingerprint,
                    implementation_bindings,
                    runtime_execution_provenance=runtime_provenance,
                )
                try:
                    current_evidence = selected.enter_context(evidence.inspect_verified(exact.evidence_fingerprint))
                except OnlyResearchCalculationError as exc:
                    if exc.code != "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND":
                        raise
                    for candidate in selected.enter_context(evidence._inspect_retained()):
                        verified = selected.enter_context(evidence.inspect_verified(candidate.evidence_fingerprint))
                        if (
                            verified.calculation_fingerprint == calculation_fingerprint
                            and verified.runtime_execution_provenance is None
                        ):
                            raise OnlyResearchCalculationError(
                                "RESEARCH_EXECUTION_IDENTITY_MISMATCH",
                                "relevant producer mandatory provenance is incomplete",
                            ) from exc
                else:
                    if current_evidence != exact:
                        raise OnlyResearchCalculationError(
                            "RESEARCH_EXECUTION_IDENTITY_MISMATCH", "current exact producer changed"
                        )
            _require_bound_owners(trees)
            yield current_calculation, current_evidence, current_result
            _require_bound_owners(trees)
        _require_bound_owners(trees)
