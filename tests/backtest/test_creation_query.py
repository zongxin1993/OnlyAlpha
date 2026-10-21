from types import SimpleNamespace

from onlyalpha.backtest.creation_query import OnlyBacktestCreationQuery


def test_oversized_dataset_inventory_never_decodes_or_admits_its_table() -> None:
    snapshot = SimpleNamespace(
        row_count=4097, definition=SimpleNamespace(instruments=("TEST.XSHG",), bar_semantic="same")
    )
    strategy = SimpleNamespace(
        universe=SimpleNamespace(instruments=("TEST.XSHG",)), market_input_contract=SimpleNamespace(bar_semantic="same")
    )

    class Datasets:
        def load(self, _):
            return snapshot

        def load_verified_table(self, _):
            raise AssertionError("oversized dataset decoded")

    class Strategies:
        def frozen_strategy_fingerprints(self):
            return ("a" * 64,)

        def load_verified(self, _):
            return strategy

    class Bindings:
        def verified_bindings(self):
            return (SimpleNamespace(base_dataset_snapshot_fingerprint="b" * 64),)

    query = OnlyBacktestCreationQuery(
        strategies=Strategies(),
        datasets=Datasets(),
        bindings=Bindings(),
        catalog=object(),
        admission=object(),
        generation=lambda: "c" * 64,
        validate_specification=lambda _, __: None,
    )
    context = query.get()
    assert context["options"] == []
    assert context["denied"][0]["code"] == "BACKTEST_NATIVE_DATASET_ROW_BOUND"


def test_corrupt_inventory_is_an_authority_error_not_invalid_user_input() -> None:
    import pytest

    from onlyalpha.backtest.errors import OnlyBacktestIntegrityError

    class CorruptBindings:
        def verified_bindings(self):
            raise ValueError("DATASET_ECONOMIC_BINDING_CORRUPT")

    query = OnlyBacktestCreationQuery(
        strategies=object(),
        datasets=object(),
        bindings=CorruptBindings(),
        catalog=object(),
        admission=object(),
        generation=lambda: "c" * 64,
        validate_specification=lambda _, __: None,
    )
    with pytest.raises(OnlyBacktestIntegrityError, match="BACKTEST_CREATION_CONTEXT_CORRUPT"):
        query.get()
