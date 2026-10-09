"""Strict source proof mutations and offline lineage, not publication issuance."""

import subprocess
import sys
from copy import deepcopy

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.dataset.sealed_input_evidence import OnlyRetainedSealedChartInputEvidenceV1
from tests.application.test_chart_calculation_input_export import export_case

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def source_proof(tmp_path_factory):
    root = tmp_path_factory.mktemp("sealed-input-evidence")
    chart, _, exporter = export_case(root)
    retained = exporter.export(chart.operation.operation_id).retained
    snapshot = chart.dataset.load_verified_table(chart.preparation.dataset_snapshot_fingerprint).snapshot
    return retained, snapshot


@pytest.mark.parametrize(
    "path",
    (
        ("source_reference",),
        ("source_selection",),
        ("integration_binding",),
        ("evidence",),
        ("scope",),
        ("materialization",),
        ("segments",),
        ("dataset_snapshot_fingerprint",),
        ("source_reference", "integration_id"),
        ("source_reference", "integration_revision_fingerprint"),
        ("source_selection", "source_id"),
        ("integration_binding", "runtime_configuration_fingerprint"),
        ("scope", "bar_construction"),
        ("evidence", "revision"),
        ("evidence", "manifest"),
        ("evidence", "seal"),
        ("evidence", "physical_proofs"),
        ("evidence", "seal", "seal_id"),
        ("evidence", "physical_proofs", 0, "partitions"),
        ("segments", 0, "segment_id"),
        ("materialization", "materialization_id"),
        ("materialization", "market_data_revision_bindings"),
        ("materialization", "request_fingerprint"),
        ("materialization", "materializer_version"),
    ),
)
@pytest.mark.parametrize("mutation", ("missing", "null", "unknown"))
def test_each_mandatory_source_dimension_is_strict(source_proof, path, mutation):
    retained, snapshot = source_proof
    value = deepcopy(retained.to_dict())
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    if mutation == "missing":
        del parent[path[-1]]
    elif mutation == "null":
        parent[path[-1]] = None
    else:
        if isinstance(parent[path[-1]], dict):
            parent[path[-1]]["unknown"] = 1
        else:
            parent["unknown"] = 1
    with pytest.raises((ValueError, TypeError, KeyError, AttributeError)):
        proof = OnlyRetainedSealedChartInputEvidenceV1.from_dict(value)
        proof.verify_snapshot(snapshot)


@pytest.mark.parametrize(
    "kind",
    (
        "bool_version",
        "duplicate_segment",
        "duplicate_proof",
        "duplicate_partition",
        "wrong_binding_owner",
        "wrong_binding_family",
        "different_materializer",
        "different_request",
        "different_snapshot",
        "different_integration",
        "wrong_seal",
        "duplicate_normalizer",
    ),
)
def test_retained_context_mutations_cannot_prove_source_match(source_proof, kind):
    retained, snapshot = source_proof
    value = deepcopy(retained.to_dict())
    if kind == "bool_version":
        value["schema_version"] = True
    elif kind == "duplicate_segment":
        value["segments"].append(value["segments"][0])
    elif kind == "duplicate_proof":
        value["evidence"]["physical_proofs"] *= 2
    elif kind == "duplicate_partition":
        value["evidence"]["physical_proofs"][0]["partitions"][0] = value["evidence"]["physical_proofs"][0][
            "partitions"
        ][1]
    elif kind == "wrong_binding_owner":
        value["integration_binding"]["integration_id"] = "00000000-0000-4000-8000-000000000001"
    elif kind == "wrong_binding_family":
        value["integration_binding"]["category"] = "BROKER"
    elif kind == "different_materializer":
        value["materialization"]["materializer_version"] = "2"
    elif kind == "different_request":
        value["materialization"]["request_fingerprint"] = "f" * 64
    elif kind == "different_snapshot":
        value["dataset_snapshot_fingerprint"] = "f" * 64
    elif kind == "different_integration":
        value["source_reference"]["integration_revision_fingerprint"] = "f" * 64
    elif kind == "wrong_seal":
        value["evidence"]["seal"]["seal_id"] = "seal:" + "f" * 64
    else:
        value["evidence"]["revision"]["normalizers"] *= 2
    with pytest.raises((ValueError, TypeError, KeyError, AttributeError)):
        OnlyRetainedSealedChartInputEvidenceV1.from_dict(value).verify_snapshot(snapshot)


def test_duplicate_json_keys_cannot_be_normalized_away(source_proof):
    retained, _ = source_proof
    raw = '{"schema_version":1,' + retained.canonical_json[1:]
    with pytest.raises(ValueError, match="duplicate"):
        OnlyRetainedSealedChartInputEvidenceV1(raw)


def test_portable_source_proof_has_no_executable_or_owning_reader_import(source_proof, tmp_path):
    retained, snapshot = source_proof
    payload = tmp_path / "retained.json"
    payload.write_text(only_canonical_json({"input": retained.to_dict(), "snapshot": snapshot.to_dict()}))
    source = r"""
import importlib.abc, json, sys
class NoAuthority(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('onlyalpha.application', 'onlyalpha.runtime', 'onlyalpha.persistence',
                                'onlyalpha_runtime_generation_manager', 'onlyalpha.market_data.durable.revision',
                                'onlyalpha.market_data.durable.memory', 'onlyalpha.market_data.durable.recorder',
                                'onlyalpha.research.dataset.parquet_store',
                                'onlyalpha.research.dataset.market_data_materializer')):
            raise AssertionError('portable input imported owning/executable module: ' + fullname)
sys.meta_path.insert(0, NoAuthority())
from onlyalpha.research.dataset.sealed_input_evidence import OnlyRetainedSealedChartInputEvidenceV1
from onlyalpha.research.dataset.manifest import OnlyResearchDatasetSnapshot
with open(sys.argv[1]) as f:
    raw = json.load(f)
proof = OnlyRetainedSealedChartInputEvidenceV1.from_dict(raw['input'])
proof.verify_snapshot(OnlyResearchDatasetSnapshot.from_dict(raw['snapshot']))
print('verified')
"""
    assert subprocess.check_output([sys.executable, "-c", source, str(payload)], text=True).strip() == "verified"


@pytest.mark.parametrize("mutation", ("wrong_family", "too_few_bars", "narrow_support"))
def test_fingerprint_correct_physical_proof_cannot_contradict_native_coverage(source_proof, mutation):
    from dataclasses import replace
    from datetime import datetime

    from onlyalpha.market_data.durable.models import (
        OnlyIngestSegment,
        OnlyMarketDataPhysicalSegmentProof,
        OnlyMarketDataProvenance,
    )
    from onlyalpha.market_data.resolution import OnlyBarConstructionIdentity

    retained, snapshot = source_proof
    payload = deepcopy(retained.to_dict())
    raw = payload["evidence"]["physical_proofs"][0]
    proof = OnlyMarketDataPhysicalSegmentProof.from_dict(raw)
    value = payload["segments"][0]
    segment = OnlyIngestSegment(
        **(
            value
            | {
                "created_at": datetime.fromisoformat(value["created_at"]),
                "sealed_at": datetime.fromisoformat(value["sealed_at"]),
                "capture_mode": OnlyMarketDataProvenance(value["capture_mode"]),
                "bar_construction": OnlyBarConstructionIdentity.from_dict(value["bar_construction"]),
            }
        )
    )
    partitions = tuple(
        replace(item, row_count=(proof.canonical_count if item.table == "market_trade" else 0))
        if item.table in ("market_trade", "market_bar")
        else item
        for item in proof.partitions
    )
    if mutation == "too_few_bars":
        segment = replace(segment, canonical_count=1)
        value["canonical_count"] = segment.canonical_count
        value["record_count"] = segment.record_count
        partitions = tuple(
            replace(item, row_count=1) if item.table == "market_bar" else item for item in proof.partitions
        )
    if mutation == "narrow_support":
        segment = replace(segment, end_ns=segment.start_ns + 15 * 60_000_000_000)
        value["end_ns"] = segment.end_ns
        partitions = proof.partitions
    proof = OnlyMarketDataPhysicalSegmentProof.build(segment, partitions)
    proof.assert_matches(segment)  # Mutation is a complete generic physical proof.
    payload["evidence"]["physical_proofs"][0] = proof.to_dict()
    with pytest.raises(ValueError, match="physical.*(family/count|native coverage|native support)"):
        OnlyRetainedSealedChartInputEvidenceV1.from_dict(payload).verify_snapshot(snapshot)


@pytest.mark.parametrize(
    "case", ("capacity_gap", "temporal_gap", "zero_count", "off_grid", "adjacent", "overlap", "duplicates")
)
def test_segment_temporal_support_uses_interval_ownership_and_capacity(source_proof, case):
    from dataclasses import replace
    from datetime import datetime

    from onlyalpha.market_data.durable.models import OnlyIngestSegment, OnlyMarketDataProvenance
    from onlyalpha.market_data.resolution import OnlyBarConstructionIdentity
    from onlyalpha.research.dataset.sealed_input_evidence import _decode, _require_temporal_support

    retained, _ = source_proof
    raw = retained.to_dict()
    scope, _, _ = _decode(raw)
    value = raw["segments"][0]
    segment = OnlyIngestSegment(
        **(
            value
            | {
                "created_at": datetime.fromisoformat(value["created_at"]),
                "sealed_at": datetime.fromisoformat(value["sealed_at"]),
                "capture_mode": OnlyMarketDataProvenance(value["capture_mode"]),
                "bar_construction": OnlyBarConstructionIdentity.from_dict(value["bar_construction"]),
            }
        )
    )
    stride = 15 * 60_000_000_000
    middle = scope.start_ns + 3 * stride
    first = replace(segment, segment_id="first", end_ns=middle, canonical_count=3)
    last = replace(segment, segment_id="last", start_ns=middle, canonical_count=3)
    if case == "capacity_gap":
        first, last = replace(first, canonical_count=1), replace(last, canonical_count=5)
    elif case == "temporal_gap":
        last = replace(last, start_ns=middle + stride, canonical_count=3)
    elif case == "zero_count":
        first, last = replace(first, canonical_count=0), replace(last, canonical_count=6)
    elif case == "off_grid":
        first = replace(first, end_ns=middle + 1000)
    elif case == "overlap":
        first, last = replace(first, end_ns=middle + stride), replace(last, start_ns=middle - stride)
    elif case == "duplicates":
        first, last = replace(first, canonical_count=6), replace(last, canonical_count=6)
    if case in ("capacity_gap", "temporal_gap", "zero_count", "off_grid"):
        with pytest.raises(ValueError, match="native (support|grid)"):
            _require_temporal_support(scope, [first, last])
    else:
        _require_temporal_support(scope, [last, first])


def test_raw_non_json_scalar_cannot_be_coerced_into_source_identity(source_proof):
    retained, _ = source_proof
    payload = deepcopy(retained.to_dict())
    payload["source_selection"]["environment"] = 1.5
    with pytest.raises(ValueError, match="without coercion"):
        OnlyRetainedSealedChartInputEvidenceV1.from_dict(payload)
