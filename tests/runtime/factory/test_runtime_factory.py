import json

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.planning import OnlyRuntimePlanner


def _plan(runtime_type: str):
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = runtime_type
    payload["cluster"]["runtime_type"] = runtime_type
    config = OnlyClusterRunConfig.from_mapping(payload, source_path="tests/fixtures/legacy_macd/cluster.json")
    return OnlyRuntimePlanner().plan(OnlyEngineId("factory-test"), (config,)).runtime_plans[0]


def test_backtest_factory_is_selected_through_runtime_assembler() -> None:
    services = only_default_engine_services()
    build = services.assembler.build(_plan("BACKTEST"))
    assert build.runtime is not None
    assert build.runtime.runtime_type == "BACKTEST"
    build.runtime.close()


def test_unimplemented_runtime_factories_return_structured_unsupported_results() -> None:
    services = only_default_engine_services()
    for runtime_type in ("PAPER", "LIVE", "SHADOW", "RESEARCH"):
        build = services.assembler.build(_plan(runtime_type))
        assert build.runtime is None
        assert build.failure_code == "UNSUPPORTED_RUNTIME_TYPE"
        assert build.failure_message == f"{runtime_type} Runtime is registered but not implemented in phase one"
