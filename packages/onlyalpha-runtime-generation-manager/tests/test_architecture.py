from pathlib import Path


def test_runtime_generation_component_has_no_private_or_mutable_loading_path() -> None:
    root = Path(__file__).resolve().parents[1] / "src/onlyalpha_runtime_generation_manager"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in (
        "onlyalpha_alpha",
        "onlyalpha_strategies",
        "importlib.reload",
        "sys.path",
        "get_latest",
        "get_newest",
        "resolve_best",
        "max(version)",
        "shell=True",
    ):
        assert forbidden not in source


def test_core_does_not_import_the_concrete_runtime_generation_component() -> None:
    root = Path(__file__).resolve().parents[3] / "src/onlyalpha"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "onlyalpha_runtime_generation_manager" not in source
