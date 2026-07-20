class OnlyFakeFrame:
    def __init__(
        self, rows: list[dict[str, object]], columns: tuple[str, ...] | None = None
    ) -> None:
        self._rows = rows
        self.columns = (
            columns or tuple(rows[0])
            if rows
            else columns
            or (
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "vol",
                "amount",
            )
        )

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self._rows


def row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "ts_code": "600000.SH",
        "trade_date": "20250103",
        "open": 10.01,
        "high": 10.55,
        "low": 9.98,
        "close": 10.35,
        "vol": 123.45,
        "amount": 127.777,
    }
    value.update(changes)
    return value
