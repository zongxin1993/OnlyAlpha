"""Translate canonical execution intent into Binance USD-M wire parameters."""

from onlyalpha.domain.trading import OnlyExecutionIntent, OnlyExposureConstraint, OnlyPositionMode


def only_binance_usdm_order_parameters(
    intent: OnlyExecutionIntent,
    *,
    position_mode: OnlyPositionMode,
) -> dict[str, str]:
    """Return provider fields without granting them canonical semantic authority."""

    parameters = {"side": intent.side.value}
    if position_mode is OnlyPositionMode.HEDGING:
        parameters["positionSide"] = intent.position_side.value
        if intent.exposure_constraint is OnlyExposureConstraint.REDUCE_ONLY:
            # Binance hedge mode does not accept reduceOnly as an independent
            # flag; the named leg plus canonical CLOSE carries that meaning.
            if not intent.reduces_exposure:
                raise ValueError("BINANCE_USDM_REDUCE_ONLY_OPEN_CONFLICT")
    else:
        if intent.reduces_exposure and intent.exposure_constraint is not OnlyExposureConstraint.REDUCE_ONLY:
            raise ValueError("BINANCE_USDM_NETTING_CLOSE_REQUIRES_REDUCE_ONLY")
        parameters["positionSide"] = "BOTH"
        if intent.exposure_constraint is OnlyExposureConstraint.REDUCE_ONLY:
            parameters["reduceOnly"] = "true"
    return parameters


__all__ = ["only_binance_usdm_order_parameters"]
