"""Versioned conventional Indicator kernels shared by batch and incremental execution."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from onlyalpha.calculation import OnlyCalculationDefinition
from onlyalpha_plugin_indicators.financial_semantics import financial_numeric_context, quantize_financial

DAY_NS = 86_400_000_000_000


@dataclass(slots=True)
class OnlyCalibratedIndicator:
    definition: OnlyCalculationDefinition
    _rows: list[dict[str, object]] = field(default_factory=list)
    _state: dict[str, Decimal | int] = field(default_factory=dict)

    @property
    def checkpoint_schema_version(self) -> int:
        return 1

    def capture_checkpoint(self) -> object:
        return {
            "definition": self.definition.fingerprint,
            "rows": [{k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in self._rows],
            "state": {k: str(v) if isinstance(v, Decimal) else v for k, v in self._state.items()},
        }

    def restore_checkpoint(self, payload: object) -> None:
        if (
            not isinstance(payload, dict)
            or set(payload) != {"definition", "rows", "state"}
            or payload["definition"] != self.definition.fingerprint
        ):
            raise ValueError("invalid calibrated Indicator checkpoint definition")
        rows, state = payload["rows"], payload["state"]
        if not isinstance(rows, list) or not isinstance(state, dict):
            raise ValueError("invalid calibrated Indicator checkpoint")
        count = state.get("count", 0)
        if type(count) is not int or count < 0 or len(rows) != min(count, self._limit()):
            raise ValueError("invalid calibrated Indicator checkpoint count")
        name = self.definition.type_id.rsplit(".", 1)[-1]
        keys = {"count"}
        if name == "rsi":
            keys |= {"previous"} | ({"gain", "loss"} if count > 1 else set())
        elif name == "atr":
            keys |= {"previous", "atr"}
        elif name == "macd":
            keys |= {"fast", "slow", "signal", "delta"}
        elif name == "vwap":
            keys |= {"day", "weighted", "volume", "start_ns"}
        if set(state) != (keys if count else set()):
            raise ValueError("invalid calibrated Indicator checkpoint state membership")
        integer_keys = {"count", "day", "start_ns"}
        restored_state: dict[str, Decimal | int] = {}
        for key, value in state.items():
            if key in integer_keys:
                if type(value) is not int or value < 0:
                    raise ValueError("invalid calibrated Indicator integer state")
                restored_state[key] = value
            else:
                if not isinstance(value, str):
                    raise ValueError("invalid calibrated Indicator Decimal state")
                decimal = Decimal(value)
                if not decimal.is_finite() or (key in {"gain", "loss", "atr", "volume"} and decimal < 0):
                    raise ValueError("invalid calibrated Indicator Decimal state")
                restored_state[key] = decimal
        restored: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid calibrated Indicator checkpoint row")
            decoded: dict[str, object] = {}
            for key, value in row.items():
                if key != "start_ns" and not isinstance(value, str):
                    raise ValueError("invalid calibrated Indicator checkpoint Decimal input")
                decoded[key] = value if key == "start_ns" else Decimal(value)
            self._validate_inputs(decoded)
            restored.append(decoded)
        if restored and name in {"rsi", "atr"}:
            source = "value" if name == "rsi" else "close"
            if restored[-1][source] != restored_state["previous"]:
                raise ValueError("checkpoint previous value differs from input")
        if restored and name == "vwap":
            latest = restored[-1]["start_ns"]
            if latest != restored_state["start_ns"] or int(restored_state["day"]) != int(str(latest)) // DAY_NS:
                raise ValueError("checkpoint UTC day differs from input")
        self._rows, self._state = restored, restored_state

    def _limit(self) -> int:
        if not self.definition.type_id.endswith(".stochastic"):
            return 1
        p = self.definition.parameters
        return sum(int(str(p[key])) for key in ("k_period", "smooth_k", "d_period")) - 2

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        self._validate_inputs(inputs)
        if self.definition.type_id.endswith(".vwap") and "start_ns" in self._state:
            start = inputs["start_ns"]
            assert isinstance(start, int)
            if start <= self._state["start_ns"]:
                raise ValueError("UTC_DAY VWAP requires strictly ordered start_ns")
        prior_rows, prior_state = self._rows, self._state
        self._rows, self._state = list(self._rows), dict(self._state)
        try:
            with financial_numeric_context(self.definition):
                self._rows.append(dict(inputs))
                self._rows = self._rows[-self._limit() :]
                self._state["count"] = int(self._state.get("count", 0)) + 1
                name = self.definition.type_id.rsplit(".", 1)[-1]
                kernel = {
                    "rsi": self._rsi,
                    "atr": self._atr,
                    "macd": self._macd,
                    "stochastic": self._stochastic,
                    "vwap": self._vwap,
                }[name]
                raw = kernel()
                return {
                    key: quantize_financial(self.definition, value) if isinstance(value, Decimal) else value
                    for key, value in raw.items()
                }
        except Exception:
            self._rows, self._state = prior_rows, prior_state
            raise

    def _validate_inputs(self, inputs: Mapping[str, object]) -> None:
        if set(inputs) != {item.name for item in self.definition.inputs}:
            raise ValueError("calibrated Indicator input names differ")
        for name, value in inputs.items():
            if name == "start_ns":
                if type(value) is not int or value < 0:
                    raise ValueError("start_ns must be nonnegative integer")
            elif not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError("calibrated Indicator inputs require finite Decimal")
        if "high" in inputs:
            high, low = inputs["high"], inputs["low"]
            assert isinstance(high, Decimal) and isinstance(low, Decimal)
            if high < low:
                raise ValueError("high must be >= low")
        if "volume" in inputs:
            volume = inputs["volume"]
            assert isinstance(volume, Decimal)
            if volume < 0:
                raise ValueError("volume must be nonnegative")

    def _d(self, name: str) -> Decimal:
        value = self._rows[-1][name]
        assert isinstance(value, Decimal)
        return value

    def _rsi(self) -> dict[str, object]:
        value = self._d("value")
        previous = self._state.get("previous")
        self._state["previous"] = value
        period = int(str(self.definition.parameters["period"]))
        count = int(self._state["count"]) - 1
        result = None
        if previous is not None:
            change = value - Decimal(previous)
            gain, loss = max(change, Decimal(0)), max(-change, Decimal(0))
            for key, current in (("gain", gain), ("loss", loss)):
                prior = Decimal(self._state.get(key, 0))
                self._state[key] = prior + current if count <= period else (prior * (period - 1) + current) / period
            if count == period:
                self._state["gain"] = Decimal(self._state["gain"]) / period
                self._state["loss"] = Decimal(self._state["loss"]) / period
            if count >= period:
                avg_gain, avg_loss = Decimal(self._state["gain"]), Decimal(self._state["loss"])
                result = (
                    Decimal(50)
                    if avg_gain == avg_loss == 0
                    else Decimal(100)
                    if avg_loss == 0
                    else Decimal(100) - Decimal(100) / (1 + avg_gain / avg_loss)
                )
        zone = "NEUTRAL" if result is None or 30 <= result <= 70 else "OVERSOLD" if result < 30 else "OVERBOUGHT"
        return {"value": result, "zone": zone}

    def _atr(self) -> dict[str, object]:
        high, low, close = self._d("high"), self._d("low"), self._d("close")
        previous = self._state.get("previous")
        tr = high - low if previous is None else max(high - low, abs(high - previous), abs(low - previous))
        self._state["previous"] = close
        period = int(str(self.definition.parameters["period"]))
        count = int(self._state["count"])
        prior = Decimal(self._state.get("atr", 0))
        self._state["atr"] = prior + tr if count <= period else (prior * (period - 1) + tr) / period
        if count == period:
            self._state["atr"] = Decimal(self._state["atr"]) / period
        atr = Decimal(self._state["atr"]) if count >= period else None
        return {"atr": atr, "normalized_atr": None if atr is None or close == 0 else atr / close}

    def _macd(self) -> dict[str, object]:
        p = self.definition.parameters
        price = self._d("value")
        for key, target in (("fast", price), ("slow", price)):
            alpha = Decimal(2) / (int(str(p[f"{key}_period"])) + 1)
            prior = self._state.get(key)
            self._state[key] = target if prior is None else prior + alpha * (target - prior)
        dif = quantize_financial(self.definition, Decimal(self._state["fast"] - self._state["slow"]))
        prior_dea = self._state.get("signal")
        signal = (
            dif
            if prior_dea is None
            else prior_dea + Decimal(2) / (int(str(p["signal_period"])) + 1) * (dif - prior_dea)
        )
        self._state["signal"] = signal
        dea = quantize_financial(self.definition, Decimal(signal))
        delta = dif - dea
        previous = self._state.get("delta", Decimal(0))
        cross = "GOLDEN_CROSS" if previous <= 0 < delta else "DEATH_CROSS" if previous >= 0 > delta else "NONE"
        self._state["delta"] = delta
        return {"dif": dif, "dea": dea, "histogram": delta, "cross_state": cross}

    def _vwap(self) -> dict[str, object]:
        start = self._rows[-1]["start_ns"]
        assert isinstance(start, int)
        day = start // DAY_NS
        if day != self._state.get("day"):
            self._state.update(day=day, weighted=Decimal(0), volume=Decimal(0))
        self._state["start_ns"] = start
        volume = self._d("volume")
        price = (self._d("high") + self._d("low") + self._d("close")) / 3
        self._state["weighted"] += price * volume
        self._state["volume"] += volume
        total = self._state["volume"]
        return {"vwap": None if total == 0 else Decimal(self._state["weighted"] / total)}

    def _stochastic(self) -> dict[str, object]:
        p = self.definition.parameters
        period, smooth, d_period = (int(str(p[key])) for key in ("k_period", "smooth_k", "d_period"))
        raws: list[Decimal | None] = []
        for end in range(max(0, len(self._rows) - smooth - d_period + 1), len(self._rows)):
            window = self._rows[max(0, end - period + 1) : end + 1]
            if len(window) < period:
                raws.append(None)
                continue
            high = max(Decimal(str(row["high"])) for row in window)
            low = min(Decimal(str(row["low"])) for row in window)
            raws.append(None if high == low else (Decimal(str(window[-1]["close"])) - low) / (high - low) * 100)
        ks = [_average(raws[max(0, end - smooth + 1) : end + 1], smooth) for end in range(len(raws))]
        return {"k": ks[-1], "d": _average(ks[-d_period:], d_period)}


def _average(values: list[Decimal | None], size: int) -> Decimal | None:
    return (
        None
        if len(values) < size or any(v is None for v in values)
        else sum((v for v in values if v is not None), Decimal(0)) / size
    )


class OnlyCalibratedTradingFactory:
    def create(self, definition: OnlyCalculationDefinition, request: object) -> OnlyCalibratedIndicator:
        del request
        return OnlyCalibratedIndicator(definition)
