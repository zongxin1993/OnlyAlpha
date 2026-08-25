from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from onlyalpha_api import create_research_app
from onlyalpha_api.health import OnlyKernelResearchReadinessProjection
from onlyalpha_api.research.definition_schema import ResearchDefinitionRequestDto
from onlyalpha_api.research.run_schema import SubmitResearchRunRequest

from onlyalpha.kernel import OnlyAlphaKernelHost
from onlyalpha.research.command import OnlyResearchCommandService, OnlyResearchRunQueryService
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.definition import (
    OnlyResearchDefinitionResolver,
    OnlyResearchRegisteredUniverse,
    OnlyResearchUniverseKind,
    OnlyResearchUniverseSelection,
)
from onlyalpha.research.operations.readiness import (
    OnlyResearchReadiness,
    OnlyResearchReadinessCheck,
    OnlyResearchReadinessStatus,
)
from onlyalpha.research.query import OnlyResearchArtifactReader
from onlyalpha.research.specification import OnlyResearchSpecification
from tests.research.calculation.support import snapshot
from tests.research.definition.support import definition
from tests.research.evaluation.support import evaluation_registry


class _Unused:
    pass


class _Universes:
    def list_registered(self) -> tuple[OnlyResearchRegisteredUniverse, ...]:
        return (
            OnlyResearchRegisteredUniverse("z.pool", OnlyResearchUniverseKind.REGISTERED_POOL, {"title": "Z"}),
            OnlyResearchRegisteredUniverse("a.universe", OnlyResearchUniverseKind.REGISTERED_UNIVERSE),
        )

    def resolve(self, selection: OnlyResearchUniverseSelection) -> tuple[str, ...]:
        return {
            "z.pool": ("B.XNAS", "A.XNAS"),
            "a.universe": ("A.XNAS", "B.XNAS"),
        }[selection.registered_id or ""]


class _ResolverOnlyUniverses:
    def resolve(self, selection: OnlyResearchUniverseSelection) -> tuple[str, ...]:
        return ("A.XNAS", "B.XNAS")


def _case(tmp_path, universe_authority=None):  # type: ignore[no-untyped-def]
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets")
    candidate, partitions = snapshot()
    committed = store.commit(candidate, partitions)
    calculations = evaluation_registry()
    resolver = OnlyResearchDefinitionResolver(calculations, store, universe_resolver=universe_authority)
    kernel = OnlyAlphaKernelHost()
    kernel.start()
    app = create_research_app(
        cast(OnlyResearchArtifactReader, _Unused()),
        cast(OnlyResearchCommandService, _Unused()),
        cast(OnlyResearchRunQueryService, _Unused()),
        calculations,
        resolver,
        OnlyKernelResearchReadinessProjection(
            kernel,
            OnlyResearchReadiness(
                OnlyResearchReadinessStatus.READY,
                (OnlyResearchReadinessCheck("product_scope", "READY"),),
            ),
        ),
    )
    return committed, calculations, resolver, TestClient(app)


def test_discovery_projects_authorities_in_stable_order_and_hides_predicates(tmp_path) -> None:
    _, calculations, _, client = _case(tmp_path)
    response = client.get("/api/v2/research/catalog/calculations")
    assert response.status_code == 200
    items = response.json()["calculations"]
    keys = [
        (item["kind"], item["type_reference"]["type_id"], item["type_reference"]["semantic_version"]) for item in items
    ]
    assert keys == sorted(keys)
    assert keys
    assert not any(kind == "PREDICATE" for kind, _, _ in keys)
    assert any(item.kind.value == "PREDICATE" for item in calculations.type_definitions())

    rsi = next(item for item in calculations.type_definitions() if item.type_id == "onlyalpha.indicator.rsi")
    projected = next(item for item in items if item["type_reference"]["type_id"] == rsi.type_id)
    assert [item["name"] for item in projected["parameters"]] == [item.name for item in rsi.parameters.fields]
    assert projected["outputs"] == [
        {
            "name": item.name,
            "data_type": item.data_type.value,
            "nullable": item.nullable,
            "semantic_type": item.semantic_type,
            "dimensions": list(item.dimensions),
            "unit": item.unit,
        }
        for item in rsi.outputs
    ]

    fields = client.get("/api/v2/research/catalog/dataset-fields").json()["dataset_fields"]
    assert [item["source"] for item in fields] == sorted(item["source"] for item in fields)
    close = next(item for item in fields if item["source"] == "bar.close")
    assert close["field_name"] == "close"
    assert close["semantic_roles"] == ["NUMERIC_SERIES", "PRICE"]

    statistics = client.get("/api/v2/research/catalog/statistics").json()["statistics"]
    assert [item["statistic_type"] for item in statistics] == ["IC", "RANK_IC"]
    assert all(item["variable_semantic_roles"] == ["FACTOR_SCORE", "FACTOR_VALUE"] for item in statistics)
    universes = client.get("/api/v2/research/catalog/universes").json()
    assert universes["selection_kinds"] == ["SINGLE_INSTRUMENT", "EXPLICIT_INSTRUMENT_SET"]
    assert universes["registered_universes"] == []


def test_universe_discovery_uses_the_same_registered_authority_as_resolution(tmp_path) -> None:
    authority = _Universes()
    committed, _, _, client = _case(tmp_path, authority)
    catalog = client.get("/api/v2/research/catalog/universes").json()
    assert catalog["selection_kinds"] == [
        "SINGLE_INSTRUMENT",
        "EXPLICIT_INSTRUMENT_SET",
        "REGISTERED_POOL",
        "REGISTERED_UNIVERSE",
    ]
    assert [item["registered_id"] for item in catalog["registered_universes"]] == ["z.pool", "a.universe"]

    source = definition(committed.definition)
    registered = OnlyResearchUniverseSelection(OnlyResearchUniverseKind.REGISTERED_POOL, registered_id="z.pool")
    payload = replace(source, dataset=replace(source.dataset, universe=registered)).to_dict()
    response = client.post("/api/v2/research/definitions/resolve", json=dict(payload))
    assert response.status_code == 200
    assert response.json()["resolved_dataset_definition"]["instruments"] == ["A.XNAS", "B.XNAS"]


def test_research_api_rejects_resolution_only_registered_universe_authority(tmp_path) -> None:
    with pytest.raises(TypeError, match="must support both resolution and discovery"):
        _case(tmp_path, _ResolverOnlyUniverses())


def test_definition_dto_preserves_authoring_expression_order(tmp_path) -> None:
    committed, _, _, _ = _case(tmp_path)
    source = definition(committed.definition)
    transported = ResearchDefinitionRequestDto.model_validate(dict(source.to_dict())).to_domain()
    assert transported == source
    assert transported.schema_version == source.schema_version
    assert [item.left.to_dict() for item in transported.signals.entry.operands] == [  # type: ignore[union-attr]
        item.left.to_dict()
        for item in source.signals.entry.operands  # type: ignore[union-attr]
    ]


def test_definition_authoring_schema_excludes_internal_predicate(tmp_path) -> None:
    _, _, _, client = _case(tmp_path)
    schema = client.app.openapi()["components"]["schemas"]["ResearchCalculationTypeReferenceDto"]
    assert schema["properties"]["kind"]["enum"] == ["INDICATOR", "FACTOR", "TARGET"]


def test_definition_transport_rejects_authored_predicate(tmp_path) -> None:
    committed, _, _, client = _case(tmp_path)
    payload = deepcopy(dict(definition(committed.definition).to_dict()))
    payload["calculations"][0]["type_reference"]["kind"] = "PREDICATE"
    response = client.post("/api/v2/research/definitions/resolve", json=payload)
    assert response.status_code == 400
    assert response.json()["error"] == {
        "phase": "SCHEMA",
        "code": "RESEARCH_DEFINITION_REQUEST_INVALID",
        "path": "calculations[0].type_reference.kind",
        "detail": "HTTP request validation failed",
    }


def test_resolve_projects_domain_truth_and_exact_specification_is_run_input(tmp_path) -> None:
    committed, _, resolver, client = _case(tmp_path)
    source = definition(committed.definition)
    expected = resolver.resolve(source)
    response = client.post("/api/v2/research/definitions/resolve", json=dict(source.to_dict()))
    assert response.status_code == 200
    body = response.json()
    assert body["authoring_definition_fingerprint"] == expected.authoring_definition_fingerprint
    assert body["resolved_definition_fingerprint"] == expected.resolved_definition_fingerprint
    assert body["dataset_snapshot_fingerprint"] == expected.dataset_snapshot_fingerprint
    assert body["specification_fingerprint"] == expected.specification_fingerprint
    assert body["candidate_count"] == len(expected.candidates) == 4
    assert [item["candidate_fingerprint"] for item in body["candidates"]] == [
        item.candidate_fingerprint for item in expected.candidates
    ]
    assert [(item["instance_key"], item["output_name"]) for item in body["published_variables"]] == [
        (item.variable.instance_key, item.variable.output_name) for item in expected.published_variables
    ]
    assert OnlyResearchSpecification.from_dict(body["exact_specification"]) == expected.specification
    assert SubmitResearchRunRequest.model_validate({"specification": body["exact_specification"]})
    assert "PREDICATE" in str(body["exact_specification"])
    assert "workload" not in body and "node_fingerprints" not in str(body)


def test_definition_domain_error_preserves_authoring_path(tmp_path) -> None:
    committed, _, _, client = _case(tmp_path)
    payload = deepcopy(dict(definition(committed.definition).to_dict()))
    payload["signals"]["entry"]["operands"][1]["right"] = {
        "kind": "LITERAL",
        "data_type": "STRING",
        "value": {"type": "STRING", "value": "bad"},
    }
    response = client.post("/api/v2/research/definitions/resolve", json=payload)
    assert response.status_code == 400
    assert response.json()["error"] == {
        "phase": "EXPRESSION",
        "code": "RESEARCH_DEFINITION_COMPARISON_TYPE_INVALID",
        "path": "signals.entry.operands[1].right",
        "detail": "DECIMAL cannot compare with STRING",
    }


def test_definition_transport_errors_have_definition_ownership(tmp_path) -> None:
    committed, _, _, client = _case(tmp_path)
    payload = dict(definition(committed.definition).to_dict())
    invalid_precision = deepcopy(payload)
    invalid_precision["statistics"][0]["definition"]["numeric"]["precision"] = "38"
    cases = (
        {**payload, "unknown": True},
        {**payload, "schema_version": "1"},
        {**payload, "dataset": {**payload["dataset"], "aggregation_source": "UNKNOWN"}},
        invalid_precision,
    )
    for invalid in cases:
        response = client.post("/api/v2/research/definitions/resolve", json=invalid)
        assert response.status_code == 400
        error = response.json()["error"]
        assert error["phase"] == "SCHEMA"
        assert error["code"] == "RESEARCH_DEFINITION_REQUEST_INVALID"
        assert set(error) == {"phase", "code", "path", "detail"}
