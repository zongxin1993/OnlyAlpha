from collections.abc import Mapping, Sequence

from onlyalpha.plugin.broker import OnlyBrokerComponent, OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import OnlyPluginValidationIssue

from ..config import OnlyMiniQmtConfig
from ..descriptor import BROKER_CAPABILITIES, BROKER_DESCRIPTOR, BROKER_INTEGRATION_TYPE
from ..sdk.loader import load_xtquant
from .gateway import OnlyMiniQmtBrokerGateway


class OnlyMiniQmtBrokerFactory:
    descriptor = BROKER_DESCRIPTOR
    integration_type = BROKER_INTEGRATION_TYPE

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyMiniQmtConfig:
        return OnlyMiniQmtConfig.parse(dict(extensions))

    def parse_runtime_integration_config(
        self,
        public_configuration: Mapping[str, object],
        resolved_secrets: Mapping[str, str],
    ) -> OnlyMiniQmtConfig:
        if resolved_secrets:
            raise ValueError("MINIQMT_BROKER_SECRETS_UNSUPPORTED")
        return self.parse_config(public_configuration)

    def validate_request(self, request: OnlyBrokerCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        return tuple(
            OnlyPluginValidationIssue("PLUGIN_CAPABILITY_MISSING", item)
            for item in BROKER_CAPABILITIES.missing(request.requested_capabilities)
        )

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyBrokerComponent:
        config = (
            request.plugin_config if isinstance(request.plugin_config, OnlyMiniQmtConfig) else self.parse_config({})
        )
        path = config.require_path()
        sdk = load_xtquant()
        trader = sdk.xttrader.XtQuantTrader(
            str(path),
            abs(hash((str(request.gateway_id), str(request.runtime_id)))) % 2_147_483_647,
        )
        account = sdk.xttype.StockAccount(config.account_id or str(request.account_id), account_type="STOCK")
        gateway = OnlyMiniQmtBrokerGateway(request, config, trader, account)
        return OnlyBrokerComponent(gateway, gateway)


factory = OnlyMiniQmtBrokerFactory()
