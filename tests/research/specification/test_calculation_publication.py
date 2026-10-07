from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from onlyalpha_plugin_indicators.registration import registrations

from onlyalpha.calculation import OnlyCalculationKind, OnlyCalculationRegistry
from onlyalpha.research.specification.model import (
    OnlyResearchCalculationSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSpecification,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.research.sweep.template import (
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchTemplateInputBinding,
    OnlyResearchTemplateReference,
)
from tests.research.sweep.support import reference


def publication_specification(dataset="a" * 64, period=3):
    from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationSelectionV1

    template = OnlyResearchGraphTemplate(
        (
            OnlyResearchGraphTemplateNode(
                "sma",
                reference(OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.sma"),
                {"period": period},
                (OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference(None, "value", "bar.close")),),
            ),
        )
    )
    return OnlyResearchSpecification(
        dataset,
        (OnlyResearchCalculationSpec("average", template),),
        (),
        schema_version=3,
        purpose="CALCULATION_PUBLICATION",
        published_series=(OnlyResearchSeriesSelector("average", "sma", "value"),),
        publication=OnlyResearchCalculationPublicationSelectionV1(),
    )


def publication_registry():
    registry = OnlyCalculationRegistry()
    for item in registrations():
        registry.register(item)
    return registry


def test_publication_specification_has_exact_shape_and_resolves_without_scientific_facts():
    spec = publication_specification()
    assert set(spec.to_dict()) == {
        "schema_version",
        "purpose",
        "dataset_snapshot_fingerprint",
        "calculations",
        "published_series",
        "publication",
    }
    assert OnlyResearchSpecification.from_dict(spec.to_dict()) == spec
    resolved = OnlyResearchSpecificationResolver(publication_registry()).resolve(spec)
    workload = resolved.workload
    assert len(workload.direct_jobs) == 1 and workload.direct_jobs[0].schema_version == 2
    assert workload.sweeps == workload.statistics_plans == ()
    assert workload.result_plan.schema_version == 4
    assert workload.result_plan.publication == spec.publication
    assert resolved.published_series[0].candidate_fingerprint is None
    assert set(workload.result_plan.to_dict()) == {
        "schema_version",
        "dataset_snapshot_fingerprint",
        "calculations",
        "published_series",
        "publication",
    }


@pytest.mark.parametrize(
    "field", ("statistics", "evidence", "candidate_calculation_id", "signals", "targets", "eligibility")
)
def test_publication_specification_rejects_scientific_fields(field):
    payload = deepcopy(publication_specification().to_dict())
    payload[field] = []
    with pytest.raises(ValueError):
        OnlyResearchSpecification.from_dict(payload)


@pytest.mark.parametrize("period", (1, 7, 31))
def test_publication_does_not_enter_calculation_identity(period):
    from onlyalpha.research.job.plan import OnlyResearchJobPlan

    resolved = OnlyResearchSpecificationResolver(publication_registry()).resolve(
        publication_specification(period=period)
    )
    job = resolved.workload.direct_jobs[0]
    assert (
        OnlyResearchJobPlan(job.dataset_snapshot_fingerprint, job.calculation_graph).calculation_fingerprint
        == job.calculation_fingerprint
    )


def test_publication_rejects_unknown_output_and_non_readiness_backend():
    resolver = OnlyResearchSpecificationResolver(publication_registry())
    spec = publication_specification()
    with pytest.raises(ValueError):
        resolver.resolve(replace(spec, published_series=(OnlyResearchSeriesSelector("average", "sma", "missing"),)))
    node = spec.calculations[0].graph_template.nodes[0]
    template = OnlyResearchGraphTemplate(
        (replace(node, type_reference=reference(OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.ema")),)
    )
    with pytest.raises(ValueError):
        resolver.resolve(replace(spec, calculations=(OnlyResearchCalculationSpec("average", template),)))


def test_legacy_import_does_not_eagerly_load_hosted_publication_resolution():
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from onlyalpha.research import OnlyResearchSpecification; assert 'onlyalpha.research.run.calculation_resolution' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_publication_rejects_multi_node_graph():
    spec = publication_specification()
    node = spec.calculations[0].graph_template.nodes[0]
    template = OnlyResearchGraphTemplate((node, replace(node, template_node_id="other", parameters={"period": 7})))
    with pytest.raises(ValueError, match="TIME_SERIES"):
        OnlyResearchSpecificationResolver(publication_registry()).resolve(
            replace(spec, calculations=(OnlyResearchCalculationSpec("average", template),))
        )


@pytest.mark.parametrize("missing_method", (False, True))
def test_resolution_checks_readiness_method_and_executes_no_values(missing_method):
    from onlyalpha.calculation import OnlyCalculationBackendKind

    class NoExecution:
        def execute(self, *args):
            raise AssertionError("resolver executed values")

        def execute_with_readiness(self, *args):
            raise AssertionError("resolver executed readiness")

    provider = object() if missing_method else NoExecution()
    registry = OnlyCalculationRegistry()
    for item in registrations():
        if (
            item.type_definition.type_id == "onlyalpha.indicator.sma"
            and item.backend is OnlyCalculationBackendKind.RESEARCH
        ):
            item = replace(item, provider=provider)
        registry.register(item)
    resolver = OnlyResearchSpecificationResolver(registry)
    if missing_method:
        with pytest.raises(ValueError, match="READINESS_BACKEND_UNAVAILABLE"):
            resolver.resolve(publication_specification())
    else:
        assert resolver.resolve(publication_specification()).workload.result_plan.schema_version == 4


def test_publication_rejects_non_time_series_graph_before_backend_resolution(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from onlyalpha.calculation import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition

    spec = publication_specification()
    resolver = OnlyResearchSpecificationResolver(publication_registry())
    base = resolver.resolve(spec)
    definition = base.workload.direct_jobs[0].calculation_graph.nodes[0].definition
    from onlyalpha.calculation.definition import CALCULATION_EXECUTION_SHAPE_EXTENSION

    cross = replace(
        definition, extensions={**definition.extensions, CALCULATION_EXECUTION_SHAPE_EXTENSION: "CROSS_SECTION"}
    )
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(cross),))
    monkeypatch.setattr(
        resolver._materializer,
        "materialize",
        Mock(return_value=SimpleNamespace(graph=graph, node_fingerprints={"sma": graph.nodes[0].fingerprint})),
    )
    with pytest.raises(ValueError, match="READINESS_GRAPH_UNSUPPORTED"):
        resolver.resolve(spec)


@pytest.mark.parametrize(
    "version,pinned",
    (
        (1, "0feeec97f7ce6e7b04e884514c75b233b843e7f6d761bff85f7aa81d640a9c21"),
        (2, "090b3eb02ad41b919cd4d9b4ff9bcf19b8dd554428b495a448c0426b6d4aa9fd"),
    ),
)
def test_legacy_specification_payload_identity_and_exact_fields_are_unchanged(version, pinned):
    from tests.research.specification.support import scientific_specification, specification

    spec = specification() if version == 1 else scientific_specification()
    assert spec.specification_fingerprint == pinned
    assert OnlyResearchSpecification.from_dict(spec.to_dict()).to_dict() == spec.to_dict()
    for field in ("purpose", "published_series", "publication"):
        with pytest.raises(ValueError):
            OnlyResearchSpecification.from_dict({**spec.to_dict(), field: None})
