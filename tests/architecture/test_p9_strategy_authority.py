import ast
from dataclasses import fields
from pathlib import Path

from onlyalpha.cluster.pipeline import OnlyClusterPipelineResult
from onlyalpha.strategy.execution import OnlyStrategyDecision


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.append(node.module)
    return tuple(result)


def test_strategy_domain_has_no_downstream_or_provider_dependencies() -> None:
    forbidden = (
        "onlyalpha.account",
        "onlyalpha.broker",
        "onlyalpha.fee",
        "onlyalpha.execution",
        "fastapi",
        "binance",
        "onlyalpha_plugin_",
    )
    for path in Path("src/onlyalpha/strategy").glob("*.py"):
        for imported in _imports(path):
            assert not imported.startswith(forbidden), f"{path}: forbidden Strategy dependency {imported}"


def test_runtime_and_cluster_have_no_dynamic_strategy_authority() -> None:
    roots = (Path("src/onlyalpha/runtime"), Path("src/onlyalpha/cluster"))
    forbidden = (
        "OnlyStrategyCreateRequest",
        "OnlyStrategyFactory",
        "strategy_path",
        "config.strategy.config_path",
    )
    for root in roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for value in forbidden:
                assert value not in source, f"{path}: legacy Strategy authority {value}"


def test_legacy_strategy_factory_is_absent_and_config_is_fingerprint_only() -> None:
    assert not Path("src/onlyalpha/strategy/factory.py").exists()
    source = Path("src/onlyalpha/config/models.py").read_text(encoding="utf-8")
    assert "class OnlyStrategyReferenceConfig" in source
    assert "class OnlyStrategyImportConfig" not in source
    assert "strategy_path" not in source


def test_candidate_and_web_do_not_reach_trading_strategy_composition() -> None:
    composition = Path("src/onlyalpha/cluster/factory.py").read_text(encoding="utf-8") + Path(
        "src/onlyalpha/strategy/execution.py"
    ).read_text(encoding="utf-8")
    assert "candidate_fingerprint" not in composition
    for root in (Path("src/onlyalpha/api"), Path("src/onlyalpha/application")):
        if root.exists():
            for path in root.rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                assert "OnlyStrategyRevision(" not in source
                assert "OnlyStrategyMarketInputContract(" not in source


def test_backtest_and_sim_share_the_single_cluster_strategy_resolver() -> None:
    cluster = Path("src/onlyalpha/cluster/factory.py").read_text(encoding="utf-8")
    backtest = Path("src/onlyalpha/runtime/backtest/factory.py").read_text(encoding="utf-8")
    sim = Path("src/onlyalpha/runtime/sim/factory.py").read_text(encoding="utf-8")

    assert cluster.count("OnlyStrategyExecutionResolver(") == 1
    assert "components.clusters.create(" in sim
    assert "components.clusters.create(" in backtest
    assert "OnlyStrategyRevision(" not in backtest + sim


def test_no_python_callback_strategy_authoring_or_cluster_injection_surface_exists() -> None:
    assert not Path("src/onlyalpha/strategy/base.py").exists()
    assert not Path("src/onlyalpha/strategy/config.py").exists()
    assert not Path("src/onlyalpha/strategy/context.py").exists()
    cluster_tree = ast.parse(Path("src/onlyalpha/cluster/base.py").read_text(encoding="utf-8"))
    cluster = next(node for node in cluster_tree.body if isinstance(node, ast.ClassDef) and node.name == "OnlyCluster")
    constructor = next(
        node
        for node in cluster.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__init__"
    )
    parameters = {item.arg for item in constructor.args.args}
    assert "strategy" not in parameters
    assert "strategy_plan" in parameters
    for root in (Path("src"), Path("packages"), Path("examples"), Path("tests/fixtures/external_plugins")):
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "class OnlyStrategy(" not in source
            assert "(OnlyStrategy):" not in source


def test_strategy_decision_is_explicit_provider_neutral_pipeline_output() -> None:
    assert {item.name for item in fields(OnlyStrategyDecision)} == {
        "strategy_fingerprint",
        "instrument_id",
        "observation_key",
        "observation_fingerprint",
        "decision_time",
        "eligibility",
        "entry",
        "exit",
        "schema_version",
    }
    assert "strategy_decision" in {item.name for item in fields(OnlyClusterPipelineResult)}
    forbidden = {"order", "account", "broker", "capital", "quantity", "position", "risk"}
    assert forbidden.isdisjoint({item.name for item in fields(OnlyStrategyDecision)})


def test_trading_strategy_path_has_no_research_runtime_implementation_dependency() -> None:
    paths = (
        Path("src/onlyalpha/strategy/execution.py"),
        Path("src/onlyalpha/strategy/adapter.py"),
        Path("src/onlyalpha/cluster/factory.py"),
        Path("src/onlyalpha/runtime/trading/predicate.py"),
    )
    for path in paths:
        assert all(not value.startswith("onlyalpha.research") for value in _imports(path))


def test_admission_uses_verified_evidence_store_and_promotion_ignores_audit_time_for_ordering() -> None:
    admission = Path("src/onlyalpha/strategy/admission.py").read_text(encoding="utf-8")
    promotion = Path("src/onlyalpha/strategy/promotion.py").read_text(encoding="utf-8")
    postgres = Path("src/onlyalpha/persistence/postgres/strategy_store.py").read_text(encoding="utf-8")
    assert "require_verified" in admission
    assert "EquivalenceAdmissionRegistry" not in admission
    assert "ORDER BY recorded_at" not in postgres
    assert "recorded_at DESC" not in postgres
    chain_body = promotion[promotion.index("def only_verified_strategy_promotion_chain") :]
    assert ".recorded_at" not in chain_body


def test_official_freeze_and_promotion_application_composition_exists() -> None:
    source = Path("src/onlyalpha/application/strategy_authority.py").read_text(encoding="utf-8")
    assert "class OnlyStrategyFreezeApplicationService" in source
    assert "class OnlyStrategyPromotionApplicationService" in source
    assert "OnlyCalculationEquivalenceEvidenceStore" in source
    assert "OnlyResearchSemanticStoreId" in source
