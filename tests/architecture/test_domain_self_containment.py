"""ADR-0005 guard: onlyalpha.domain depends only on the standard library and its own modules."""

import sys
from pathlib import Path

from tests.architecture._architecture_imports import canonical_imports_for_path

DOMAIN_ROOT = Path("src/onlyalpha/domain")
REPO_ROOT = Path(".")


def _is_allowed(module: str) -> bool:
    if module == "onlyalpha.domain" or module.startswith("onlyalpha.domain."):
        return True
    return module.partition(".")[0] in sys.stdlib_module_names


def test_domain_modules_import_only_stdlib_and_domain() -> None:
    paths = sorted(DOMAIN_ROOT.rglob("*.py"))
    assert paths
    violations = [
        f"{path.relative_to(REPO_ROOT)}: {module}"
        for path in paths
        for capability in canonical_imports_for_path(path, REPO_ROOT)
        for module in (capability[1],)
        if len(capability) >= 2 and not _is_allowed(module)
    ]
    assert not violations
