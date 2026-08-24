from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationRegistry,
    only_implementation_manifest_from_bytes,
)
from onlyalpha.strategy import (
    OnlyCalculationEquivalenceCorpus,
    OnlyCalculationEquivalenceError,
    OnlyCalculationEquivalenceEvidenceStore,
    OnlyCalculationEquivalenceExecution,
    OnlyCalculationEquivalenceRow,
    OnlyCalculationEquivalenceVerifier,
)
from tests.strategy.p9_support import p9_strategy_case


class _Runner:
    def __init__(self, value: object = Decimal("1.000000000000")) -> None:
        self._value = value

    def execute(self, reference, corpus):
        del reference, corpus
        return OnlyCalculationEquivalenceExecution(
            (
                OnlyCalculationEquivalenceRow(
                    "TEST.SYMBOL",
                    1_000_000_000,
                    (("value", self._value),),
                ),
            )
        )


def _reference(case):
    node = case.revision.decision_graph.ordered_nodes[0]
    registration = case.registry.resolve(
        node.definition.kind,
        node.definition.type_id,
        node.definition.semantic_version,
        OnlyCalculationBackendKind.RESEARCH,
    )
    assert registration.implementation_manifest is not None
    return registration.implementation_manifest.calculation_type_reference


def test_verifier_and_store_publish_deterministic_verified_evidence(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    reference = _reference(case)
    corpus = OnlyCalculationEquivalenceCorpus("EXACT", {"timestamps": [1_000_000_000]})
    verifier = OnlyCalculationEquivalenceVerifier(case.registry, _Runner(), _Runner())
    first = verifier.verify(reference, corpus)
    second = verifier.verify(reference, corpus)
    store = OnlyCalculationEquivalenceEvidenceStore(tmp_path / "authority")

    committed = store.commit(first)

    assert committed == store.commit(second)
    assert store.load_verified(committed.evidence_fingerprint) == committed
    assert store.require_verified(
        reference,
        committed.research_implementation_fingerprint,
        committed.trading_implementation_fingerprint,
    ) == (committed,)


def test_corpus_change_changes_evidence_but_not_implementation_pair(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    reference = _reference(case)
    verifier = OnlyCalculationEquivalenceVerifier(case.registry, _Runner(), _Runner())
    first = verifier.verify(reference, OnlyCalculationEquivalenceCorpus("A", {"axis": [1]})).evidence
    second = verifier.verify(reference, OnlyCalculationEquivalenceCorpus("B", {"axis": [1, 2]})).evidence

    assert first.evidence_fingerprint != second.evidence_fingerprint
    assert first.research_implementation_fingerprint == second.research_implementation_fingerprint
    assert first.trading_implementation_fingerprint == second.trading_implementation_fingerprint


def test_output_difference_cannot_create_equivalent_evidence(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    verifier = OnlyCalculationEquivalenceVerifier(case.registry, _Runner(Decimal("1")), _Runner(Decimal("2")))

    with pytest.raises(OnlyCalculationEquivalenceError) as error:
        verifier.verify(_reference(case), OnlyCalculationEquivalenceCorpus("DIFF", {"axis": [1]}))
    assert error.value.code == "EQUIVALENCE_VERIFICATION_FAILED"


def test_implementation_change_makes_old_evidence_inapplicable(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    reference = _reference(case)
    original = case.registry.resolve(
        reference.kind,
        reference.type_id,
        reference.semantic_version,
        OnlyCalculationBackendKind.RESEARCH,
    )
    assert original.implementation_manifest is not None
    changed_manifest = only_implementation_manifest_from_bytes(
        calculation_type_reference=reference,
        backend_kind=OnlyCalculationBackendKind.RESEARCH,
        entrypoint_identity=original.implementation_manifest.entrypoint_identity,
        resources={"changed.py": b"behavior changed"},
    )
    changed = OnlyCalculationRegistry()
    changed.register(replace(original, implementation_manifest=changed_manifest))
    trading = case.registry.resolve(
        reference.kind,
        reference.type_id,
        reference.semantic_version,
        OnlyCalculationBackendKind.TRADING,
    )
    assert trading.implementation_manifest is not None
    changed.register(trading)
    store = OnlyCalculationEquivalenceEvidenceStore(tmp_path / "authority")
    old = OnlyCalculationEquivalenceVerifier(case.registry, _Runner(), _Runner()).verify(
        reference,
        OnlyCalculationEquivalenceCorpus("EXACT", {"axis": [1]}),
    )
    store.commit(old)

    with pytest.raises(OnlyCalculationEquivalenceError) as error:
        store.require_verified(
            reference,
            changed_manifest.implementation_fingerprint,
            trading.implementation_manifest.implementation_fingerprint,
        )
    assert error.value.code == "EQUIVALENCE_EVIDENCE_NOT_FOUND"


def test_tampered_or_arbitrary_evidence_fingerprint_fails_closed(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    reference = _reference(case)
    store = OnlyCalculationEquivalenceEvidenceStore(tmp_path / "authority")
    evidence = store.commit(
        OnlyCalculationEquivalenceVerifier(case.registry, _Runner(), _Runner()).verify(
            reference,
            OnlyCalculationEquivalenceCorpus("EXACT", {"axis": [1]}),
        )
    )
    manifest = (
        tmp_path
        / "authority"
        / "calculation-equivalence"
        / "evidence"
        / evidence.evidence_fingerprint[:2]
        / evidence.evidence_fingerprint
        / "manifest.json"
    )
    manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(OnlyCalculationEquivalenceError) as corrupt:
        store.load_verified(evidence.evidence_fingerprint)
    assert corrupt.value.code == "EQUIVALENCE_EVIDENCE_CORRUPT"
    with pytest.raises(OnlyCalculationEquivalenceError) as missing:
        store.load_verified("f" * 64)
    assert missing.value.code == "EQUIVALENCE_EVIDENCE_NOT_FOUND"


def test_evidence_store_rejects_unexpected_files_and_symlink_authority(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    reference = _reference(case)
    verified = OnlyCalculationEquivalenceVerifier(case.registry, _Runner(), _Runner()).verify(
        reference,
        OnlyCalculationEquivalenceCorpus("EXACT", {"axis": [1]}),
    )
    store = OnlyCalculationEquivalenceEvidenceStore(tmp_path / "authority")
    evidence = store.commit(verified)
    target = (
        tmp_path
        / "authority"
        / "calculation-equivalence"
        / "evidence"
        / evidence.evidence_fingerprint[:2]
        / evidence.evidence_fingerprint
    )
    (target / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OnlyCalculationEquivalenceError) as unexpected:
        store.load_verified(evidence.evidence_fingerprint)
    assert unexpected.value.code == "EQUIVALENCE_EVIDENCE_CORRUPT"

    symlink_store = OnlyCalculationEquivalenceEvidenceStore(tmp_path / "symlink-authority")
    symlink_target = (
        tmp_path
        / "symlink-authority"
        / "calculation-equivalence"
        / "evidence"
        / evidence.evidence_fingerprint[:2]
        / evidence.evidence_fingerprint
    )
    symlink_target.parent.mkdir(parents=True)
    symlink_target.symlink_to(target, target_is_directory=True)
    with pytest.raises(OnlyCalculationEquivalenceError) as symlink:
        symlink_store.load_verified(evidence.evidence_fingerprint)
    assert symlink.value.code == "EQUIVALENCE_EVIDENCE_CORRUPT"
