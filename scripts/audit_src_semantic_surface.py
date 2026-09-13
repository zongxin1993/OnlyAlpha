"""Report the durable ``src/onlyalpha`` semantic surface.

This is intentionally report-only.  Import reachability is evidence for review,
not a deletion authority: dynamic loading, package entry points and historical
readers still require human confirmation before a module can be removed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "onlyalpha"

# These modules implement persistence, transport, operator, or local integration
# boundaries.  They remain in this package until a separately authorized
# relocation; classification does not imply that they are dead.
EXTERNAL_ADAPTER_PREFIXES = (
    "onlyalpha.backtest.worker_main",
    "onlyalpha.persistence",
    "onlyalpha.output",
    "onlyalpha.storage",
    "onlyalpha.scenario",
    "onlyalpha.research.worker_main",
    "onlyalpha.cluster.demo",
    "onlyalpha.cluster.loader",
    "onlyalpha.cluster.registry",
    "onlyalpha.plugin.testing",
)
ENTRYPOINT_MODULES = {
    "onlyalpha.backtest.worker_main",
    "onlyalpha.research.worker_main",
}


@dataclass(frozen=True, slots=True)
class ModuleRecord:
    path: Path
    module: str
    classification: str
    production_importers: tuple[str, ...]


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(("onlyalpha", *parts))


def _production_files() -> tuple[Path, ...]:
    roots = [SOURCE_ROOT]
    for parent in (ROOT / "packages", ROOT / "plugs"):
        roots.extend(path for path in parent.glob("*/src") if path.is_dir())
    return tuple(sorted(path for root in roots for path in root.rglob("*.py")))


def _resolve_relative(importer: str, module: str | None, level: int, *, package_module: bool) -> str:
    package = importer if package_module else importer.rsplit(".", 1)[0]
    if level > 1:
        package_parts = package.split(".")[: -(level - 1)]
    else:
        package_parts = package.split(".")
    return ".".join((*package_parts, *(module.split(".") if module else ())))


def _imports(path: Path, importer: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names if alias.name.startswith("onlyalpha."))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                name = _resolve_relative(importer, node.module, node.level, package_module=path.name == "__init__.py")
            else:
                name = node.module or ""
            if name.startswith("onlyalpha."):
                result.add(name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("onlyalpha."):
                result.add(node.value)
    return result


def collect() -> tuple[ModuleRecord, ...]:
    source_files = tuple(sorted(SOURCE_ROOT.rglob("*.py")))
    modules = {_module_name(path): path for path in source_files}
    inbound: dict[str, set[str]] = {module: set() for module in modules}
    for path in _production_files():
        importer = _module_name(path) if path.is_relative_to(SOURCE_ROOT) else str(path.relative_to(ROOT))
        for imported in _imports(path, importer):
            imported_parts = imported.split(".")
            for size in range(2, len(imported_parts) + 1):
                candidate = ".".join(imported_parts[:size])
                if candidate in inbound and candidate != importer:
                    inbound[candidate].add(importer)
    for entrypoint in ENTRYPOINT_MODULES:
        if entrypoint in inbound:
            inbound[entrypoint].add("packaging entry point")
    records: list[ModuleRecord] = []
    for module, path in sorted(modules.items()):
        classification = "EXTERNAL_ADAPTER" if module.startswith(EXTERNAL_ADAPTER_PREFIXES) else "CANONICAL"
        records.append(ModuleRecord(path, module, classification, tuple(sorted(inbound[module]))))
    return tuple(records)


def main() -> None:
    records = collect()
    candidates = tuple(record for record in records if not record.production_importers and record.module != "onlyalpha")
    counts = {
        classification: sum(record.classification == classification for record in records)
        for classification in (
            "CANONICAL",
            "EXTERNAL_ADAPTER",
        )
    }
    print(f"Total src modules: {len(records)}")
    print(f"CANONICAL: {counts['CANONICAL']}")
    print(f"EXTERNAL_ADAPTER: {counts['EXTERNAL_ADAPTER']}")
    print(f"Production-unreachable candidates (review only): {len(candidates)}")
    for record in candidates:
        print(f"- {record.module} [{record.classification}] {record.path.relative_to(ROOT)}")
    print("\nComplete module inventory:")
    print("| Module | Path | Classification | Production importers |")
    print("|---|---|---|---:|")
    for record in records:
        print(
            f"| `{record.module}` | `{record.path.relative_to(ROOT)}` | "
            f"`{record.classification}` | {len(record.production_importers)} |"
        )


if __name__ == "__main__":
    main()
