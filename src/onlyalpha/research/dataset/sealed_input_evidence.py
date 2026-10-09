"""Strict neutral retained source lineage. Parsing never issues publication permission."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from onlyalpha.canonical import only_canonical_json, only_canonical_payload
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.market_data.durable.models import (
    OnlyCoverageManifest,
    OnlyCoverageStatus,
    OnlyIngestSegment,
    OnlyMarketDataPhysicalSegmentProof,
    OnlyMarketDataProvenance,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
)
from onlyalpha.market_data.durable.sealed_identity import (
    only_build_seal,
    only_native_bar_coverage_proof,
    only_verify_revision_authority,
)
from onlyalpha.market_data.resolution import OnlyBarConstructionIdentity, OnlyBarResolutionMode
from onlyalpha.plugin.integration_binding import only_verify_retained_integration_runtime_binding

from .definition import OnlyResearchDatasetDefinition
from .lineage import OnlyMarketDataRevisionBinding, only_dataset_materialization_id
from .manifest import OnlyResearchDatasetSnapshot
from .sealed_input_identity import OnlySealedMarketDataMaterializationPlan, only_sealed_market_data_input_fingerprints
from .strict import (
    require_exact_fields,
    require_int,
    require_list,
    require_mapping,
    require_sha256,
    require_str,
    require_utc_datetime,
)

_CONTEXT = "retained sealed Chart input"
_FIELDS = {
    "schema_version",
    "source_reference",
    "source_selection",
    "integration_binding_fingerprint",
    "scope",
    "evidence",
    "segments",
    "materialization",
    "dataset_snapshot_fingerprint",
    "integration_binding",
}


def _equal(value: object, expected: object) -> None:
    # JSON equality, unlike Python equality, distinguishes True from 1 recursively.
    if only_canonical_json(value) != only_canonical_json(expected):
        raise ValueError("retained sealed input representation/relation differs")


def _pairs(value: object) -> tuple[tuple[str, str], ...]:
    result = []
    for item in require_list(value, _CONTEXT):
        members = require_list(item, _CONTEXT)
        if len(members) != 2 or any(type(member) is not str or not member.strip() for member in members):
            raise ValueError("invalid retained identity pair")
        result.append((cast(str, members[0]), cast(str, members[1])))
    return tuple(result)


def _scope_payload(scope: OnlyMarketDataScope) -> dict[str, object]:
    assert scope.bar_construction is not None
    return cast(dict[str, object], only_canonical_payload(scope)) | {
        "bar_construction": scope.bar_construction.to_dict()
    }


def _segment_payload(segment: OnlyIngestSegment) -> dict[str, object]:
    assert segment.bar_construction is not None
    return cast(dict[str, object], only_canonical_payload(segment)) | {
        "bar_construction": segment.bar_construction.to_dict()
    }


def _require_temporal_support(scope: OnlyMarketDataScope, segments: list[OnlyIngestSegment]) -> None:
    """Prove feasible complete Bar support, not authenticity of uncopied rows.

    Each required closed interval needs one possible occurrence in a Segment
    covering that entire interval. Counts are capacities, never unique coverage.
    Earliest-end allocation for interval footprints preserves later possibilities;
    duplicates may leave unused capacity. Chart's existing 672-point bound keeps
    this consistency predicate finite, including for untrusted portable bytes.
    """
    stride = 15 * 60_000_000_000
    count = (scope.end_ns - scope.start_ns) // stride
    if not 1 <= count <= 672:
        raise ValueError("retained Chart support exceeds admitted point bound")
    assert scope.bar_construction is not None
    origin = scope.bar_construction.plan.grid_origin_ns
    footprints = sorted(
        ((segment.recovery_scope(), segment.canonical_count, segment.segment_id) for segment in segments),
        key=lambda item: (item[0].end_ns, item[2]),
    )
    remaining = [item[1] for item in footprints]
    if any(
        capacity and ((footprint.start_ns - origin) % stride or (footprint.end_ns - origin) % stride)
        for footprint, capacity, _ in footprints
    ):
        raise ValueError("source physical BAR footprint differs from native grid")
    for start in range(scope.start_ns, scope.end_ns, stride):
        for index, (footprint, _, _) in enumerate(footprints):
            if remaining[index] and footprint.start_ns <= start and start + stride <= footprint.end_ns:
                remaining[index] -= 1
                break
        else:
            raise ValueError("source physical BAR footprints/counts cannot prove complete native support")


def _decode(raw: Mapping[str, object]) -> tuple[OnlyMarketDataScope, OnlyMarketDataRevision, OnlyMarketDataSeal]:
    require_exact_fields(raw, _FIELDS, _CONTEXT)
    if require_int(raw, "schema_version", _CONTEXT) != 1:
        raise ValueError("unsupported sealed input evidence version")
    require_sha256(raw, "dataset_snapshot_fingerprint", _CONTEXT)
    binding = require_sha256(raw, "integration_binding_fingerprint", _CONTEXT)
    reference = require_mapping(raw["source_reference"], _CONTEXT)
    require_exact_fields(
        reference, {"integration_id", "integration_revision_fingerprint", "expected_type_id"}, _CONTEXT
    )
    integration = require_str(reference, "integration_id", _CONTEXT)
    if str(UUID(integration)) != integration:
        raise ValueError("noncanonical Integration identity")
    revision_ref = require_sha256(reference, "integration_revision_fingerprint", _CONTEXT)
    type_id = require_str(reference, "expected_type_id", _CONTEXT)
    selection = require_mapping(raw["source_selection"], _CONTEXT)
    require_exact_fields(
        selection,
        {"integration_id", "integration_revision_fingerprint", "type_id", "source_id", "environment"},
        _CONTEXT,
    )
    for name in selection:
        if not require_str(selection, name, _CONTEXT).strip():
            raise ValueError("empty source selection identity")
    _equal(
        (selection["integration_id"], selection["integration_revision_fingerprint"], selection["type_id"]),
        (integration, revision_ref, type_id),
    )
    binding_raw = require_mapping(raw["integration_binding"], _CONTEXT)
    only_verify_retained_integration_runtime_binding(binding_raw)
    _equal(
        (
            binding_raw["integration_id"],
            binding_raw["revision_fingerprint"],
            binding_raw["type_id"],
            binding_raw["binding_fingerprint"],
        ),
        (integration, revision_ref, type_id, binding),
    )
    scope_raw = require_mapping(raw["scope"], _CONTEXT)
    require_exact_fields(scope_raw, set(OnlyMarketDataScope.__dataclass_fields__), _CONTEXT)
    construction = OnlyBarConstructionIdentity.from_dict(require_mapping(scope_raw["bar_construction"], _CONTEXT))
    scope = OnlyMarketDataScope(**(dict(scope_raw) | {"bar_construction": construction}))  # type: ignore[arg-type]
    _equal(scope_raw, _scope_payload(scope))
    if (
        construction.plan.mode is not OnlyBarResolutionMode.PROVIDER_NATIVE
        or construction.plan.target_semantic != OnlyBarSemantic.fixed_duration(15)
        or construction.plan.integration_revision_fingerprint != revision_ref
        or scope.source_id != selection["source_id"]
        or scope.data_kind != "BAR"
        or scope.first_sequence is not None
        or scope.last_sequence is not None
        or type(scope.start_ns) is not int
        or type(scope.end_ns) is not int
        or not 0 <= scope.start_ns < scope.end_ns <= 2**63 - 1
        or scope.start_ns % 1000
        or scope.end_ns % 1000
    ):
        raise ValueError("sealed input source/construction/scope relation differs")
    evidence = require_mapping(raw["evidence"], _CONTEXT)
    require_exact_fields(evidence, {"revision", "manifest", "seal", "physical_proofs"}, _CONTEXT)
    manifest_raw = require_mapping(evidence["manifest"], _CONTEXT)
    manifest = OnlyCoverageManifest.build(
        scope,
        _pairs(manifest_raw["segment_refs"]),
        coverage_status=OnlyCoverageStatus.COMPLETE,
        proof=tuple(
            require_str({"item": item}, "item", _CONTEXT) for item in require_list(manifest_raw["proof"], _CONTEXT)
        ),
    )
    _equal(manifest_raw, manifest)
    stride_ns = construction.plan.target_semantic.stride_minutes * 60_000_000_000
    origin = construction.plan.grid_origin_ns
    count = (scope.end_ns - scope.start_ns) // stride_ns
    if (
        (scope.start_ns - origin) % stride_ns
        or (scope.end_ns - origin) % stride_ns
        or manifest.proof != only_native_bar_coverage_proof(count, count, True)
    ):
        raise ValueError("native bar coverage proof is incomplete")
    if not manifest.segment_refs or len({item[0] for item in manifest.segment_refs}) != len(manifest.segment_refs):
        raise ValueError("missing/duplicate retained Segment")
    revision_raw = require_mapping(evidence["revision"], _CONTEXT)
    parent = revision_raw["parent_revision_id"]
    if parent is not None and (type(parent) is not str or not parent.startswith("market-data-revision:")):
        raise ValueError("invalid parent Revision")
    revision = OnlyMarketDataRevision.build(
        manifest,
        normalizers=_pairs(revision_raw["normalizers"]),
        creation_reason=require_str(revision_raw, "creation_reason", _CONTEXT),
        parent_revision_id=parent,
    )
    _equal(revision_raw, revision)
    if not revision.normalizers or len(set(revision.normalizers)) != len(revision.normalizers):
        raise ValueError("missing/duplicate retained normalizer")
    seal_raw = require_mapping(evidence["seal"], _CONTEXT)
    seal = only_build_seal(revision, manifest, sealed_at=require_utc_datetime(seal_raw, "sealed_at", _CONTEXT))
    _equal(seal_raw, seal)
    only_verify_revision_authority(revision, manifest, seal)
    segments = []
    for item in require_list(raw["segments"], _CONTEXT):
        value = require_mapping(item, _CONTEXT)
        require_exact_fields(value, set(OnlyIngestSegment.__dataclass_fields__), _CONTEXT)
        for name in ("schema_version", "record_count", "raw_count", "canonical_count", "start_ns", "end_ns"):
            require_int(value, name, _CONTEXT)
        segment = OnlyIngestSegment(
            **(
                dict(value)
                | {  # type: ignore[arg-type]
                    "created_at": require_utc_datetime(value, "created_at", _CONTEXT),
                    "sealed_at": require_utc_datetime(value, "sealed_at", _CONTEXT),
                    "capture_mode": OnlyMarketDataProvenance(require_str(value, "capture_mode", _CONTEXT)),
                    "bar_construction": OnlyBarConstructionIdentity.from_dict(
                        require_mapping(value["bar_construction"], _CONTEXT)
                    ),
                }
            )
        )
        _equal(value, _segment_payload(segment))
        recovered = segment.recovery_scope()
        if (
            segment.integration_binding_fingerprint != binding
            or _scope_payload(recovered) | {"start_ns": scope.start_ns, "end_ns": scope.end_ns} != _scope_payload(scope)
            or not scope.start_ns <= recovered.start_ns < recovered.end_ns <= scope.end_ns
        ):
            raise ValueError("Segment source/Integration/scope differs")
        segments.append(segment)
    if tuple((item.segment_id, item.content_hash) for item in segments) != revision.segment_refs:
        raise ValueError("Segment occurrence coverage/order differs")
    proofs = tuple(
        OnlyMarketDataPhysicalSegmentProof.from_dict(require_mapping(item, _CONTEXT))
        for item in require_list(evidence["physical_proofs"], _CONTEXT)
    )
    _equal(evidence["physical_proofs"], [item.to_dict() for item in proofs])
    for segment, proof in zip(segments, proofs, strict=True):
        proof.assert_matches(segment)
        partitions = {item.table: item.row_count for item in proof.partitions}
        if (
            partitions["market_bar"] != proof.canonical_count
            or partitions["market_trade"]
            or partitions["market_reference_price"]
        ):
            raise ValueError("BAR source physical partition family/count differs")
    # A source may retain duplicate Bar occurrences, but it cannot prove more
    # unique grid points than its complete physical BAR occurrence count.
    if sum(item.canonical_count for item in proofs) < count:
        raise ValueError("source physical BAR count cannot prove native coverage")
    _require_temporal_support(scope, segments)
    materialization = require_mapping(raw["materialization"], _CONTEXT)
    require_exact_fields(
        materialization,
        {
            "materialization_id",
            "dataset_snapshot_fingerprint",
            "market_data_revision_bindings",
            "materializer_id",
            "materializer_version",
            "request_fingerprint",
        },
        _CONTEXT,
    )
    expected_bindings = (
        OnlyMarketDataRevisionBinding(
            scope.source_id, scope.instrument_id, scope.data_kind, revision.revision_id, revision.fingerprint
        ),
    )
    _equal(materialization["market_data_revision_bindings"], expected_bindings)
    _equal(materialization["dataset_snapshot_fingerprint"], raw["dataset_snapshot_fingerprint"])
    _equal(
        (materialization["materializer_id"], materialization["materializer_version"]),
        ("onlyalpha.sealed-market-data", "1"),
    )
    request = require_sha256(materialization, "request_fingerprint", _CONTEXT)
    expected_id = only_dataset_materialization_id(
        cast(str, raw["dataset_snapshot_fingerprint"]), expected_bindings, "onlyalpha.sealed-market-data", "1", request
    )
    _equal(materialization["materialization_id"], expected_id)
    return scope, revision, seal


@dataclass(frozen=True, slots=True)
class OnlyRetainedSealedChartInputEvidenceV1:
    canonical_json: str

    def __post_init__(self) -> None:
        raw = self.to_dict()
        _decode(raw)
        if only_canonical_json(raw) != self.canonical_json:
            raise ValueError("noncanonical sealed input evidence")

    def to_dict(self) -> dict[str, object]:
        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            value = dict(pairs)
            if len(value) != len(pairs):
                raise ValueError("duplicate sealed input field")
            return value

        return dict(require_mapping(json.loads(self.canonical_json, object_pairs_hook=unique), _CONTEXT))

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OnlyRetainedSealedChartInputEvidenceV1:
        def require_json(value: object) -> None:
            if value is None or type(value) in (str, int, bool):
                return
            if isinstance(value, Mapping) and all(type(key) is str for key in value):
                for item in value.values():
                    require_json(item)
            elif type(value) is list:
                for item in value:
                    require_json(item)
            else:
                raise ValueError("sealed input requires exact JSON types without coercion")

        require_json(raw)
        _decode(raw)
        return cls(only_canonical_json(raw))

    def verify_snapshot(self, snapshot: OnlyResearchDatasetSnapshot) -> None:
        raw = self.to_dict()
        scope, revision, seal = _decode(raw)
        assert scope.bar_construction is not None
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        definition = OnlyResearchDatasetDefinition(
            (OnlyInstrumentId.parse(scope.instrument_id),),
            scope.bar_construction.plan.target_semantic,
            OnlyTimeRange(
                epoch + timedelta(microseconds=scope.start_ns // 1000),
                epoch + timedelta(microseconds=scope.end_ns // 1000 + 1),
            ),
        )
        construction, request = only_sealed_market_data_input_fingerprints(
            OnlySealedMarketDataMaterializationPlan((revision.revision_id,), definition, (scope,)),
            ((scope.instrument_id, scope.bar_construction.fingerprint, revision.fingerprint, seal.seal_id),),
        )
        materialization = require_mapping(raw["materialization"], _CONTEXT)
        if (
            snapshot.snapshot_fingerprint != raw["dataset_snapshot_fingerprint"]
            or snapshot.definition != definition
            or snapshot.construction_fingerprint != construction
            or snapshot.row_count != (scope.end_ns - scope.start_ns) // (15 * 60_000_000_000)
            or materialization["request_fingerprint"] != request
            or len(snapshot.provenance) != 1
        ):
            raise ValueError("sealed input Materialization/Snapshot identity differs")
        provenance = snapshot.provenance[0]
        bounds = ((str(scope.start_ns), str(scope.end_ns)),)
        if (
            (
                provenance.source_id,
                provenance.instrument_id,
                provenance.data_version,
                provenance.plugin_id,
                provenance.plugin_version,
            )
            != (scope.source_id, scope.instrument_id, scope.data_version, "durable-market-data", "1")
            or provenance.cache_content_fingerprint is not None
            or provenance.resolved_ranges != bounds
            or provenance.observed_ranges != bounds
            or provenance.source_metadata
            != {
                "bar_construction_fingerprint": scope.bar_construction.fingerprint,
                "construction_recipe": scope.bar_construction.plan.resolved_recipe.to_dict(),
            }
        ):
            raise ValueError("sealed input Snapshot provenance differs")
