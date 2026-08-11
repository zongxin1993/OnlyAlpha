"""Fail-closed SIM product identity and composition contract."""

from __future__ import annotations

from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities, OnlyDataSourceCapabilities
from onlyalpha.plugin.errors import OnlyPluginError
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult
from onlyalpha.runtime.streaming.config import OnlyStreamingRuntimeConfig
from onlyalpha.runtime.streaming.execution import OnlyExecutionSubmissionCapability


class _OnlySimCompositionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class OnlySimRuntimeFactory:
    """Validate SIM composition without claiming execution is available."""

    @property
    def runtime_type(self) -> str:
        return "SIM"

    def validate(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        try:
            self._validate(request)
        except Exception as exc:
            return self._failure(exc)
        return OnlyRuntimeBuildResult(
            failure_code="SIM_EXECUTION_WIRING_PENDING",
            failure_message=(
                "SIM composition is valid, but realtime Virtual Broker execution wiring is not implemented"
            ),
        )

    def create(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        return self.validate(request)

    @staticmethod
    def _validate(request: OnlyRuntimeBuildRequest) -> None:
        components = request.components
        if not isinstance(components, OnlyComponentFactoryRegistries):
            raise TypeError("Sim factory requires OnlyComponentFactoryRegistries")

        config = request.config
        if config.runtime.runtime_type != "SIM":
            raise _OnlySimCompositionError(
                "SIM_RUNTIME_TYPE_REQUIRED",
                "Sim factory requires runtime.type=SIM",
            )

        streaming = OnlyStreamingRuntimeConfig.from_mapping(config.runtime.extensions)
        if streaming.execution_capability is not OnlyExecutionSubmissionCapability.SIMULATED:
            raise _OnlySimCompositionError(
                "SIM_EXECUTION_CAPABILITY_REQUIRED",
                "SIM requires explicit SIMULATED execution capability",
            )

        if config.start_time is not None or config.end_time is not None:
            raise _OnlySimCompositionError(
                "SIM_FINITE_RANGE_NOT_SUPPORTED",
                "SIM does not support runtime.start_time or runtime.end_time",
            )

        if config.runtime.persistence.checkpoint.enabled:
            raise _OnlySimCompositionError(
                "SIM_CHECKPOINT_NOT_SUPPORTED",
                "SIM checkpoint/restart is not yet supported",
            )

        sources = tuple(item for item in config.data_sources if item.enabled)
        if len(sources) != 1:
            raise _OnlySimCompositionError(
                "SIM_DATA_SOURCE_COUNT_INVALID",
                "SIM requires exactly one enabled realtime DataSource",
            )
        source = sources[0]
        source_factory = components.data_sources.resolve(source.plugin_id)
        source_capabilities = source_factory.descriptor.capabilities
        required_source_capabilities = OnlyDataSourceCapabilities(historical_bars=True, live_bars=True)
        if not isinstance(source_capabilities, OnlyDataSourceCapabilities):
            raise _OnlySimCompositionError(
                "SIM_DATA_SOURCE_CAPABILITY_REQUIRED",
                "SIM DataSource must declare historical_bars and live_bars capabilities",
            )
        missing_source_capabilities = source_capabilities.missing(required_source_capabilities)
        if missing_source_capabilities:
            raise _OnlySimCompositionError(
                "SIM_DATA_SOURCE_CAPABILITY_REQUIRED",
                f"SIM DataSource is missing required capabilities: {', '.join(missing_source_capabilities)}",
            )

        if len(config.accounts) != 1:
            raise _OnlySimCompositionError(
                "SIM_ACCOUNT_COUNT_INVALID",
                "SIM requires exactly one Account",
            )

        brokers = tuple(item for item in config.brokers if item.enabled)
        if len(brokers) != 1:
            raise _OnlySimCompositionError(
                "SIM_BROKER_COUNT_INVALID",
                "SIM requires exactly one enabled Broker",
            )
        broker = brokers[0]
        broker_factory = components.brokers.resolve(broker.plugin_id)
        broker_capabilities = broker_factory.descriptor.capabilities
        if (
            not isinstance(broker_capabilities, OnlyBrokerPluginCapabilities)
            or not broker_capabilities.simulated_execution
        ):
            raise _OnlySimCompositionError(
                "SIM_SIMULATED_BROKER_REQUIRED",
                "SIM Broker must explicitly support simulated_execution",
            )
        required_broker_capabilities = OnlyBrokerPluginCapabilities(
            submit_order=True,
            cancel_order=True,
            query_orders=True,
            query_trades=True,
        )
        missing_broker_capabilities = broker_capabilities.missing(required_broker_capabilities)
        if missing_broker_capabilities:
            raise _OnlySimCompositionError(
                "SIM_BROKER_CAPABILITY_REQUIRED",
                f"SIM Broker is missing required capabilities: {', '.join(missing_broker_capabilities)}",
            )

    @staticmethod
    def _failure(exc: Exception) -> OnlyRuntimeBuildResult:
        if isinstance(exc, (_OnlySimCompositionError, OnlyPluginError)):
            code = exc.code
        else:
            code = "RUNTIME_ASSEMBLY_FAILED"
        return OnlyRuntimeBuildResult(failure_code=code, failure_message=str(exc))
