from __future__ import annotations

from dataclasses import replace

from onlyalpha_runtime_generation_manager.search_worker import (
    _derive_parameter,
    _derive_symbolic,
    _resolve_parameter_research,
    _resolve_symbolic_research,
)

from onlyalpha.quant_assets import only_discover_quant_asset_providers
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.experiment import (
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchSpaceReferenceV1,
)
from onlyalpha.research.search.parameter import (
    PARAMETER_SEARCH_SPACE_KIND,
    OnlyParameterFactorSearchSpaceV1,
    only_deterministic_coarse_to_fine_implementation,
)
from onlyalpha.research.search.symbolic import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    OnlySymbolicResearchEvaluationContractV1,
    only_deterministic_enumeration_implementation,
)
from tests.research.calculation.support import snapshot
from tests.research.search.parameter.test_adaptive_parameter_search_v1 import _manifest, _policy
from tests.research.search.symbolic.support import space
from tests.research.search.symbolic.test_research_and_provenance_integration import (
    _experiment,
    _scientific_template,
)
from tests.research.specification.support import registry
from tests.research.sweep.support import definition


def test_worker_executes_real_symbolic_catalog_registry_resolver_and_algorithm(tmp_path) -> None:  # type: ignore[no-untyped-def]
    candidate, partitions = snapshot()
    dataset_root = tmp_path / "datasets"
    committed = OnlyParquetResearchDatasetSnapshotStore(dataset_root).commit(candidate, partitions)
    catalog = only_discover_quant_asset_providers()
    _public_catalog, base_space = space(max_nodes=3)
    search_space = replace(
        base_space,
        catalog_generation_fingerprint=catalog.generation_fingerprint,
    )
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(
        _scientific_template(committed.snapshot_fingerprint),
        "feature",
    )
    algorithm = only_deterministic_enumeration_implementation()
    experiment = _experiment(
        search_space.search_space_fingerprint,
        catalog.generation_fingerprint,
        committed.snapshot_fingerprint,
        evaluation.evaluation_contract_fingerprint,
    )
    result = _derive_symbolic(
        {
            "experiment": experiment.to_dict(),
            "search_space": search_space.to_dict(),
            "evaluation_contract": evaluation.to_dict(),
            "algorithm_manifest": algorithm.to_dict(),
            "dataset_store_root": str(dataset_root),
        }
    )
    assert result["catalog_generation_fingerprint"] == catalog.generation_fingerprint
    assert result["algorithm_implementation_fingerprint"] == algorithm.implementation_fingerprint
    assert result["proposals"]
    assert (
        _derive_symbolic(
            {
                "experiment": experiment.to_dict(),
                "search_space": search_space.to_dict(),
                "evaluation_contract": evaluation.to_dict(),
                "algorithm_manifest": algorithm.to_dict(),
                "dataset_store_root": str(dataset_root),
            }
        )
        == result
    )
    resolved = _resolve_symbolic_research(
        {
            "evaluation_contract": evaluation.to_dict(),
            "proposal": result["proposals"][0],  # type: ignore[index]
        }
    )
    assert resolved["specification"]
    assert resolved["candidate_fingerprint"]


def test_worker_executes_real_parameter_materialization_resolver_and_algorithm(tmp_path) -> None:  # type: ignore[no-untyped-def]
    candidate, partitions = snapshot()
    dataset_root = tmp_path / "datasets"
    committed = OnlyParquetResearchDatasetSnapshotStore(dataset_root).commit(candidate, partitions)
    catalog = only_discover_quant_asset_providers()
    search_space = OnlyParameterFactorSearchSpaceV1.from_sweep(
        catalog_generation_fingerprint=catalog.generation_fingerprint,
        sweep_definition=definition(committed.snapshot_fingerprint),
        candidate_template_node_id="momentum",
        candidate_output_name="factor_value",
        calculation_registry=registry(),
    )
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(
        _scientific_template(committed.snapshot_fingerprint),
        "feature",
    )
    policy = _policy()
    algorithm = only_deterministic_coarse_to_fine_implementation()
    experiment = replace(
        _manifest(policy),
        search_space_reference=OnlySearchSpaceReferenceV1(
            PARAMETER_SEARCH_SPACE_KIND,
            1,
            search_space.search_space_fingerprint,
        ),
        evaluation_context_reference=OnlySearchEvaluationContextReferenceV1(
            SYMBOLIC_EVALUATION_CONTRACT_KIND,
            1,
            evaluation.evaluation_contract_fingerprint,
        ),
        catalog_generation_fingerprint=catalog.generation_fingerprint,
        dataset_snapshot_fingerprint=committed.snapshot_fingerprint,
    )
    result = _derive_parameter(
        {
            "experiment": experiment.to_dict(),
            "search_space": search_space.to_dict(),
            "evaluation_contract": evaluation.to_dict(),
            "search_policy": policy.to_dict(),
            "algorithm_manifest": algorithm.to_dict(),
            "dataset_store_root": str(dataset_root),
            "evidence": [],
            "prior_decisions": [],
        }
    )
    assert result["catalog_generation_fingerprint"] == catalog.generation_fingerprint
    assert result["algorithm_implementation_fingerprint"] == algorithm.implementation_fingerprint
    assert result["decision"]
    assert (
        _derive_parameter(
            {
                "experiment": experiment.to_dict(),
                "search_space": search_space.to_dict(),
                "evaluation_contract": evaluation.to_dict(),
                "search_policy": policy.to_dict(),
                "algorithm_manifest": algorithm.to_dict(),
                "dataset_store_root": str(dataset_root),
                "evidence": [],
                "prior_decisions": [],
            }
        )
        == result
    )
    resolved = _resolve_parameter_research(
        {
            "evaluation_contract": evaluation.to_dict(),
            "proposal": result["proposals"][0],  # type: ignore[index]
        }
    )
    assert resolved["specification"]
    assert resolved["candidate_fingerprint"]
