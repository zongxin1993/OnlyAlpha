from pathlib import Path


def _python_source(package: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((Path("src/onlyalpha") / package).glob("*.py"))
    )


def test_result_dtos_do_not_depend_on_runtime_or_output_layers() -> None:
    source = _python_source("result")
    for forbidden in (
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.broker",
        "onlyalpha.analytics",
        "onlyalpha.artifact",
        "onlyalpha.report",
        "pyarrow",
        "pandas",
    ):
        assert forbidden not in source


def test_analytics_and_artifact_dependencies_point_one_way() -> None:
    analytics = _python_source("analytics")
    artifact = _python_source("artifact")
    for forbidden in ("onlyalpha.runtime", "onlyalpha.collector", "onlyalpha.artifact", "onlyalpha.report"):
        assert forbidden not in analytics
    for forbidden in ("onlyalpha.runtime", "onlyalpha.collector", "onlyalpha.report"):
        assert forbidden not in artifact


def test_runtime_does_not_depend_on_analysis_or_presentation() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(Path("src/onlyalpha/runtime").rglob("*.py")))
    for forbidden in ("onlyalpha.analytics", "onlyalpha.artifact", "onlyalpha.report"):
        assert forbidden not in source
