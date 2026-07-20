from collections.abc import Mapping, Sequence
from onlyalpha.plugin.broker import OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import OnlyPluginValidationIssue
from ..config import OnlyMiniQmtConfig
from ..descriptor import BROKER_CAPABILITIES, BROKER_DESCRIPTOR
from ..sdk.loader import load_xtquant
from .gateway import OnlyMiniQmtBrokerGateway


class OnlyMiniQmtBrokerFactory:
    descriptor = BROKER_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyMiniQmtConfig:
        return OnlyMiniQmtConfig.parse(dict(extensions))

    def validate_request(
        self, request: OnlyBrokerCreateRequest
    ) -> Sequence[OnlyPluginValidationIssue]:
        return tuple(
            OnlyPluginValidationIssue("PLUGIN_CAPABILITY_MISSING", item)
            for item in BROKER_CAPABILITIES.missing(request.requested_capabilities)
        )

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyMiniQmtBrokerGateway:
        config = (
            request.plugin_config
            if isinstance(request.plugin_config, OnlyMiniQmtConfig)
            else self.parse_config({})
        )
        path = config.require_path()
        sdk = load_xtquant()
        trader = sdk.xttrader.XtQuantTrader(
            str(path),
            abs(hash((str(request.gateway_id), str(request.runtime_id))))
            % 2_147_483_647,
        )
        account = sdk.xttype.StockAccount(
            config.account_id or str(request.account_id), account_type="STOCK"
        )
        return OnlyMiniQmtBrokerGateway(request, config, trader, account)


factory = OnlyMiniQmtBrokerFactory()
