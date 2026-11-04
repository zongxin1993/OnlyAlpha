"""Explicit simulation-only fee contract supplied by the Virtual Broker plugin."""

from onlyalpha.plugin.api import OnlyBrokerFeeContract, only_simulation_zero_broker_fee_contract


def fee_contract() -> OnlyBrokerFeeContract:
    return only_simulation_zero_broker_fee_contract("virtual")
