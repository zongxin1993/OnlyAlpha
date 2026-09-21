from types import MappingProxyType

import pytest
from onlyalpha_agent_orchestrator.adapters.openai_compatible import OnlyOpenAICompatibleModelAdapterV1
from onlyalpha_agent_orchestrator.adapters.transport import (
    OnlyHttpDispatchClassification,
    OnlyHttpResponseV1,
    OnlyHttpTransportOutcomeV1,
)
from onlyalpha_agent_orchestrator.execution import execute_external_model_occurrence
from onlyalpha_agent_orchestrator.provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyOpenAICompatibleAgentProvider,
)
from onlyalpha_agent_orchestrator.runtime import assert_external_io_permit

from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyResolvedIntegrationRuntimeConfiguration,
    OnlyResolvedIntegrationSecrets,
)
from onlyalpha.plugin.agent_provider import OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE
from onlyalpha.plugin.integration import OnlyIntegrationCategory
from onlyalpha.research.agent import OnlyAgentModelCallOutcome
from tests.research.agent.test_external_model_execution import _Contexts, _permit, _response
from tests.research.agent.test_occurrence_foundation import _prepare_model, _services


def test_provider_integration_and_model_profile_drive_real_external_model_adapter(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = OnlyIntegrationRuntimeBindingV1(
        OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        "a" * 64,
        OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE.type_id.value,
        OnlyIntegrationCategory.AGENT_PROVIDER,
        OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE.fingerprint,
        "b" * 64,
    )
    profile = OnlyAgentModelProfileV1(
        binding.integration_id.value,
        binding.revision_fingerprint,
        binding.runtime_configuration_fingerprint,
        "model-a",
        "2026-09-01",
        ("CHAT", "STRUCTURED_OUTPUT"),
    )
    endpoint = OnlyOpenAICompatibleAgentProvider.endpoint(
        OnlyResolvedIntegrationRuntimeConfiguration(
            binding,
            OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE,
            MappingProxyType(
                {
                    "base_url": "https://provider.example/v1",
                    "connect_timeout_seconds": 0.2,
                    "read_timeout_seconds": 1.0,
                    "verify_tls": True,
                }
            ),
            OnlyResolvedIntegrationSecrets({"api_credential": "exact-provider-secret"}),
        ),
        profile,
    )
    context, model, _, _, _, reference, *_ = _services(tmp_path)
    prepared = _prepare_model(
        model,
        context,
        reference,
        provider_id="openai-compatible",
        model_id=profile.model_id,
        model_version=profile.model_version,
    )

    class Transport:
        requests = []

        def send(self, request, permit):  # type: ignore[no-untyped-def]
            assert_external_io_permit(permit, consume=True)
            self.requests.append(request)
            return OnlyHttpTransportOutcomeV1(
                OnlyHttpDispatchClassification.RESPONSE_RECEIVED,
                OnlyHttpResponseV1(200, (), _response('{"action":"PLAN"}')),
            )

    transport = Transport()
    adapter = OnlyOpenAICompatibleModelAdapterV1(
        config=endpoint,
        resources=model._resources,  # noqa: SLF001
        contexts=_Contexts(),
        transport=transport,  # type: ignore[arg-type]
    )

    result = execute_external_model_occurrence(
        permit=_permit(monkeypatch, model, context),
        prepared=prepared,
        occurrences=model,
        adapter=adapter,
    )

    assert result.outcome is OnlyAgentModelCallOutcome.RETURNED
    assert len(transport.requests) == 1
    assert transport.requests[0].headers["Authorization"] == "Bearer exact-provider-secret"
