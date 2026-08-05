from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_runtime_factories_do_not_read_legacy_ashare_mappings() -> None:
    for relative in (
        "src/onlyalpha/runtime/backtest/factory.py",
        "src/onlyalpha/runtime/paper/factory.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "instrument_attributes" not in source
        assert '.get("st_status", False)' not in source
        assert '.get("suspended", False)' not in source


def test_ashare_authority_never_infers_board_from_symbol_prefix() -> None:
    source = (ROOT / "src/onlyalpha/reference/ashare.py").read_text(encoding="utf-8")
    assert "startswith" not in source
    assert "binary float" not in source
