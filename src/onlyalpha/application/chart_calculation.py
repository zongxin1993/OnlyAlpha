"""Immutable chart calculation T1 intent, exact capability proof and admission service.

This boundary admits preparation only. It neither reads market facts nor creates work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogCalculationCapabilityV1,
    OnlyExactCatalogContextV1,
    OnlyExactCatalogReadinessProjectionV1,
    only_project_exact_catalog_readiness,
)
from onlyalpha.application.product_command_authority import OnlyProductCommandConflictError
from onlyalpha.application.product_command_receipt import OnlyProductCommandId, OnlyProductCommandKind
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationScalar,
    OnlyParameterDefinition,
    OnlyParameterSchema,
    OnlyParameterType,
)
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.research.run.model import OnlyResearchRunId

if TYPE_CHECKING:
    from .chart_calculation_ports import OnlyChartCalculationAdmissionStore

_SHA = re.compile(r"[0-9a-f]{64}")
_NS = re.compile(r"0|[1-9][0-9]*")
_DURATION_NS = 900_000_000_000


class OnlyChartCalculationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str = "CHART_REQUEST_INVALID") -> None:
    if not condition:
        raise OnlyChartCalculationError(code)


def _object(value: object, fields: set[str]) -> Mapping[str, object]:
    _require(isinstance(value, Mapping) and set(value) == fields)
    return cast(Mapping[str, object], value)


def _text(value: object) -> str:
    _require(isinstance(value, str) and bool(value) and len(value.encode("utf-8")) <= 256)
    return cast(str, value)


def _sha(value: object) -> str:
    result = _text(value)
    _require(_SHA.fullmatch(result) is not None)
    return result


def _utc(value: datetime) -> None:
    _require(isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() == UTC.utcoffset(value))


def _time_ns(value: object) -> int:
    text = _text(value)
    _require(_NS.fullmatch(text) is not None, "CHART_RANGE_INVALID")
    number = int(text)
    _require(number <= 2**63 - 1 and number % 1000 == 0, "CHART_RANGE_INVALID")
    return number


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationRequestV1:
    """Strict immutable request; JSON is retained as canonical value, never a mutable dict."""

    canonical_json: str

    def __post_init__(self) -> None:
        value = json.loads(self.canonical_json)
        root = _object(
            value,
            {"schema_version", "source_reference", "instrument_id", "bar_semantic", "display_range", "calculation"},
        )
        _require(type(root["schema_version"]) is int and root["schema_version"] == 1)
        source = _object(
            root["source_reference"], {"integration_id", "integration_revision_fingerprint", "expected_type_id"}
        )
        OnlyProductCommandId(_text(source["integration_id"]))
        _sha(source["integration_revision_fingerprint"])
        _text(source["expected_type_id"])
        instrument = _text(root["instrument_id"])
        try:
            _require(str(OnlyInstrumentId.parse(instrument)) == instrument)
        except OnlyValidationError as exc:
            raise OnlyChartCalculationError("CHART_REQUEST_INVALID") from exc
        semantic = _object(root["bar_semantic"], {"schema_version", "formation", "price_type", "adjustment_policy"})
        _require(type(semantic["schema_version"]) is int and semantic["schema_version"] == 2)
        formation = _object(
            semantic["formation"], {"schema_version", "kind", "window_minutes", "stride_minutes", "alignment"}
        )
        _require(all(type(formation[name]) is int for name in ("schema_version", "window_minutes", "stride_minutes")))
        _require(
            OnlyBarSemantic.from_dict(semantic) == OnlyBarSemantic.fixed_duration(15), "CHART_BAR_SEMANTIC_UNSUPPORTED"
        )
        bounds = _object(root["display_range"], {"start_ns", "end_ns"})
        _require(_time_ns(bounds["start_ns"]) < _time_ns(bounds["end_ns"]), "CHART_RANGE_INVALID")
        selection = _object(root["calculation"], {"kind", "type_id", "semantic_version", "parameters", "output_name"})
        _require(
            (selection["kind"], selection["type_id"], selection["semantic_version"])
            == ("INDICATOR", "onlyalpha.indicator.sma", "1"),
            "CHART_CALCULATION_UNSUPPORTED",
        )
        _require(selection["output_name"] == "value", "CHART_OUTPUT_UNSUPPORTED")
        _require(isinstance(selection["parameters"], dict), "CHART_PARAMETERS_INVALID")
        _require(
            self.canonical_json == only_canonical_json(value) and len(self.canonical_json.encode("utf-8")) <= 16384
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyChartCalculationRequestV1:
        # Reject non-JSON values before the shared canonical serializer can stringify them.
        return cls(only_canonical_json(json.loads(json.dumps(value, allow_nan=False))))

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.canonical_json))

    @property
    def intent_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    @property
    def command_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"command_kind": OnlyProductCommandKind.CREATE_CHART_CALCULATION.value, "intent": self.to_dict()}
        )


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationCatalogWitnessV1:
    """Self-contained exact projections, preserving their complete hash and relation proofs."""

    canonical_json: str

    def __post_init__(self) -> None:
        value = _object(
            json.loads(self.canonical_json), {"schema_version", "context", "readiness", "readiness_contract_version"}
        )
        _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
        _require(type(value["readiness_contract_version"]) is int and value["readiness_contract_version"] == 1)
        context = OnlyExactCatalogContextV1.from_dict(cast(Mapping[str, object], value["context"]))
        readiness = OnlyExactCatalogReadinessProjectionV1.from_dict(cast(Mapping[str, object], value["readiness"]))
        expected = only_project_exact_catalog_readiness(context, readiness.ordered_calculation_readiness_capabilities)
        _require(expected == readiness, "CHART_READINESS_CAPABILITY_UNAVAILABLE")
        capability = self._select(context)
        providers = [
            item
            for item in context.ordered_providers
            if item.sort_key == (capability.provider_kind.value, capability.provider_id, capability.provider_version)
        ]
        _require(len(providers) == 1, "CHART_READINESS_CAPABILITY_UNAVAILABLE")
        matches = [
            item
            for item in readiness.ordered_calculation_readiness_capabilities
            if item.sort_key == capability.sort_key
        ]
        _require(
            len(matches) == 1
            and matches[0].implementation_fingerprint == capability.implementation_fingerprint
            and 1 in matches[0].readiness_contract_versions,
            "CHART_READINESS_CAPABILITY_UNAVAILABLE",
        )
        _parameter_schema(capability)
        _require(self.canonical_json == only_canonical_json(value))

    @staticmethod
    def _select(context: OnlyExactCatalogContextV1) -> OnlyExactCatalogCalculationCapabilityV1:
        matches = [
            item
            for item in context.ordered_calculation_capabilities
            if (item.kind, item.type_id, item.semantic_version, item.backend)
            == (OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.sma", "1", OnlyCalculationBackendKind.RESEARCH)
        ]
        _require(len(matches) == 1, "CHART_READINESS_CAPABILITY_UNAVAILABLE")
        return matches[0]

    @property
    def capability(self) -> OnlyExactCatalogCalculationCapabilityV1:
        return self._select(OnlyExactCatalogContextV1.from_dict(cast(Mapping[str, object], self.to_dict()["context"])))

    @classmethod
    def from_projections(
        cls, context: OnlyExactCatalogContextV1, readiness: OnlyExactCatalogReadinessProjectionV1
    ) -> OnlyChartCalculationCatalogWitnessV1:
        return cls.from_dict(
            {
                "schema_version": 1,
                "context": context.to_dict(),
                "readiness": readiness.to_dict(),
                "readiness_contract_version": 1,
            }
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyChartCalculationCatalogWitnessV1:
        return cls(only_canonical_json(value))

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.canonical_json))

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())


def _parameter_schema(capability: OnlyExactCatalogCalculationCapabilityV1) -> OnlyParameterSchema:
    rows = cast(tuple[Mapping[str, object], ...], capability.type_descriptor["parameters"])
    _require(len(rows) == 2 and {row["name"] for row in rows} == {"period", "price_field"}, "CHART_PARAMETERS_INVALID")
    fields = []
    for row in rows:
        expected = OnlyParameterType.INTEGER if row["name"] == "period" else OnlyParameterType.STRING
        _require(row["parameter_type"] == expected.value, "CHART_PARAMETERS_INVALID")
        fields.append(
            OnlyParameterDefinition(
                _text(row["name"]),
                expected,
                cast(bool, row["required"]),
                cast(OnlyCalculationScalar, row["default"]),
                cast(int | None, row["minimum"]),
                cast(int | None, row["maximum"]),
                cast(tuple[OnlyCalculationScalar, ...], row["enum_values"]),
                cast(bool, row["uppercase"]),
            )
        )
    _require(
        any(
            row["name"] == "value"
            for row in cast(tuple[Mapping[str, object], ...], capability.type_descriptor["outputs"])
        ),
        "CHART_OUTPUT_UNSUPPORTED",
    )
    return OnlyParameterSchema(tuple(fields))


def only_normalize_chart_calculation(
    request: OnlyChartCalculationRequestV1, witness: OnlyChartCalculationCatalogWitnessV1, accepted_at: datetime
) -> OnlyChartCalculationRequestV1:
    _utc(accepted_at)
    value = request.to_dict()
    selection = cast(dict[str, object], value["calculation"])
    parameters = cast(dict[str, object], selection["parameters"])
    for name, item in parameters.items():
        _require(
            (name == "period" and type(item) is int) or (name == "price_field" and type(item) is str),
            "CHART_PARAMETERS_INVALID",
        )
    schema = _parameter_schema(witness.capability)
    try:
        normalized = dict(schema.normalize(parameters))
    except (ValueError, TypeError) as exc:
        raise OnlyChartCalculationError("CHART_PARAMETERS_INVALID") from exc
    _require(type(normalized["period"]) is int and 1 <= normalized["period"] <= 672, "CHART_RESOURCE_LIMIT")
    selection["parameters"] = normalized
    bounds = cast(dict[str, object], value["display_range"])
    start, end = _time_ns(bounds["start_ns"]), _time_ns(bounds["end_ns"])
    delta = accepted_at - datetime(1970, 1, 1, tzinfo=UTC)
    cutoff = ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1000
    _require(end <= cutoff, "CHART_RANGE_NOT_CLOSED")
    # Grid origin/coverage is plugin-owned and checked only in later input selection.
    support = end - start + (cast(int, normalized["period"]) - 1) * _DURATION_NS
    _require(
        start >= (cast(int, normalized["period"]) - 1) * _DURATION_NS and support <= 672 * _DURATION_NS,
        "CHART_RESOURCE_LIMIT",
    )
    return OnlyChartCalculationRequestV1.from_dict(value)


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationOperationV1:
    operation_id: OnlyProductCommandId
    product_command_id: OnlyProductCommandId
    command_fingerprint: str
    intent_fingerprint: str
    intent: OnlyChartCalculationRequestV1
    catalog_witness: OnlyChartCalculationCatalogWitnessV1
    reserved_run_id: OnlyResearchRunId
    accepted_at: datetime
    schema_version: int = 1
    state: str = "ADMITTED"
    preparation_revision: int = 0

    def __post_init__(self) -> None:
        _require(isinstance(self.operation_id, OnlyProductCommandId) and self.operation_id == self.product_command_id)
        _require(type(self.schema_version) is int and self.schema_version == 1 and self.state == "ADMITTED")
        _require(type(self.preparation_revision) is int and self.preparation_revision == 0)
        _require(
            isinstance(self.reserved_run_id, OnlyResearchRunId)
            and self.reserved_run_id.value != self.operation_id.value
        )
        _utc(self.accepted_at)
        _require(self.intent == only_normalize_chart_calculation(self.intent, self.catalog_witness, self.accepted_at))
        _require(
            self.intent_fingerprint == self.intent.intent_fingerprint
            and self.command_fingerprint == self.intent.command_fingerprint
        )


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationAdmissionOutcome:
    operation: OnlyChartCalculationOperationV1
    reused: bool


def only_verify_chart_calculation_retry(
    request: OnlyChartCalculationRequestV1, operation: OnlyChartCalculationOperationV1
) -> None:
    try:
        normalized = only_normalize_chart_calculation(request, operation.catalog_witness, operation.accepted_at)
    except ValueError as exc:
        raise OnlyProductCommandConflictError(operation.product_command_id.value) from exc
    if normalized != operation.intent:
        raise OnlyProductCommandConflictError(operation.product_command_id.value)


class OnlyChartCalculationAdmissionService:
    def __init__(
        self,
        store: OnlyChartCalculationAdmissionStore,
        catalog: Callable[[], tuple[OnlyExactCatalogContextV1, OnlyExactCatalogReadinessProjectionV1]],
    ) -> None:
        self._store = store
        self._catalog = catalog

    def admit(
        self, command_id: OnlyProductCommandId, request: OnlyChartCalculationRequestV1, *, accepted_at: datetime
    ) -> OnlyChartCalculationAdmissionOutcome:
        existing = self._store.load_verified(command_id)
        if existing is not None:
            only_verify_chart_calculation_retry(request, existing)
            return OnlyChartCalculationAdmissionOutcome(existing, True)
        context, readiness = self._catalog()
        witness = OnlyChartCalculationCatalogWitnessV1.from_projections(context, readiness)
        only_normalize_chart_calculation(request, witness, accepted_at)
        return self._store.admit_or_replay(command_id, request, witness, accepted_at=accepted_at)
