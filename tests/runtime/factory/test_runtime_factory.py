import json

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.value import OnlyCurrency
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


def test_default_composition_installs_only_the_verified_cny_policy() -> None:
    first = only_default_engine_services()
    second = only_default_engine_services()
    cny = OnlyCurrency("CNY", 2)

    first_policy = first.fee_reconciliation_policies.require("STANDARD_FEE_RECONCILIATION", "1", cny)
    second_policy = second.fee_reconciliation_policies.require("STANDARD_FEE_RECONCILIATION", "1", cny)

    assert first.fee_reconciliation_policies is not second.fee_reconciliation_policies
    assert first_policy.identity == second_policy.identity
    with pytest.raises(ValueError, match="FEE_RECONCILIATION_POLICY_NOT_INSTALLED"):
        first.fee_reconciliation_policies.require(
            "STANDARD_FEE_RECONCILIATION",
            "1",
            OnlyCurrency("USD", 2),
        )


def test_unimplemented_runtime_factories_return_structured_unsupported_results() -> None:
    services = only_default_engine_services()
    for runtime_type in ("LIVE", "SHADOW", "RESEARCH"):
        build = services.assembler.build(_plan(runtime_type))
        assert build.runtime is None
        assert build.failure_code == "UNSUPPORTED_RUNTIME_TYPE"
        assert build.failure_message == f"{runtime_type} Runtime is registered but not implemented in phase one"


def test_paper_factory_is_selected_and_fails_closed_on_an_enabled_broker() -> None:
    build = only_default_engine_services().assembler.build(_plan("PAPER"))

    assert build.runtime is None
    assert build.failure_code == "RUNTIME_ASSEMBLY_FAILED"
    assert "forbids enabled Broker adapters" in str(build.failure_message)
