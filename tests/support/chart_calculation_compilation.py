"""Deterministic sealed input and compile-only boundary fixtures."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from onlyalpha.application.chart_calculation import (
    OnlyChartCalculationOperationV1,
    OnlyChartCalculationRequestV1,
    only_normalize_chart_calculation,
)
from onlyalpha.application.chart_calculation_preparation import (
    OnlyChartCalculationInputPinV1,
    OnlyChartCalculationPreparationV1,
    OnlyChartCalculationRuntimeBindingReferenceV1,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority, OnlyRuntimeWorkBindingEvidence
from onlyalpha.calculation import OnlyCalculationBackendKind
from onlyalpha.canonical import only_canonical_json, only_canonical_payload
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.durable.revision import OnlyHistoricalMarketDataQueryService
from onlyalpha.research.dataset.market_data_materializer import OnlySealedMarketDataDatasetMaterializer
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1
from onlyalpha.research.run.model import OnlyResearchRunId
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.application.test_chart_calculation_admission import NOW, D, payload, witness
from tests.application.test_market_data_product import BASE, INSTRUMENT, _reference, _service
from tests.research.specification.test_calculation_publication import publication_registry

GENERATION = "b" * 64


def prepared_input(tmp_path: Path, *, period: int = 3, price_field: str = "CLOSE"):
    market = _service(tmp_path / "market", native_minutes=(1, 15))
    market.service._clock = OnlyBacktestClock(BASE + timedelta(hours=8))
    reference = _reference(market.revision_fingerprint)
    start = OnlyTimestamp.from_datetime(BASE).unix_nanos
    end = start + (period + 3) * D
    selected = market.service.plan_selection(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start,
        end_ns=end,
        bar_semantic=OnlyBarSemantic.fixed_duration(15),
    )
    market.service.acquire_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start,
        end_ns=end,
        bar_semantic=OnlyBarSemantic.fixed_duration(15),
    )
    raw = payload({"period": period, "price_field": price_field})
    raw["source_reference"] = {
        "integration_id": reference.integration_id,
        "integration_revision_fingerprint": reference.integration_revision_fingerprint,
        "expected_type_id": reference.expected_type_id,
    }
    raw["instrument_id"] = str(INSTRUMENT)
    raw["display_range"] = {"start_ns": str(start + (period - 1) * D), "end_ns": str(end)}
    catalog_witness = witness()
    intent = only_normalize_chart_calculation(OnlyChartCalculationRequestV1.from_dict(raw), catalog_witness, NOW)
    command = OnlyProductCommandId("00000000-0000-4000-8000-000000000721")
    work = OnlyResearchRunId("00000000-0000-4000-8000-000000000722")
    operation = OnlyChartCalculationOperationV1(
        command,
        command,
        intent.command_fingerprint,
        intent.intent_fingerprint,
        intent,
        catalog_witness,
        work,
        NOW,
    )
    query = OnlyHistoricalMarketDataQueryService(market.catalog, market.service._facts)
    revision = query.resolve_latest(selected.scope)
    revision, seal = query.resolve_with_seal(revision.revision_id)
    evidence = {
        "revision": revision,
        "manifest": market.catalog.load_coverage_manifest(revision.manifest_id),
        "seal": seal,
        "physical_proofs": market.catalog.load_physical_proofs(tuple(item[0] for item in revision.segment_refs)),
    }
    pin = OnlyChartCalculationInputPinV1(
        only_canonical_json(
            {
                "schema_version": 1,
                "operation_id": command.value,
                "intent_fingerprint": intent.intent_fingerprint,
                "source_reference": raw["source_reference"],
                "source_selection": selected.source_selection,
                "integration_binding_fingerprint": selected.integration_binding_fingerprint,
                "display_range": raw["display_range"],
                "scope": {
                    **only_canonical_payload(selected.scope),
                    "bar_construction": selected.scope.bar_construction.to_dict(),
                },
                "evidence": evidence,
                "runtime_generation_fingerprint": GENERATION,
                "runtime_work_id": work.value,
            }
        )
    )
    dataset = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "dataset")
    materializer = OnlySealedMarketDataDatasetMaterializer(query, dataset, dataset, lambda: NOW)
    materialized = materializer.materialize_with_lineage(pin.materialization_plan())
    binding = OnlyRuntimeWorkBindingEvidence(
        work.value,
        GENERATION,
        "NEW_WORK",
        "CHART_CALCULATION_INPUT",
        "chart-input-preparation",
        "e" * 64,
        1,
        True,
    )
    preparation = OnlyChartCalculationPreparationV1(
        command,
        4,
        1,
        command,
        NOW,
        GENERATION,
        work.value,
        "INPUT_READY",
        pin,
        materialized.snapshot.snapshot_fingerprint,
        materialized.materialization.materialization_id,
        runtime_binding_reference=OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(binding),
    )
    preparations = Mock()
    preparations.load_verified.return_value = preparation
    runtime = Mock(spec=OnlyRuntimeGenerationWorkAuthority)
    runtime.require_work_binding_evidence.return_value = binding
    runtime.require_runtime_generation.return_value = SimpleNamespace(
        runtime_generation_fingerprint=GENERATION,
        catalog_generation_fingerprint=catalog_witness.to_dict()["context"]["catalog_generation_fingerprint"],
    )
    runtime.require_historical_generation.return_value = runtime.require_runtime_generation.return_value
    compilations = Mock()
    compilations.load_verified.return_value = None
    compilations.commit_or_replay.side_effect = lambda operation, preparation, compilation: compilation
    resolver = Mock()
    resolver.resolve_calculation_publication.side_effect = resolve_publication
    return SimpleNamespace(
        operation=operation,
        preparation=preparation,
        binding=binding,
        market=market,
        dataset=dataset,
        materializer=materializer,
        materialized=materialized,
        preparations=preparations,
        runtime=runtime,
        compilations=compilations,
        resolver=resolver,
    )


def resolve_publication(generation, specification):
    """A canonical compiler fake, never a numeric executor or hosted-provenance claim."""
    registry = publication_registry()
    resolved = OnlyResearchSpecificationResolver(registry).resolve(specification)
    candidate = resolved.candidates[0]
    job = resolved.workload.direct_jobs[0]
    definition = job.calculation_graph.nodes[0].definition
    registration = registry.resolve(
        definition.kind,
        definition.type_id,
        definition.semantic_version,
        OnlyCalculationBackendKind.RESEARCH,
    )
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationImplementationBinding

    manifest = registration.implementation_manifest
    return OnlyResearchCalculationRuntimeResolutionV1(
        generation,
        specification,
        specification.specification_fingerprint,
        job,
        resolved.workload.result_plan,
        specification.calculations[0].calculation_id,
        candidate.node_fingerprints,
        (
            OnlyResearchCalculationImplementationBinding(
                job.calculation_graph.nodes[0].fingerprint, manifest.implementation_fingerprint
            ),
        ),
        manifest,
    )
