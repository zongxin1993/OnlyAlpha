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


def test_exact_catalog_context_core_has_no_infrastructure_or_http_dependencies() -> None:
    module = Path(__file__).resolve().parents[3] / "src/onlyalpha/application/catalog_context.py"
    source = module.read_text(encoding="utf-8")
    for forbidden in ("onlyalpha_runtime_generation_manager", "fastapi", "psycopg", "subprocess", "tempfile"):
        assert forbidden not in source


def test_search_execution_boundary_is_bounded_and_cannot_load_history_into_parent() -> None:
    repository = Path(__file__).resolve().parents[3]
    contract = (repository / "src/onlyalpha/application/search_generation_execution.py").read_text(encoding="utf-8")
    manager_root = Path(__file__).resolve().parents[1] / "src/onlyalpha_runtime_generation_manager"
    manager = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (manager_root / "host_manager.py", manager_root / "search_worker.py")
    )
    for forbidden in ("subprocess", "importlib", "sys.path", "socket", "psycopg"):
        assert forbidden not in contract
    for forbidden in (
        "CALL_PYTHON",
        "EXEC_MODULE",
        "INVOKE_FUNCTION",
        "shell=True",
        "eval(",
        "exec(",
        "importlib.reload",
        "sys.path",
        "ACTIVE_FOR_NEW_WORK",
        "get_latest",
    ):
        assert forbidden not in manager
