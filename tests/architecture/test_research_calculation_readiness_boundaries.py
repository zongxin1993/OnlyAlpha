"""Executable dependency directions for internal readiness publication."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

from onlyalpha.calculation import OnlyCalculationBackendKind
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, only_discover_quant_asset_providers

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "onlyalpha"
CALCULATION = CORE / "research" / "calculation"
PUBLICATION_MODULES = (
    "readiness.py",
    "publication.py",
    "result_v2_identity.py",
    "result_v2.py",
    "result_v2_ports.py",
    "result_v2_store.py",
    "execution_evidence_v2.py",
)
PRODUCT_FORBIDDEN = ("onlyalpha.application", "onlyalpha.persistence", "onlyalpha_http_server", "onlyalpha_web_console")
AGGREGATE_REEXPORT_MODULES = ("onlyalpha.research", "onlyalpha.research.calculation")


def _package(path: Path) -> str:
    source = (
        CORE.parent if path.is_relative_to(CORE) else next(parent for parent in path.parents if parent.name == "src")
    )
    return ".".join(path.parent.relative_to(source).parts)


def _imports(tree: ast.AST, package: str) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            imports.add(module)
            imports.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and node.args:
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name in ("__import__", "import_module") and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str):
                    imports.add(resolve_name(value, package) if value.startswith(".") else value)
    return imports


def _boundary_violations(
    imports: set[str],
    *,
    forbidden_prefixes: tuple[str, ...],
    forbidden_exact_modules: tuple[str, ...] = (),
) -> set[str]:
    return {
        name
        for name in imports
        if name in forbidden_exact_modules
        or any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
    }


def _assert_boundary(
    path: Path,
    forbidden_prefixes: tuple[str, ...],
    *,
    forbidden_exact_modules: tuple[str, ...] = (),
) -> None:
    imports = _imports(ast.parse(path.read_text()), _package(path))
    violations = _boundary_violations(
        imports,
        forbidden_prefixes=forbidden_prefixes,
        forbidden_exact_modules=forbidden_exact_modules,
    )
    assert not violations, (str(path.relative_to(ROOT)), sorted(violations))


@pytest.mark.parametrize("name", PUBLICATION_MODULES)
def test_readiness_publication_depends_only_on_canonical_research_and_calculation(name: str) -> None:
    _assert_boundary(
        CALCULATION / name,
        PRODUCT_FORBIDDEN
        + (
            "onlyalpha.research.query",
            "onlyalpha.research.artifact",
            "onlyalpha.research.result",
            "onlyalpha.runtime",
            "onlyalpha_plugin_indicators",
            "onlyalpha_plugin_operators",
            "onlyalpha_plugin_targets",
        ),
        forbidden_exact_modules=AGGREGATE_REEXPORT_MODULES,
    )


def test_indicator_readiness_plugin_cannot_publish_or_orchestrate() -> None:
    paths = sorted((ROOT / "plugs/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators").rglob("*.py"))
    assert paths
    for path in paths:
        _assert_boundary(
            path,
            PRODUCT_FORBIDDEN
            + (
                "onlyalpha.research.calculation.result_v2_store",
                "onlyalpha.research.calculation.execution_evidence_v2",
                "onlyalpha.research.job",
                "onlyalpha.runtime",
                "onlyalpha.research.query",
                "onlyalpha.research.artifact",
            ),
            forbidden_exact_modules=AGGREGATE_REEXPORT_MODULES,
        )


def test_core_does_not_import_official_indicator_implementation() -> None:
    paths = sorted(CORE.rglob("*.py"))
    assert paths
    for path in paths:
        _assert_boundary(path, ("onlyalpha_plugin_indicators",))


def _eager_statements(statements: list[ast.stmt]) -> list[ast.stmt]:
    eager = []
    for node in statements:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.If):
            type_checking = isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
            type_checking |= isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING"
            eager.extend(_eager_statements(node.orelse if type_checking else node.body + node.orelse))
        else:
            eager.append(node)
    return eager


def test_job_orchestrates_authorities_without_product_or_eager_v2_store_dependencies() -> None:
    paths = sorted((CORE / "research/job").rglob("*.py"))
    assert paths
    for path in paths:
        _assert_boundary(path, PRODUCT_FORBIDDEN, forbidden_exact_modules=AGGREGATE_REEXPORT_MODULES)
        tree = ast.parse(path.read_text())
        eager = ast.Module(body=_eager_statements(tree.body), type_ignores=[])
        imports = _imports(eager, _package(path))
        assert not any(
            name.startswith(
                (
                    "onlyalpha.research.calculation.result_v2",
                    "onlyalpha.research.calculation.execution_evidence_v2",
                )
            )
            for name in imports
        ), path
    # Fresh-process transitive import proof is owned by the existing Job test:
    # test_v1_job_import_does_not_load_v2_result_or_evidence_implementations.


def test_product_and_http_do_not_expose_internal_readiness_publication_contracts() -> None:
    forbidden = {
        "RESEARCH_JOB_PLAN_READINESS_SCHEMA_VERSION",
        "OnlyResearchCalculationResultV2",
        "OnlyResearchCalculationExecutionEvidenceV2",
    }
    paths = sorted((CORE / "application").rglob("*.py")) + sorted(
        (ROOT / "packages/onlyalpha-http-server/src").rglob("*.py")
    )
    assert paths
    for path in paths:
        tree = ast.parse(path.read_text())
        names = {
            node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Name, ast.Attribute, ast.alias))
        }
        # Includes __all__ and string forward annotations, not whole-file matching.
        names.update(
            node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        assert not names & forbidden, (path, names & forbidden)


def test_only_production_sma_research_registration_advertises_readiness_v1() -> None:
    discovered = only_discover_quant_asset_providers()
    production = tuple(
        provider for provider in discovered.providers if provider.manifest.provider_id.startswith("onlyalpha.")
    )
    assert {provider.manifest.provider_id for provider in production} >= {
        "onlyalpha.indicator.library",
        "onlyalpha.operator.library",
    }
    registry = OnlyQuantAssetCatalogGeneration(production).calculation_registry()
    supported = {
        (
            item.type_definition.type_id,
            item.type_definition.semantic_version,
            item.backend,
            item.readiness_contract_versions,
        )
        for item in registry.backend_registrations()
        if item.readiness_contract_versions
    }
    assert supported == {("onlyalpha.indicator.sma", "1", OnlyCalculationBackendKind.RESEARCH, (1,))}


@pytest.mark.parametrize(
    "source",
    (
        "import onlyalpha.application as product",
        "from onlyalpha import application as product",
        "from ...application import handler",
        "__import__('onlyalpha.application')",
        "importlib.import_module('onlyalpha.application')",
    ),
)
def test_import_guard_detects_absolute_relative_alias_and_literal_dynamic_dependencies(source: str) -> None:
    imports = _imports(ast.parse(source), "onlyalpha.research.calculation")
    assert any(name == "onlyalpha.application" or name.startswith("onlyalpha.application.") for name in imports)


@pytest.mark.parametrize(
    "source",
    (
        "from onlyalpha.research import OnlyParquetResearchCalculationResultStoreV2",
        "from onlyalpha.research import OnlyResearchJobExecutor as Executor",
        "import onlyalpha.research as research",
        "from onlyalpha.research import *",
        "__import__('onlyalpha.research')",
        "from .. import OnlyParquetResearchCalculationResultStoreV2",
        "from onlyalpha import research as research",
    ),
)
def test_boundary_guard_rejects_root_reexport_entrypoint(source: str) -> None:
    imports = _imports(ast.parse(source), "onlyalpha.research.calculation")
    violations = _boundary_violations(
        imports,
        forbidden_prefixes=("onlyalpha.research.calculation.result_v2_store", "onlyalpha.research.job"),
        forbidden_exact_modules=AGGREGATE_REEXPORT_MODULES,
    )
    assert "onlyalpha.research" in violations


@pytest.mark.parametrize(
    "source",
    (
        "from onlyalpha.research.calculation import OnlyResearchCalculationExecutionEvidenceStoreV2",
        "from onlyalpha.research.calculation import OnlyParquetResearchCalculationResultStoreV2 as Store",
        "import onlyalpha.research.calculation as calculation",
        "from onlyalpha.research.calculation import *",
        "importlib.import_module('onlyalpha.research.calculation')",
        "from . import OnlyResearchCalculationExecutionEvidenceStoreV2",
        "from onlyalpha.research import calculation as calculation",
    ),
)
def test_boundary_guard_rejects_calculation_aggregate_reexport_entrypoint(source: str) -> None:
    imports = _imports(ast.parse(source), "onlyalpha.research.calculation")
    violations = _boundary_violations(
        imports,
        forbidden_prefixes=(
            "onlyalpha.research.calculation.result_v2_store",
            "onlyalpha.research.calculation.execution_evidence_v2",
        ),
        forbidden_exact_modules=AGGREGATE_REEXPORT_MODULES,
    )
    assert "onlyalpha.research.calculation" in violations


@pytest.mark.parametrize(
    "source",
    (
        "from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendExecutionV2",
        "from onlyalpha.research.calculation.readiness import OnlyResearchOutputReadiness",
        "from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationContract",
        "from onlyalpha.research.calculation.errors import OnlyResearchCalculationError",
    ),
)
def test_boundary_guard_allows_explicit_narrow_calculation_spi(source: str) -> None:
    imports = _imports(ast.parse(source), "onlyalpha.research.calculation")
    assert not _boundary_violations(
        imports,
        forbidden_prefixes=(
            "onlyalpha.research.calculation.result_v2_store",
            "onlyalpha.research.calculation.execution_evidence_v2",
        ),
        forbidden_exact_modules=AGGREGATE_REEXPORT_MODULES,
    )


@pytest.mark.parametrize(
    "name",
    (
        "onlyalpha.research.calculation.result_v2_store",
        "onlyalpha.research.calculation.result_v2_store.OnlyParquetResearchCalculationResultStoreV2",
        "onlyalpha.research.calculation.execution_evidence_v2",
        "onlyalpha.research.calculation.execution_evidence_v2.OnlyResearchCalculationExecutionEvidenceStoreV2",
    ),
)
def test_boundary_guard_retains_implementation_prefix_rejection(name: str) -> None:
    assert _boundary_violations(
        {name},
        forbidden_prefixes=(
            "onlyalpha.research.calculation.result_v2_store",
            "onlyalpha.research.calculation.execution_evidence_v2",
        ),
        forbidden_exact_modules=AGGREGATE_REEXPORT_MODULES,
    ) == {name}
