from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.runtime.backtest.input_requirements import only_kernel_economic_input_requirements
from tests.market_product.test_universal_economic_policy import _futures_policy


def test_futures_kernel_requirements_do_not_mutate_strategy_inputs() -> None:
    requirements = only_kernel_economic_input_requirements(_futures_policy())

    assert {(item.fact_family, item.reference_price_kind) for item in requirements} == {
        (OnlyMarketDataType.FUNDING_RATE, None),
        (OnlyMarketDataType.REFERENCE_PRICE, OnlyReferencePriceKind.MARK),
    }
