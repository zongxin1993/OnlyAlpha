import json

from onlyalpha.application.run import OnlyEngineRunService
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.cluster.factory import OnlyClusterFactory
from onlyalpha.config import OnlyRunConfig
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.factor.factory import OnlyFactorFactory
from onlyalpha.indicator import only_default_indicator_factories
from onlyalpha.output import OnlyRuntimeResultExporter
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries, OnlyEngineRunAssembler
from onlyalpha.runtime.defaults import only_default_run_service
from onlyalpha.runtime.factory import OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from onlyalpha.strategy.factory import OnlyStrategyFactory


def _as_runtime(runtime_type: str) -> OnlyRunConfig:
    baseline = OnlyRunConfig.load("tests/fixtures/legacy_macd/run.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = runtime_type
    return OnlyRunConfig.from_mapping(payload, source_path="tests/fixtures/legacy_macd/run.json")


def test_backtest_factory_is_selected_through_common_run_service() -> None:
    result = only_default_run_service().run(_as_runtime("BACKTEST"), export=False)
    assert result.runtime_type == "BACKTEST"
    assert result.status.value == "COMPLETED"


def test_unimplemented_runtime_factories_return_structured_unsupported_results() -> None:
    for runtime_type in ("PAPER", "LIVE", "SHADOW", "RESEARCH"):
        result = only_default_run_service().run(_as_runtime(runtime_type), export=False)
        assert result.status is OnlyRuntimeResultStatus.UNSUPPORTED
        assert result.runtime_type == runtime_type
        assert result.to_dict()["failure"] == {
            "code": "UNSUPPORTED_RUNTIME_TYPE",
            "message": f"{runtime_type} Runtime is registered but not implemented in phase one",
        }


def test_missing_runtime_factory_returns_structured_result() -> None:
    assembler = OnlyEngineRunAssembler(
        OnlyRuntimeFactoryRegistry(),
        OnlyComponentFactoryRegistries(
            OnlyDataSourceFactoryRegistry(),
            OnlyBrokerFactoryRegistry(),
            OnlyClusterFactory(
                OnlyStrategyFactory(),
                OnlyFactorFactory(),
                only_default_indicator_factories(),
            ),
        ),
    )
    result = OnlyEngineRunService(assembler, OnlyRuntimeResultExporter()).run(_as_runtime("PAPER"), export=False)
    assert result.status is OnlyRuntimeResultStatus.UNSUPPORTED
    assert result.to_dict()["failure"]["code"] == "RUNTIME_FACTORY_NOT_AVAILABLE"
