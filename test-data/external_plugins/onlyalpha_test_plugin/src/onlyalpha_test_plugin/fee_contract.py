"""Explicit fee authority for the deterministic external test Broker."""

from onlyalpha.plugin.api import OnlyBrokerFeeContract, only_simulation_zero_broker_fee_contract


def fee_contract() -> OnlyBrokerFeeContract:
    return only_simulation_zero_broker_fee_contract("test-external-broker")
