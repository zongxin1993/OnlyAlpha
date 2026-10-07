from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.support.chart_calculation_compilation import GENERATION, prepared_input, resolve_publication


def test_compiler_has_fixed_shape_and_preserves_admitted_defaults(tmp_path: Path) -> None:
    from onlyalpha.application.chart_calculation_compilation import only_chart_calculation_specification_v3
    from onlyalpha.research.specification.model import OnlyResearchSpecification

    system = prepared_input(tmp_path)
    spec = only_chart_calculation_specification_v3(system.operation, system.preparation)
    assert spec.schema_version == 3 and spec.purpose == "CALCULATION_PUBLICATION"
    assert spec.dataset_snapshot_fingerprint == system.preparation.dataset_snapshot_fingerprint
    (calculation,) = spec.calculations
    (node,) = calculation.graph_template.nodes
    assert calculation.calculation_id == "chart_calculation" and calculation.sweep_dimensions == ()
    assert node.template_node_id == "indicator" and node.input_bindings == ()
    assert dict(node.parameters) == system.operation.intent.to_dict()["calculation"]["parameters"]
    assert spec.published_series[0].to_dict() == {
        "calculation_id": "chart_calculation",
        "template_node_id": "indicator",
        "output_name": "value",
    }
    assert spec.statistics == () and spec.evidence is None
    assert spec.publication.to_dict() == {
        "artifact_profile": "RESEARCH_CALCULATION_V2",
        "calculation_result_schema_version": 2,
        "execution_evidence_schema_version": 2,
        "readiness_contract_version": 1,
    }
    assert OnlyResearchSpecification.from_dict(spec.to_dict()) == spec


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "MATERIALIZING_INPUT"),
        ("operation_id", None),
        ("input_pin", None),
        ("dataset_snapshot_fingerprint", None),
        ("dataset_materialization_id", None),
        ("runtime_work_id", "foreign"),
        ("runtime_binding_reference", None),
    ],
)
def test_compiler_rejects_incomplete_preparation(tmp_path: Path, field: str, value: object) -> None:
    from onlyalpha.application.chart_calculation_compilation import only_chart_calculation_specification_v3

    system = prepared_input(tmp_path)
    # Simulate a malformed boundary response without weakening the production constructor.
    from dataclasses import fields
    from types import SimpleNamespace

    raw = {item.name: getattr(system.preparation, item.name) for item in fields(system.preparation)}
    raw[field] = value
    with pytest.raises(ValueError):
        only_chart_calculation_specification_v3(system.operation, SimpleNamespace(**raw))


def test_relation_round_trip_and_complete_fingerprint(tmp_path: Path) -> None:
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1

    system = prepared_input(tmp_path)
    value = compilation(system)
    raw = value.to_dict()
    assert OnlyChartCalculationCompilationV1.from_dict(json.loads(json.dumps(raw, indent=2))) == value
    assert OnlyChartCalculationCompilationV1.from_dict(dict(reversed(list(raw.items())))) == value
    assert len(value.compilation_fingerprint) == 64
    assert "created_at" not in raw and "accepted_at" not in raw
    value.verify_operation_preparation(system.operation, system.preparation)
    assert (
        replace(value, input_preparation_revision=value.input_preparation_revision + 1).compilation_fingerprint
        != value.compilation_fingerprint
    )


def compilation(system):
    from onlyalpha.application.chart_calculation_compilation import (
        OnlyChartCalculationCompilationV1,
        only_chart_calculation_specification_v3,
    )

    operation, preparation = system.operation, system.preparation
    specification = only_chart_calculation_specification_v3(operation, preparation)
    return OnlyChartCalculationCompilationV1(
        operation.operation_id,
        operation.intent_fingerprint,
        operation.catalog_witness.fingerprint,
        preparation.revision,
        preparation.fence,
        preparation.input_selection_fingerprint,
        preparation.dataset_snapshot_fingerprint,
        preparation.dataset_materialization_id,
        preparation.runtime_generation_fingerprint,
        preparation.runtime_work_id,
        preparation.runtime_binding_reference,
        operation.catalog_witness.capability.implementation_fingerprint,
        specification,
        resolve_publication(preparation.runtime_generation_fingerprint, specification),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("input_preparation_revision", True),
        ("input_preparation_revision", 0),
        ("input_preparation_fence", True),
        ("input_preparation_fence", 5),
        ("operation_id", "foreign"),
        ("intent_fingerprint", "A" * 64),
        ("catalog_witness_fingerprint", "short"),
        ("input_selection_fingerprint", 3),
        ("dataset_snapshot_fingerprint", "f" * 64),
        ("dataset_materialization_id", "untyped"),
        ("runtime_generation_fingerprint", "f" * 64),
        ("runtime_work_id", "foreign"),
        ("runtime_binding_reference", None),
        ("catalog_implementation_fingerprint", "f" * 64),
        ("specification", {}),
        ("resolution", {}),
        ("unexpected", None),
    ],
)
def test_relation_rejects_malformed_shape(tmp_path: Path, field: str, value: object) -> None:
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1

    raw = compilation(prepared_input(tmp_path)).to_dict()
    raw[field] = value
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        OnlyChartCalculationCompilationV1.from_dict(raw)


@pytest.mark.parametrize(
    "field",
    [
        "operation_id",
        "intent_fingerprint",
        "catalog_witness_fingerprint",
        "input_preparation_revision",
        "input_preparation_fence",
        "input_selection_fingerprint",
        "dataset_snapshot_fingerprint",
        "dataset_materialization_id",
        "runtime_generation_fingerprint",
        "runtime_work_id",
        "specification",
        "resolution",
    ],
)
def test_relation_requires_every_context_dimension(tmp_path: Path, field: str) -> None:
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1

    raw = compilation(prepared_input(tmp_path)).to_dict()
    raw.pop(field)
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        OnlyChartCalculationCompilationV1.from_dict(raw)


@pytest.mark.parametrize(
    "field",
    [
        "operation_id",
        "intent_fingerprint",
        "catalog_witness_fingerprint",
        "input_preparation_revision",
        "input_preparation_fence",
        "input_selection_fingerprint",
        "dataset_materialization_id",
    ],
)
def test_complete_different_occurrence_cannot_be_replayed(tmp_path: Path, field: str) -> None:
    from onlyalpha.application.product_command_receipt import OnlyProductCommandId

    system = prepared_input(tmp_path)
    original = compilation(system)
    replacements = {
        "operation_id": OnlyProductCommandId("00000000-0000-4000-8000-000000000729"),
        "intent_fingerprint": "f" * 64,
        "catalog_witness_fingerprint": "f" * 64,
        "input_preparation_revision": 5,
        "input_preparation_fence": 2,
        "input_selection_fingerprint": "f" * 64,
        "dataset_materialization_id": "dataset-materialization:" + "f" * 64,
    }
    different = replace(original, **{field: replacements[field]})
    assert different.compilation_fingerprint != original.compilation_fingerprint
    with pytest.raises(ValueError, match="CHART_SPECIFICATION_COMPILATION_CONFLICT"):
        different.verify_operation_preparation(system.operation, system.preparation)


@pytest.mark.parametrize(
    "path,value",
    [
        (("runtime_binding_reference", "binding_kind"), "EXACT"),
        (("runtime_binding_reference", "binding_owner"), "OTHER"),
        (("runtime_binding_reference", "binding_sequence"), True),
        (("runtime_binding_reference", "binding_event_fingerprint"), "bad"),
        (("resolution", "specification_fingerprint"), "f" * 64),
        (("resolution", "job_plan", "schema_version"), 1),
        (("resolution", "job_plan", "publication", "readiness_contract_version"), True),
        (("resolution", "result_plan", "schema_version"), 3),
        (("resolution", "calculation_id"), "other"),
        (("resolution", "node_fingerprints"), {}),
        (("resolution", "implementation_manifest", "backend_kind"), "TRADING"),
        (("resolution", "implementation_manifest", "implementation_fingerprint"), "f" * 64),
        (("resolution", "research_implementation_bindings"), []),
    ],
)
def test_nested_relation_mutations_fail_closed(tmp_path: Path, path: tuple[str, ...], value: object) -> None:
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1

    raw = compilation(prepared_input(tmp_path)).to_dict()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        OnlyChartCalculationCompilationV1.from_dict(raw)


def test_duplicate_implementation_owner_is_not_relation_proof(tmp_path: Path) -> None:
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1

    raw = compilation(prepared_input(tmp_path)).to_dict()
    bindings = raw["resolution"]["research_implementation_bindings"]
    bindings.append(dict(bindings[0]))
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        OnlyChartCalculationCompilationV1.from_dict(raw)


def service(system, **overrides):
    from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationService

    return OnlyChartCalculationCompilationService(
        **{
            "preparations": system.preparations,
            "datasets": system.dataset,
            "materializations": system.dataset,
            "runtime_generations": system.runtime,
            "resolver": system.resolver,
            "compilations": system.compilations,
            **overrides,
        }
    )


def test_service_compiles_exact_generation_then_rechecks_before_commit(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    result = service(system).compile(system.operation)
    assert result == compilation(system)
    system.resolver.resolve_calculation_publication.assert_called_once_with(GENERATION, result.specification)
    assert system.preparations.load_verified.call_count == 2
    assert system.runtime.require_work_binding_evidence.call_count == 2
    system.compilations.commit_or_replay.assert_called_once_with(system.operation, system.preparation, result)
    system.preparations.claim.assert_not_called()
    system.preparations.fail.assert_not_called()
    system.runtime.bind_new_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()


def test_historical_replay_survives_inactivity_and_host_unavailability(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    existing = compilation(system)
    system.compilations.load_verified.return_value = existing
    system.runtime.require_work_binding_evidence.return_value = replace(system.binding, active=False)
    system.runtime.require_runtime_generation.side_effect = AssertionError("replay consulted current eligibility")
    system.resolver.resolve_calculation_publication.side_effect = AssertionError("replay recompiled")
    system.materializer.materialize_with_lineage = lambda *args: pytest.fail("replay materialized input")
    assert service(system).compile(system.operation) == existing
    system.compilations.commit_or_replay.assert_not_called()


def test_inactive_binding_cannot_create_first_compilation(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.runtime.require_work_binding_evidence.return_value = replace(system.binding, active=False)
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_INACTIVE"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize("state", [None, "MATERIALIZING_INPUT", "FAILED"])
def test_non_ready_has_no_compiler_or_store_side_effect(tmp_path: Path, state: str | None) -> None:
    system = prepared_input(tmp_path)
    if state is None:
        system.preparations.load_verified.return_value = None
    else:
        system.preparations.load_verified.return_value = replace(
            system.preparation,
            state="MATERIALIZING_INPUT",
            input_pin=None,
            dataset_snapshot_fingerprint=None,
            dataset_materialization_id=None,
        )
        if state == "FAILED":
            from onlyalpha.application.runtime_generation import OnlyRuntimeWorkAdmissionClosureEvidence

            system.preparations.load_verified.return_value = replace(
                system.preparations.load_verified.return_value,
                state="FAILED",
                failure_code="CHART_SEALED_COVERAGE_UNAVAILABLE",
                failure_decision="CHART_SEALED_COVERAGE_UNAVAILABLE",
                runtime_closure_reference=OnlyRuntimeWorkAdmissionClosureEvidence(
                    system.binding.work_id,
                    GENERATION,
                    "CHART_CALCULATION_INPUT",
                    "CHART_SEALED_COVERAGE_UNAVAILABLE",
                    "chart",
                    "f" * 64,
                    2,
                ),
            )
    with pytest.raises(ValueError, match="CHART_INPUT_NOT_READY"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("work_id", "foreign"),
        ("runtime_generation_fingerprint", "c" * 64),
        ("binding_kind", "EXACT"),
        ("binding_owner", "OTHER"),
        ("binding_event_fingerprint", "f" * 64),
        ("binding_sequence", 2),
        ("binding_actor", "foreign"),
    ],
)
def test_wrong_runtime_binding_never_compiles(tmp_path: Path, field: str, value: object) -> None:
    system = prepared_input(tmp_path)
    changes = {field: value}
    if field == "binding_kind":
        changes["binding_owner"] = None
    system.runtime.require_work_binding_evidence.return_value = replace(system.binding, **changes)
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_CONFLICT"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_lost_preparation_revision_before_commit_writes_nothing(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.preparations.load_verified.side_effect = [system.preparation, replace(system.preparation, revision=5)]
    with pytest.raises(ValueError, match="CHART_SPECIFICATION_COMPILATION_CONFLICT"):
        service(system).compile(system.operation)
    system.compilations.commit_or_replay.assert_not_called()


def test_released_binding_before_commit_writes_nothing(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.runtime.require_work_binding_evidence.side_effect = [system.binding, replace(system.binding, active=False)]
    with pytest.raises(ValueError, match="CHART_RUNTIME_BINDING_INACTIVE"):
        service(system).compile(system.operation)
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize(
    "exception,code",
    [
        (ValueError("RUNTIME_WORK_GENERATION_UNBOUND"), "CHART_RUNTIME_BINDING_CONFLICT"),
        (RuntimeError("RUNTIME_GENERATION_WORK_AUTHORITY_UNAVAILABLE"), "CHART_EXECUTION_GENERATION_UNAVAILABLE"),
    ],
)
def test_missing_or_unavailable_runtime_proof_is_not_absence(tmp_path: Path, exception: Exception, code: str) -> None:
    system = prepared_input(tmp_path)
    system.runtime.require_work_binding_evidence.side_effect = exception
    with pytest.raises(ValueError, match=code):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize("price_field", ["CLOSE", "VOLUME"])
def test_exact_registered_compiler_owns_implicit_source_selection(tmp_path: Path, price_field: str) -> None:
    system = prepared_input(tmp_path, price_field=price_field)
    value = compilation(system)
    assert value.specification.calculations[0].graph_template.nodes[0].input_bindings == ()
    (node,) = value.resolution.calculation_graph.nodes
    assert node.definition.input_bindings["value"].source == "bar." + price_field.lower()


@pytest.mark.parametrize("boundary", ["datasets", "materializations"])
@pytest.mark.parametrize("exception", [FileNotFoundError("missing"), ValueError("corrupt")])
def test_missing_input_authority_is_not_compilation_absence(
    tmp_path: Path, boundary: str, exception: Exception
) -> None:
    from unittest.mock import Mock

    system = prepared_input(tmp_path)
    fake = Mock()
    fake.load_verified_table.side_effect = exception
    fake.load_materialization.side_effect = exception
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        service(system, **{boundary: fake}).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_snapshot_fingerprint", "f" * 64),
        ("materializer_id", "foreign"),
        ("materializer_version", "2"),
        ("request_fingerprint", "f" * 64),
        ("market_data_revision_bindings", ()),
        ("materialization_id", "dataset-materialization:" + "f" * 64),
    ],
)
def test_materialization_requires_full_expected_lineage(tmp_path: Path, field: str, value: object) -> None:
    from unittest.mock import Mock

    from onlyalpha.research.dataset.lineage import OnlyDatasetMaterialization, only_dataset_materialization_id

    system = prepared_input(tmp_path)
    original = system.materialized.materialization
    if field == "market_data_revision_bindings":
        value = (replace(original.market_data_revision_bindings[0], source_id="foreign"),)
    changes = {field: value}
    # Recompute a complete different identity; correct self-hashes are not ownership.
    if field != "materialization_id":
        semantic = original.semantic_payload() | changes
        changes["materialization_id"] = only_dataset_materialization_id(
            semantic["dataset_snapshot_fingerprint"],
            semantic["market_data_revision_bindings"],
            semantic["materializer_id"],
            semantic["materializer_version"],
            semantic["request_fingerprint"],
        )
        different = replace(original, **changes)
    else:
        # The owning loader should reject malformed content; verify defense at the consumer too.
        from types import SimpleNamespace

        different = SimpleNamespace(
            **{name: getattr(original, name) for name in OnlyDatasetMaterialization.__dataclass_fields__} | changes
        )
    materializations = Mock()
    materializations.load_materialization.return_value = different
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        service(system, materializations=materializations).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize("variant", ["duplicate", "revision", "instrument", "kind", "fingerprint"])
def test_revision_binding_is_exact_and_unique(tmp_path: Path, variant: str) -> None:
    from unittest.mock import Mock

    from onlyalpha.research.dataset.lineage import only_dataset_materialization_id

    system = prepared_input(tmp_path)
    original = system.materialized.materialization
    (binding,) = original.market_data_revision_bindings
    mutations = {
        "revision": {"revision_id": "foreign"},
        "instrument": {"instrument_id": "OTHER.TEST"},
        "kind": {"data_kind": "TICK"},
        "fingerprint": {"revision_fingerprint": "f" * 64},
    }
    bindings = (binding, binding) if variant == "duplicate" else (replace(binding, **mutations[variant]),)
    different = replace(
        original,
        market_data_revision_bindings=bindings,
        materialization_id=only_dataset_materialization_id(
            original.dataset_snapshot_fingerprint,
            bindings,
            original.materializer_id,
            original.materializer_version,
            original.request_fingerprint,
        ),
    )
    materializations = Mock()
    materializations.load_materialization.return_value = different
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        service(system, materializations=materializations).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_corrupt_existing_compilation_is_never_rebuilt(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.compilations.load_verified.side_effect = ValueError("CHART_COMPILATION_RELATION_CORRUPT")
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_complete_different_existing_compilation_is_never_overwritten(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.compilations.load_verified.return_value = replace(compilation(system), input_preparation_revision=5)
    with pytest.raises(ValueError, match="CHART_SPECIFICATION_COMPILATION_CONFLICT"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_storage_unknown_and_control_signals_propagate(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.compilations.commit_or_replay.side_effect = OSError("commit unknown")
    with pytest.raises(OSError, match="commit unknown"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.side_effect = KeyboardInterrupt
    system.compilations.commit_or_replay.reset_mock()
    with pytest.raises(KeyboardInterrupt):
        service(system).compile(system.operation)
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize("mutation", ["generation", "specification", "implementation"])
def test_complete_different_host_response_is_rejected(tmp_path: Path, mutation: str) -> None:
    system = prepared_input(tmp_path)

    def wrong(generation, specification):
        if mutation == "generation":
            generation = "f" * 64
        if mutation == "specification":
            specification = replace(specification, dataset_snapshot_fingerprint="f" * 64)
        resolved = resolve_publication(generation, specification)
        if mutation == "implementation":
            from onlyalpha.research.calculation.execution import OnlyResearchCalculationImplementationBinding

            manifest = replace(resolved.implementation_manifest, entrypoint_identity="foreign:backend")
            resolved = replace(
                resolved,
                implementation_manifest=manifest,
                research_implementation_bindings=(
                    OnlyResearchCalculationImplementationBinding(
                        resolved.calculation_graph.nodes[0].fingerprint, manifest.implementation_fingerprint
                    ),
                ),
            )
        return resolved

    system.resolver.resolve_calculation_publication.side_effect = wrong
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        service(system).compile(system.operation)
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize(
    "kind,code",
    [
        ("unavailable", "CHART_EXECUTION_GENERATION_UNAVAILABLE"),
        ("capability", "CHART_READINESS_CAPABILITY_UNAVAILABLE"),
        ("mismatch", "CHART_COMPILATION_RELATION_CORRUPT"),
    ],
)
def test_expected_host_failures_are_stable_and_non_mutating(tmp_path: Path, kind: str, code: str) -> None:
    from onlyalpha.application.search_generation_execution import (
        OnlyHistoricalGenerationCapabilityUnsupported,
        OnlyHistoricalGenerationExecutionMismatch,
        OnlyHistoricalGenerationUnavailable,
    )

    system = prepared_input(tmp_path)
    exceptions = {
        "unavailable": OnlyHistoricalGenerationUnavailable,
        "capability": OnlyHistoricalGenerationCapabilityUnsupported,
        "mismatch": OnlyHistoricalGenerationExecutionMismatch,
    }
    system.resolver.resolve_calculation_publication.side_effect = exceptions[kind]("fault")
    with pytest.raises(ValueError, match=code):
        service(system).compile(system.operation)
    system.compilations.commit_or_replay.assert_not_called()
    system.preparations.fail.assert_not_called()
    system.runtime.release_work.assert_not_called()


def test_compile_entry_does_not_accept_caller_owned_graph_or_refs(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    boundary = service(system)
    with pytest.raises(TypeError):
        boundary.compile(system.operation, runtime_generation_fingerprint="f" * 64)
    with pytest.raises(ValueError):
        boundary.compile(system.operation.intent.to_dict())
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_specification_and_calculation_identity_follow_only_canonical_inputs(tmp_path: Path) -> None:
    system = prepared_input(tmp_path / "close")
    close = compilation(system)
    other_period = compilation(prepared_input(tmp_path / "period", period=4))
    volume = compilation(prepared_input(tmp_path / "volume", price_field="VOLUME"))
    # Another fixture acquisition legitimately has a different immutable Revision.
    # Identity equality requires the same exact pinned input, not merely equal Bars.
    same = compilation(system)
    assert close == same
    assert close.specification_fingerprint != other_period.specification_fingerprint
    assert close.graph_fingerprint != other_period.graph_fingerprint
    assert close.calculation_fingerprint != other_period.calculation_fingerprint
    assert close.graph_fingerprint != volume.graph_fingerprint
    assert close.calculation_fingerprint != volume.calculation_fingerprint
    from onlyalpha.research.job.plan import OnlyResearchJobPlan

    legacy_job = OnlyResearchJobPlan(close.dataset_snapshot_fingerprint, close.resolution.calculation_graph)
    assert legacy_job.calculation_fingerprint == close.calculation_fingerprint


@pytest.mark.parametrize("mutation", ["source_reference", "intent", "generation", "owner", "work"])
def test_preparation_pin_proves_full_operation_context(tmp_path: Path, mutation: str) -> None:
    from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationInputPinV1
    from onlyalpha.application.product_command_receipt import OnlyProductCommandId
    from onlyalpha.canonical import only_canonical_json

    system = prepared_input(tmp_path)
    raw = system.preparation.input_pin.to_dict()
    if mutation == "source_reference":
        raw["source_reference"]["expected_type_id"] = "foreign"
    elif mutation == "intent":
        raw["intent_fingerprint"] = "f" * 64
    elif mutation == "generation":
        raw["runtime_generation_fingerprint"] = "f" * 64
    elif mutation == "owner":
        raw["operation_id"] = OnlyProductCommandId("00000000-0000-4000-8000-000000000729").value
    else:
        raw["runtime_work_id"] = OnlyProductCommandId("00000000-0000-4000-8000-000000000729").value
    different = OnlyChartCalculationInputPinV1(only_canonical_json(raw))
    system.preparations.load_verified.return_value = replace(system.preparation, input_pin=different)
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_catalog_of_first_compilation_must_match_frozen_admission(tmp_path: Path) -> None:
    from types import SimpleNamespace

    system = prepared_input(tmp_path)
    system.runtime.require_runtime_generation.return_value = SimpleNamespace(
        runtime_generation_fingerprint=GENERATION,
        catalog_generation_fingerprint="f" * 64,
    )
    with pytest.raises(ValueError, match="CHART_EXECUTION_GENERATION_UNAVAILABLE"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_unexpected_resolver_bug_is_not_definitive_failure(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.resolver.resolve_calculation_publication.side_effect = ValueError("unclassified bug")
    with pytest.raises(ValueError, match="unclassified bug"):
        service(system).compile(system.operation)
    system.compilations.commit_or_replay.assert_not_called()
    system.preparations.fail.assert_not_called()


def test_exact_dataset_physical_verification_is_required_even_on_replay(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.compilations.load_verified.return_value = compilation(system)
    snapshot = system.materialized.snapshot
    (partition,) = snapshot.partitions
    target = system.dataset._target(snapshot.snapshot_fingerprint) / partition.relative_path
    target.write_bytes(b"corrupt physical input")
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_dataset_helper_preserves_existing_input_identity_formula(tmp_path: Path) -> None:
    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.research.dataset.market_data_materializer import only_sealed_market_data_input_fingerprints

    system = prepared_input(tmp_path)
    pin = system.preparation.input_pin
    plan = pin.materialization_plan()
    scope = pin.scope
    evidence = pin.to_dict()["evidence"]
    bindings = (
        (
            scope.instrument_id,
            scope.bar_construction.fingerprint,
            evidence["revision"]["fingerprint"],
            evidence["seal"]["seal_id"],
        ),
    )
    construction, request = only_sealed_market_data_input_fingerprints(plan, bindings)
    assert construction == only_canonical_fingerprint(bindings)
    assert request == only_canonical_fingerprint(
        {
            "definition": plan.definition,
            "scopes": plan.scopes,
            "constructions": tuple(item.fingerprint for item in plan.constructions),
        }
    )
    assert construction == system.materialized.snapshot.construction_fingerprint
    assert request == system.materialized.materialization.request_fingerprint


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "foreign"),
        ("instrument_id", "OTHER.TEST"),
        ("data_version", "foreign"),
        ("plugin_id", "foreign"),
        ("plugin_version", "2"),
        ("resolved_ranges", ()),
        ("observed_ranges", ()),
        ("source_metadata", {}),
    ],
)
def test_snapshot_provenance_is_not_optional_input_proof(tmp_path: Path, field: str, value: object) -> None:
    from unittest.mock import Mock

    from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset

    system = prepared_input(tmp_path)
    verified = system.dataset.load_verified_table(system.preparation.dataset_snapshot_fingerprint)
    (provenance,) = verified.snapshot.provenance
    different = replace(verified.snapshot, provenance=(replace(provenance, **{field: value}),))
    datasets = Mock()
    datasets.load_verified_table.return_value = OnlyVerifiedResearchDataset(different, verified.table)
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        service(system, datasets=datasets).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


@pytest.mark.parametrize("variant", ["missing", "duplicate", "construction", "snapshot"])
def test_snapshot_coverage_and_construction_are_exact(tmp_path: Path, variant: str) -> None:
    from unittest.mock import Mock

    from onlyalpha.research.dataset.identity import only_snapshot_fingerprint
    from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset

    system = prepared_input(tmp_path)
    verified = system.dataset.load_verified_table(system.preparation.dataset_snapshot_fingerprint)
    snapshot = verified.snapshot
    if variant == "missing":
        different = replace(snapshot, provenance=())
    elif variant == "duplicate":
        different = replace(snapshot, provenance=snapshot.provenance * 2)
    else:
        construction = "f" * 64 if variant == "construction" else snapshot.construction_fingerprint
        content = "f" * 64 if variant == "snapshot" else snapshot.content_fingerprint
        fingerprint = only_snapshot_fingerprint(
            snapshot.definition,
            snapshot.dataset_schema,
            content,
            snapshot.row_count,
            construction,
        )
        different = replace(
            snapshot,
            construction_fingerprint=construction,
            content_fingerprint=content,
            snapshot_fingerprint=fingerprint,
        )
    datasets = Mock()
    datasets.load_verified_table.return_value = OnlyVerifiedResearchDataset(different, verified.table)
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        service(system, datasets=datasets).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_second_exact_generation_is_not_substituted_by_current_generation(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from onlyalpha.application.chart_calculation_preparation import (
        OnlyChartCalculationInputPinV1,
        OnlyChartCalculationRuntimeBindingReferenceV1,
    )
    from onlyalpha.canonical import only_canonical_json

    system = prepared_input(tmp_path)
    generation = "2" * 64
    raw = system.preparation.input_pin.to_dict()
    raw["runtime_generation_fingerprint"] = generation
    binding = replace(system.binding, runtime_generation_fingerprint=generation)
    preparation = replace(
        system.preparation,
        runtime_generation_fingerprint=generation,
        input_pin=OnlyChartCalculationInputPinV1(only_canonical_json(raw)),
        runtime_binding_reference=OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(binding),
    )
    system.preparations.load_verified.return_value = preparation
    system.runtime.require_work_binding_evidence.return_value = binding
    system.runtime.require_runtime_generation.return_value = SimpleNamespace(
        runtime_generation_fingerprint=generation,
        catalog_generation_fingerprint=system.operation.catalog_witness.to_dict()["context"][
            "catalog_generation_fingerprint"
        ],
    )
    result = service(system).compile(system.operation)
    assert result.runtime_generation_fingerprint == generation
    system.resolver.resolve_calculation_publication.assert_called_once_with(generation, result.specification)
    system.runtime.require_new_work_generation.assert_not_called()


def test_application_reads_no_current_registry_and_executes_no_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    from onlyalpha_plugin_indicators.research import OnlyOfficialResearchIndicatorBackend

    from onlyalpha.calculation import OnlyCalculationRegistry

    system = prepared_input(tmp_path)
    expected = compilation(system)
    system.resolver.resolve_calculation_publication.side_effect = None
    system.resolver.resolve_calculation_publication.return_value = expected.resolution
    no_current = Mock(side_effect=AssertionError("application consulted current Registry"))
    no_numeric = Mock(side_effect=AssertionError("application executed values"))
    monkeypatch.setattr(OnlyCalculationRegistry, "resolve", no_current)
    monkeypatch.setattr(OnlyOfficialResearchIndicatorBackend, "execute", no_numeric)
    monkeypatch.setattr(OnlyOfficialResearchIndicatorBackend, "execute_with_readiness", no_numeric)
    assert service(system).compile(system.operation) == expected
    no_current.assert_not_called()
    no_numeric.assert_not_called()


@pytest.mark.parametrize("method", ["require_work_binding_evidence", "require_runtime_generation"])
def test_unclassified_runtime_error_is_not_rewritten(tmp_path: Path, method: str) -> None:
    system = prepared_input(tmp_path)
    getattr(system.runtime, method).side_effect = ValueError("RUNTIME_GENERATION_UNDOCUMENTED")
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_UNDOCUMENTED"):
        service(system).compile(system.operation)
    system.compilations.commit_or_replay.assert_not_called()
    system.preparations.fail.assert_not_called()


@pytest.mark.parametrize("method", ["require_work_binding_evidence", "require_runtime_generation"])
def test_expected_runtime_unavailability_preserves_preparation(tmp_path: Path, method: str) -> None:
    system = prepared_input(tmp_path)
    getattr(system.runtime, method).side_effect = ValueError("RUNTIME_GENERATION_UNAVAILABLE")
    with pytest.raises(ValueError, match="CHART_EXECUTION_GENERATION_UNAVAILABLE"):
        service(system).compile(system.operation)
    system.compilations.commit_or_replay.assert_not_called()
    system.preparations.fail.assert_not_called()
    system.runtime.release_work.assert_not_called()


def test_missing_whole_preparation_context_is_a_typed_error(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    system.preparations.load_verified.return_value = {}
    with pytest.raises(ValueError, match="CHART_INPUT_EVIDENCE_CORRUPT"):
        service(system).compile(system.operation)
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()
