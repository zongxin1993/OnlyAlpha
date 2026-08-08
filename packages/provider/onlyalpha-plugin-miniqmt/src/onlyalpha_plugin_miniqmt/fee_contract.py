"""Explicit shadow-execution fee contract supplied by the MiniQMT plugin."""

from onlyalpha.plugin.api import OnlyBrokerFeeContract, only_simulation_zero_broker_fee_contract


def fee_contract() -> OnlyBrokerFeeContract:
    return only_simulation_zero_broker_fee_contract("miniqmt")
