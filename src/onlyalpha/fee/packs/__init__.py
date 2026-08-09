"""Built-in conformance Market fee packs."""

from onlyalpha.fee.packs.cn_a_share import only_cn_a_share_production_fee_pack
from onlyalpha.fee.packs.generic_crypto_spot import only_generic_crypto_spot_fee_pack
from onlyalpha.fee.packs.generic_margin_futures import only_generic_margin_futures_fee_pack
from onlyalpha.fee.packs.generic_t0_cash import only_generic_t0_cash_fee_pack

__all__ = [
    "only_cn_a_share_production_fee_pack",
    "only_generic_crypto_spot_fee_pack",
    "only_generic_margin_futures_fee_pack",
    "only_generic_t0_cash_fee_pack",
]
