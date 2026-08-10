"""Virtual Broker plugin Factory and extension parser."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.broker import OnlyBrokerComponent, OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities, OnlyPluginValidationIssue
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor
from onlyalpha_plugin_broker_virtual.config import OnlyVirtualBrokerConfig
from onlyalpha_plugin_broker_virtual.descriptor import ONLY_VIRTUAL_PLUGIN_DESCRIPTOR
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillDispatchMode,
    OnlyVirtualFillScheduleMode,
    OnlyVirtualFillScheduleStepSpec,
)
from onlyalpha_plugin_broker_virtual.gateway import OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.latency import OnlyFixedLatencyModel
from onlyalpha_plugin_broker_virtual.slippage import OnlyFixedSlippageModel
from onlyalpha_plugin_broker_virtual.submission_control import (
    OnlyVirtualSubmissionAction,
    OnlyVirtualSubmissionControl,
    OnlyVirtualSubmissionSimulation,
)


@dataclass(frozen=True, slots=True)
class OnlyVirtualBrokerPluginConfig:
    matching_type: str
    slippage_type: str
    maximum_fill_quantity: Decimal | None
    fill_schedule_mode: OnlyVirtualFillScheduleMode | None
    fill_dispatch_mode: OnlyVirtualFillDispatchMode
    fill_schedule_steps: tuple[OnlyVirtualFillScheduleStepSpec, ...]
    submit_latency_ns: int
    acceptance_latency_ns: int
    fill_latency_ns: int
    cancel_latency_ns: int
    query_latency_ns: int
    slippage_offset: Decimal | None
    submission_simulation: OnlyVirtualSubmissionSimulation


class OnlyVirtualBrokerFactory:
    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return ONLY_VIRTUAL_PLUGIN_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyVirtualBrokerPluginConfig:
        unknown = set(extensions) - {
            "matching",
            "latency",
            "slippage",
            "maximum_fill_quantity",
            "simulation",
        }
        if unknown:
            raise ValueError(f"unknown Virtual Broker extensions: {', '.join(sorted(unknown))}")
        matching = extensions.get("matching", {})
        slippage = extensions.get("slippage", {})
        latency = extensions.get("latency", {})
        simulation = extensions.get("simulation", {})
        if (
            not isinstance(matching, Mapping)
            or not isinstance(slippage, Mapping)
            or not isinstance(latency, Mapping)
            or not isinstance(simulation, Mapping)
        ):
            raise ValueError("broker matching/slippage/latency/simulation extensions must be mappings")
        unknown_matching = set(matching) - {"type", "maximum_fill_quantity", "partial_fill"}
        unknown_slippage = set(slippage) - {"type", "price_offset"}
        unknown_latency = set(latency) - {"submit_ns", "acceptance_ns", "fill_ns", "cancel_ns", "query_ns"}
        if unknown_matching or unknown_slippage or unknown_latency:
            raise ValueError("unknown Virtual Broker nested extension field")
        unknown_simulation = set(simulation) - {"submissions"}
        if unknown_simulation:
            raise ValueError("unknown Virtual Broker simulation field")
        raw_submissions = simulation.get("submissions", ())
        if not isinstance(raw_submissions, Sequence) or isinstance(raw_submissions, (str, bytes)):
            raise ValueError("Virtual Broker simulation submissions must be a sequence")
        submission_controls: list[OnlyVirtualSubmissionControl] = []
        for raw_submission in raw_submissions:
            if not isinstance(raw_submission, Mapping):
                raise ValueError("Virtual Broker simulation submission must be a mapping")
            unknown_submission = set(raw_submission) - {
                "submission_index",
                "action",
                "reason",
                "rejection_code",
            }
            if unknown_submission:
                raise ValueError("unknown Virtual Broker simulation submission field")
            raw_index = raw_submission.get("submission_index")
            if not isinstance(raw_index, int) or isinstance(raw_index, bool):
                raise ValueError("VIRTUAL_SUBMISSION_INDEX_INVALID")
            raw_action = raw_submission.get("action")
            if not isinstance(raw_action, str):
                raise ValueError("VIRTUAL_SUBMISSION_ACTION_INVALID")
            raw_reason = raw_submission.get("reason")
            raw_rejection_code = raw_submission.get("rejection_code")
            if raw_reason is not None and not isinstance(raw_reason, str):
                raise ValueError("VIRTUAL_SUBMISSION_REASON_INVALID")
            if raw_rejection_code is not None and not isinstance(raw_rejection_code, str):
                raise ValueError("VIRTUAL_SUBMISSION_REJECTION_CODE_INVALID")
            try:
                action = OnlyVirtualSubmissionAction(raw_action.upper())
            except ValueError as exc:
                raise ValueError("VIRTUAL_SUBMISSION_ACTION_INVALID") from exc
            submission_controls.append(OnlyVirtualSubmissionControl(raw_index, action, raw_reason, raw_rejection_code))
        submission_simulation = OnlyVirtualSubmissionSimulation(tuple(submission_controls))
        partial_fill = matching.get("partial_fill")
        if partial_fill is not None and not isinstance(partial_fill, Mapping):
            raise ValueError("Virtual Broker partial_fill extension must be a mapping")
        partial = {} if partial_fill is None else partial_fill
        unknown_partial = set(partial) - {"mode", "dispatch_mode", "steps", "maximum_fill_quantity"}
        if unknown_partial:
            raise ValueError("unknown Virtual Broker partial_fill field")
        raw_steps = partial.get("steps", ())
        if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes)):
            raise ValueError("Virtual Broker partial_fill steps must be a sequence")
        steps: list[OnlyVirtualFillScheduleStepSpec] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                raise ValueError("Virtual Broker partial_fill step must be a mapping")
            unknown_step = set(raw_step) - {"bar_offset", "quantity", "ratio"}
            if unknown_step:
                raise ValueError("unknown Virtual Broker partial_fill step field")
            steps.append(
                OnlyVirtualFillScheduleStepSpec(
                    int(raw_step.get("bar_offset", 0)),
                    None if raw_step.get("quantity") is None else Decimal(str(raw_step["quantity"])),
                    None if raw_step.get("ratio") is None else Decimal(str(raw_step["ratio"])),
                )
            )
        maximum_values = tuple(
            Decimal(str(value))
            for value in (
                extensions.get("maximum_fill_quantity"),
                matching.get("maximum_fill_quantity"),
                partial.get("maximum_fill_quantity"),
            )
            if value is not None
        )
        if len(set(maximum_values)) > 1:
            raise ValueError("VIRTUAL_FILL_POLICY_CONFLICT")
        maximum = maximum_values[0] if maximum_values else None
        explicit_mode = partial.get("mode")
        mode = None if explicit_mode is None else OnlyVirtualFillScheduleMode(str(explicit_mode).upper())
        dispatch_mode = OnlyVirtualFillDispatchMode(str(partial.get("dispatch_mode", "ONE_PER_BAR")).upper())
        if maximum is not None and mode in {OnlyVirtualFillScheduleMode.WHOLE, OnlyVirtualFillScheduleMode.SCHEDULE}:
            raise ValueError("VIRTUAL_FILL_POLICY_CONFLICT")
        if mode is OnlyVirtualFillScheduleMode.MAX_PER_BAR and maximum is None:
            raise ValueError("VIRTUAL_FILL_MAXIMUM_REQUIRED")
        if mode is OnlyVirtualFillScheduleMode.SCHEDULE and not steps:
            raise ValueError("VIRTUAL_FILL_SCHEDULE_EMPTY")
        if mode is not OnlyVirtualFillScheduleMode.SCHEDULE and steps:
            raise ValueError("VIRTUAL_FILL_POLICY_CONFLICT")
        return OnlyVirtualBrokerPluginConfig(
            str(matching.get("type", "NEXT_BAR")).upper(),
            str(slippage.get("type", "NONE")).upper(),
            maximum,
            mode,
            dispatch_mode,
            tuple(steps),
            int(latency.get("submit_ns", 0)),
            int(latency.get("acceptance_ns", 0)),
            int(latency.get("fill_ns", 0)),
            int(latency.get("cancel_ns", 0)),
            int(latency.get("query_ns", 0)),
            None if slippage.get("price_offset") is None else Decimal(str(slippage["price_offset"])),
            submission_simulation,
        )

    def validate_request(self, request: OnlyBrokerCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        issues: list[OnlyPluginValidationIssue] = []
        capabilities = self.descriptor.capabilities
        if not isinstance(capabilities, OnlyBrokerPluginCapabilities):
            issues.append(OnlyPluginValidationIssue("PLUGIN_DESCRIPTOR_INVALID", "invalid capabilities"))
        else:
            issues.extend(
                OnlyPluginValidationIssue(
                    "PLUGIN_CAPABILITY_NOT_SUPPORTED",
                    f"Virtual Broker does not support {name}",
                    name,
                )
                for name in capabilities.missing(request.requested_capabilities)
            )
        config = request.plugin_config
        if not isinstance(config, OnlyVirtualBrokerPluginConfig):
            issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "invalid Virtual Broker config"))
        else:
            if config.matching_type != "NEXT_BAR":
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "NEXT_BAR matching is required"))
            if config.slippage_type not in {"NONE", "FIXED"}:
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "unsupported slippage type"))
            if config.maximum_fill_quantity is not None and config.maximum_fill_quantity <= 0:
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "maximum fill must be positive"))
            if config.fill_schedule_mode is OnlyVirtualFillScheduleMode.SCHEDULE and not config.fill_schedule_steps:
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "fill schedule requires steps"))
            if not isinstance(config.submission_simulation, OnlyVirtualSubmissionSimulation):
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "invalid submission simulation"))
            if (
                min(
                    config.submit_latency_ns,
                    config.acceptance_latency_ns,
                    config.fill_latency_ns,
                    config.cancel_latency_ns,
                    config.query_latency_ns,
                )
                < 0
            ):
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "latency cannot be negative"))
        return tuple(issues)

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyBrokerComponent:
        config = request.plugin_config
        if not isinstance(config, OnlyVirtualBrokerPluginConfig):
            raise TypeError("Virtual Broker Factory requires OnlyVirtualBrokerPluginConfig")
        broker_config = OnlyVirtualBrokerConfig(
            request.gateway_id,
            request.account_id,
            request.initial_cash.currency,
            request.initial_cash,
            maximum_fill_quantity=None
            if config.maximum_fill_quantity is None
            else OnlyQuantity(config.maximum_fill_quantity, 8),
            fill_schedule_mode=config.fill_schedule_mode,
            fill_dispatch_mode=config.fill_dispatch_mode,
            fill_schedule_steps=config.fill_schedule_steps,
            latency_model=OnlyFixedLatencyModel(
                config.submit_latency_ns,
                config.acceptance_latency_ns,
                config.fill_latency_ns,
                config.cancel_latency_ns,
                config.query_latency_ns,
            ),
            slippage_model=(
                None
                if config.slippage_type == "NONE"
                else OnlyFixedSlippageModel(OnlyPrice(config.slippage_offset or Decimal(0), 8))
            ),
            submission_simulation=config.submission_simulation,
        )
        gateway = OnlyVirtualBrokerGateway(
            broker_config,
            request.runtime_id,
            request.clock,
            request.broker_inbound_queue.put,
        )
        return OnlyBrokerComponent(gateway, gateway, gateway)
