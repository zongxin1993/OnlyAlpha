"""Pure public SDK values; no dataset, runtime or execution admission is granted."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import product

import pyarrow as pa
import pytest
from onlyalpha.algorithm.batch import (
    OnlyResearchCalculationError,
    OnlyResearchOutputReadiness,
    OnlyResearchReadinessReason,
    OnlyResearchReadinessState,
    only_validate_research_output_readiness,
)
from onlyalpha.calculation.chart_decimal import only_chart_study_effective_numeric, only_chart_study_numeric_binding
from onlyalpha.calculation.chart_study import OnlyChartStudySeries, OnlyChartStudySupport
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
    OnlyNumericDefinition,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationSemanticDependency,
    only_implementation_manifest_from_bytes,
)
from onlyalpha.calculation.value_semantics import OnlyCanonicalValueSemanticsV1
from onlyalpha.quant_assets.private_factor_provider_snapshot import (
    OnlyPrivateFactorProviderSnapshotEntryV1,
    OnlyPrivateFactorProviderSnapshotV1,
)
from onlyalpha_backend_algorithms.targets.registration import resolve_forward_return

NUMERIC = OnlyNumericDefinition("DECIMAL", 38, Decimal("0.000000000001"), ROUND_HALF_EVEN)


@pytest.mark.parametrize(
    "operation,left,right,expected",
    [
        ("add", "2.125", "4", "6.125"),
        ("sub", "2.125", "4", "-1.875"),
        ("mul", "2.125", "4", "8.5"),
        ("div", "2.125", "4", "0.53125"),
        ("div", "1", "0", None),
        ("min", "-2", "3", "-2"),
        ("max", "-2", "3", "3"),
    ],
)
def test_exact_decimal_operations_and_zero_division(operation, left, right, expected):
    api = OnlyCanonicalValueSemanticsV1(NUMERIC)
    actual = getattr(api, operation)(Decimal(left), Decimal(right))
    assert actual == (None if expected is None else Decimal(expected))
    assert getattr(api, operation)(None, Decimal(right)) is None
    with pytest.raises(TypeError, match="DECIMAL_REQUIRED"):
        getattr(api, operation)(True, Decimal(right))


@pytest.mark.parametrize(
    "operation,expected", [("eq", False), ("ne", True), ("lt", True), ("le", True), ("gt", False), ("ge", False)]
)
def test_ordering_never_coerces_missing_or_nonfinite_values(operation, expected):
    api = OnlyCanonicalValueSemanticsV1(NUMERIC)
    assert getattr(api, operation)(Decimal("-1"), Decimal("2")) is expected
    assert getattr(api, operation)(Decimal("-1"), None) is None
    for bad in (1, "1", Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(TypeError, match="DECIMAL_REQUIRED"):
            getattr(api, operation)(bad, Decimal("2"))


@pytest.mark.parametrize("left,right", list(product((False, True, None), repeat=2)))
def test_three_valued_boolean_tables_are_exact(left, right):
    api = OnlyCanonicalValueSemanticsV1(NUMERIC)
    expected_and = False if left is False or right is False else None if None in (left, right) else True
    expected_or = True if left is True or right is True else None if None in (left, right) else False
    assert api.and_(left, right) is expected_and
    assert api.or_(left, right) is expected_or
    assert api.not_(left) is (None if left is None else not left)
    assert api.where(left, "yes", "no") == (None if left is None else "yes" if left else "no")
    assert api.is_missing(left) is (left is None)
    assert api.coalesce(left, "fallback") == ("fallback" if left is None else left)
    with pytest.raises(TypeError, match="BOOLEAN_REQUIRED"):
        api.not_(1)
    assert api.negate(None) is None
    assert api.negate(Decimal("-2")) == Decimal("2")


def readiness(states, reasons):
    return OnlyResearchOutputReadiness(pa.array(states, type=pa.string()), pa.array(reasons, type=pa.string()))


@pytest.mark.parametrize(
    "state,reason,is_null,nullable",
    list(product(tuple(OnlyResearchReadinessState), tuple(OnlyResearchReadinessReason), (False, True), (False, True))),
)
def test_readiness_pairs_values_reasons_and_nullable_contract(state, reason, is_null, nullable):
    from onlyalpha.calculation.definition import OnlyCalculationReference

    definition = resolve_forward_return(
        {"exit_offset": 2},
        OnlyCalculationReference(None, "value", "bar.close"),
        OnlyCalculationReference(None, "value", "bar.close"),
    )
    definition = replace(definition, outputs=(replace(definition.outputs[0], nullable=nullable),))
    name = definition.outputs[0].name
    values = pa.array([None if is_null else Decimal("0")], type=pa.decimal128(38, 12))
    evidence = readiness([state.value], [reason.value])
    valid = (
        (
            state is OnlyResearchReadinessState.PARTIAL
            and reason is OnlyResearchReadinessReason.WARMUP_INCOMPLETE
            and (not is_null or nullable)
        )
        or (
            state is OnlyResearchReadinessState.READY
            and (
                (not is_null and reason is OnlyResearchReadinessReason.NONE)
                or (is_null and nullable and reason is OnlyResearchReadinessReason.VALUE_UNDEFINED)
            )
        )
        or (
            state is OnlyResearchReadinessState.UNAVAILABLE
            and is_null
            and reason
            in (OnlyResearchReadinessReason.INPUT_UNAVAILABLE, OnlyResearchReadinessReason.DEPENDENCY_UNAVAILABLE)
        )
    )
    if valid:
        only_validate_research_output_readiness(definition, {name: values}, {name: evidence}, row_count=1)
    else:
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_INVALID"):
            only_validate_research_output_readiness(definition, {name: values}, {name: evidence}, row_count=1)


def test_readiness_rejects_alignment_unknown_enums_and_non_string_evidence():
    from onlyalpha.calculation.definition import OnlyCalculationReference

    d = resolve_forward_return(
        {"exit_offset": 2},
        OnlyCalculationReference(None, "value", "bar.close"),
        OnlyCalculationReference(None, "value", "bar.close"),
    )
    name = d.outputs[0].name
    values = {name: pa.array([Decimal("0")], type=pa.decimal128(38, 12))}
    good = {name: readiness(["READY"], ["NONE"])}
    for count in (True, -1, 1.5, "1"):
        with pytest.raises(OnlyResearchCalculationError):
            only_validate_research_output_readiness(d, values, good, row_count=count)
    for outputs, evidence in [
        ({}, good),
        (values, {}),
        (values, {name: object()}),
        ({name: [Decimal("0")]}, good),
        (values, {name: readiness(["WRONG"], ["NONE"])}),
        (values, {name: readiness(["READY"], [None])}),
        (values, {name: OnlyResearchOutputReadiness(pa.array([1]), pa.array(["NONE"]))}),
    ]:
        with pytest.raises(OnlyResearchCalculationError):
            only_validate_research_output_readiness(d, outputs, evidence, row_count=1)
    with pytest.raises(OnlyResearchCalculationError):
        only_validate_research_output_readiness(d, values, good, row_count=2)


def test_chart_decimal_binding_is_explicit_and_presentation_is_detached():
    declared = OnlyNumericDefinition("DECIMAL", 28, Decimal("0.000000000001"), "CONTEXT")
    assert only_chart_study_effective_numeric(declared).rounding == ROUND_HALF_EVEN
    binding = only_chart_study_numeric_binding(declared)
    assert binding["effective_rounding"] == ROUND_HALF_EVEN and binding["declared_rounding"] == "CONTEXT"
    assert binding["precision"] == 28 and binding["output_quantum"] == "0.000000000001"
    for bad in (
        replace(declared, precision=38),
        replace(declared, rounding="ROUND_DOWN"),
        replace(declared, output_quantum=None),
    ):
        with pytest.raises(ValueError, match="CHART_STUDY_NUMERIC_UNAVAILABLE"):
            only_chart_study_effective_numeric(bad)
    parameters = {"period": 20}
    series = OnlyChartStudySeries("value", "Value", "LINE", "SCALAR", "blue")
    support = OnlyChartStudySupport("Mean", "Trend", parameters, (series,), "SEPARATE_PANE", ("value", "zero"))
    parameters["period"] = 5
    document = support.to_dict()
    assert document["default_parameters"] == {"period": 20} and document["fill"] == ["value", "zero"]
    document["default_parameters"]["period"] = 2
    assert support.to_dict()["default_parameters"] == {"period": 20}
    assert series.to_dict()["default_visible"] is True
    assert replace(support, fill=None).to_dict()["fill"] is None


def snapshot_values():
    # Content-addressed pure metadata fixture. It does not assert that a Runtime
    # ever installed or admitted these bytes, or grant an execution capability.
    source = b"fixture source bytes"
    source_hash = hashlib.sha256(source).hexdigest()
    api = hashlib.sha256(b"fixture api").hexdigest()
    artifact = hashlib.sha256(b"fixture source artifact").hexdigest()
    manifests = []
    adapters = [
        hashlib.sha256(value).hexdigest() for value in (b"research-fixture-adapter", b"trading-fixture-adapter")
    ]
    reference = OnlyCalculationTypeReference(OnlyCalculationKind.FACTOR, "private.factor.snapshot_contract", "1")
    for backend, adapter, entrypoint in [
        (OnlyCalculationBackendKind.RESEARCH, adapters[0], "OnlyPrivateFactorResearchBackendV1"),
        (OnlyCalculationBackendKind.TRADING, adapters[1], "OnlyPrivateFactorTradingBackendFactoryV1"),
    ]:
        prefix = "private_factor/" + backend.value.lower()
        manifests.append(
            only_implementation_manifest_from_bytes(
                calculation_type_reference=reference,
                backend_kind=backend,
                entrypoint_identity="onlyalpha_backend_algorithms.sdk.private_factor_execution:" + entrypoint,
                resources={
                    "private_factor/source.py": source,
                    prefix + "-adapter.py": b"adapter fixture",
                    prefix + "-identity.txt": adapter.encode(),
                },
                semantic_dependencies=(
                    OnlyCalculationSemanticDependency("onlyalpha.private-factor.api", "1", api),
                    OnlyCalculationSemanticDependency("onlyalpha.private-factor.source-artifact", "1", artifact),
                ),
            )
        )
    entry = OnlyPrivateFactorProviderSnapshotEntryV1(
        reference.type_id,
        "1",
        hashlib.sha256(b"unpublished revision fixture").hexdigest(),
        source_hash,
        artifact,
        1,
        api,
        *adapters,
        manifests[0].implementation_fingerprint,
        manifests[1].implementation_fingerprint,
        hashlib.sha256(b"equivalence fixture").hexdigest(),
    )
    return entry, manifests


def test_provider_snapshot_binds_exact_implementations_and_reads_canonical_values():
    entry, manifests = snapshot_values()
    for manifest in manifests:
        entry.require_implementation_manifest(manifest)
    snapshot = OnlyPrivateFactorProviderSnapshotV1((entry,))
    assert type(snapshot).from_dict(snapshot.to_dict()) == snapshot
    assert type(entry).from_dict(entry.to_dict()) == entry
    for bad in (
        {},
        {**snapshot.to_dict(), "extra": 1},
        {**snapshot.to_dict(), "snapshot_fingerprint": "0" * 64},
        {**snapshot.to_dict(), "entries": [1]},
    ):
        with pytest.raises(ValueError, match="SNAPSHOT_INVALID"):
            type(snapshot).from_dict(bad)
    for change in (
        {"factor_id": "bad id"},
        {"factor_api_version": True},
        {"source_sha256": "x"},
        {"semantic_version": ""},
    ):
        with pytest.raises(ValueError, match="SNAPSHOT_INVALID"):
            replace(entry, **change)
    for bad in ({}, {**entry.to_dict(), "factor_api_version": True}, {**entry.to_dict(), "source_sha256": 1}):
        with pytest.raises(ValueError, match="SNAPSHOT_INVALID"):
            type(entry).from_dict(bad)
    for entries in ((), (entry, entry)):
        with pytest.raises(ValueError, match="SNAPSHOT_INVALID"):
            type(snapshot)(entries)
    for bad in (
        replace(entry, source_sha256="0" * 64),
        replace(entry, research_implementation_fingerprint="0" * 64),
        replace(entry, factor_api_version=2),
        replace(entry, research_adapter_fingerprint="0" * 64),
    ):
        with pytest.raises(ValueError, match="IMPLEMENTATION_MANIFEST_MISMATCH"):
            bad.require_implementation_manifest(manifests[0])
