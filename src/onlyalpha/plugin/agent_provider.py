"""Public Integration contract for external Agent model providers."""

from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationProbeCheck,
    OnlyIntegrationProbeContractV1,
    OnlyIntegrationProbeMode,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    OnlyIntegrationValueKind,
)

OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE = OnlyIntegrationTypeDescriptorV1(
    type_id=OnlyIntegrationTypeId("openai.compatible.agent_provider"),
    category=OnlyIntegrationCategory.AGENT_PROVIDER,
    display_name="OpenAI-compatible Agent Provider",
    description="OpenAI-compatible chat and structured-output model connectivity.",
    provider_id="openai-compatible",
    implementation_id="openai-compatible",
    implementation_version="1.0.0",
    public_api_version="1.0",
    capabilities=("CHAT", "MODEL_DISCOVERY", "STRUCTURED_OUTPUT"),
    configuration_contract=OnlyIntegrationConfigurationContractV1(
        fields=(
            OnlyIntegrationConfigurationFieldV1(
                "base_url", OnlyIntegrationValueKind.STRING, True, display_name="API base URL"
            ),
            OnlyIntegrationConfigurationFieldV1(
                "api_credential",
                OnlyIntegrationValueKind.STRING,
                True,
                secret=True,
                display_name="API credential",
            ),
            OnlyIntegrationConfigurationFieldV1(
                "connect_timeout_seconds",
                OnlyIntegrationValueKind.DURATION,
                False,
                default=10.0,
                advanced=True,
                display_name="Connect timeout",
                minimum=0.0,
                maximum=60.0,
                exclusive_minimum=True,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "read_timeout_seconds",
                OnlyIntegrationValueKind.DURATION,
                False,
                default=60.0,
                advanced=True,
                display_name="Read timeout",
                minimum=0.0,
                maximum=300.0,
                exclusive_minimum=True,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "verify_tls",
                OnlyIntegrationValueKind.BOOLEAN,
                False,
                default=True,
                advanced=True,
                display_name="Verify TLS",
            ),
        )
    ),
    probe_contract=OnlyIntegrationProbeContractV1(
        probe_mode=OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
        default_probe_instrument="models",
        user_selectable_probe_instrument=False,
        probe_checks=(
            OnlyIntegrationProbeCheck.CONNECTIVITY,
            OnlyIntegrationProbeCheck.AUTHENTICATION,
            OnlyIntegrationProbeCheck.MODEL_DISCOVERY,
        ),
    ),
)

__all__ = ["OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE"]
