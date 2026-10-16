from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from onlyalpha.runtime.runtime import OnlyRuntimeError
from onlyalpha.runtime.streaming.config import OnlyStreamingRuntimeConfig
from onlyalpha.runtime.streaming.execution import OnlyExecutionSubmissionCapability
from onlyalpha.runtime.streaming.runtime import OnlyStreamingRuntime


def test_streaming_config_does_not_select_a_provider_profile() -> None:
    assert (
        OnlyStreamingRuntimeConfig(OnlyExecutionSubmissionCapability.SIMULATED).historical_compatibility_profile is None
    )
    assert (
        OnlyStreamingRuntimeConfig.from_mapping({"execution_capability": "SIMULATED"}).historical_compatibility_profile
        is None
    )


def test_streaming_config_preserves_an_explicit_provider_profile() -> None:
    result = OnlyStreamingRuntimeConfig.from_mapping(
        {"execution_capability": "SIMULATED", "streaming": {"historical_compatibility_profile": "controlled-bars-v1"}}
    )
    assert result.historical_compatibility_profile == "controlled-bars-v1"


@pytest.mark.parametrize("profile", ["", "   ", 2, False])
def test_streaming_config_rejects_invalid_explicit_profiles(profile: object) -> None:
    with pytest.raises(ValueError, match="historical.*profile"):
        OnlyStreamingRuntimeConfig.from_mapping(
            {"execution_capability": "SIMULATED", "streaming": {"historical_compatibility_profile": profile}}
        )


def test_bar_warmup_missing_profile_fails_before_calling_provider(make_runtime_bar) -> None:
    bar = make_runtime_bar(0)
    load_warmup = Mock()
    runtime = cast(
        OnlyStreamingRuntime,
        SimpleNamespace(
            _services=SimpleNamespace(clock=SimpleNamespace(now_utc=lambda: bar.bar_end)),
            _warmup_alignment_steps=(),
            _construction_graph=SimpleNamespace(provider_inputs=(bar.bar_type,)),
            _historical_compatibility_profile=None,
            _driver=SimpleNamespace(source=SimpleNamespace(load_warmup=load_warmup)),
        ),
    )
    with pytest.raises(OnlyRuntimeError, match="historical.*profile"):
        OnlyStreamingRuntime._bootstrap(runtime)
    load_warmup.assert_not_called()
