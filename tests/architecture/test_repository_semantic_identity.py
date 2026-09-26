from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]
PERMANENT_SURFACES = (
    "src",
    "packages",
    "plugs",
    "database",
    "tests",
    "test-data",
    "fixtures",
    "schemas",
    "config",
    "scripts",
    "examples",
    "contracts",
    "deploy",
    ".github/workflows",
)
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
TOKEN = re.compile(
    r"(?i)(?<![a-z0-9])(?:p\d{1,3}(?:[._-]\d{1,3}[a-z]?)?|"
    r"pa(?:[._-]?\d{1,3})(?:[._-][a-z0-9]+)*|"
    r"[abk]\d{1,3}(?:[._-]\d{1,3}[a-z]?)?|"
    r"closure[._-]\d+|phase[._-]\d+|milestone[._-]\d+|task[._-]\d+|"
    r"final[._-]fix|second[._-]fix|temporary[._-]fix|new[._-]schema|"
    r"old[._-]runtime|new[._-]runtime|cleanup[._-]helper)(?![a-z0-9])"
)
IDENTIFIER_TOKEN = re.compile(
    r"(?i)(?:^|_)(p\d{1,3}(?:_\d{1,3}[a-z]?)?|pa_?\d{1,3}(?:_[a-z0-9]+)*|"
    r"[abk]\d{1,3}(?:_\d{1,3}[a-z]?)?|closure_\d+|phase_\d+|"
    r"milestone_\d+|task_\d+|final_fix|second_fix|temporary_fix|new_schema|"
    r"old_runtime|new_runtime|cleanup_helper)(?:_|$)"
)
MIGRATION = re.compile(r"^\d{4}_(?P<suffix>.+)\.sql$")
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
CONTENT_SCAN_EXCLUSIONS = {"tests/architecture/test_repository_semantic_identity.py"}
IGNORED_RUNTIME_ARTIFACTS = {"packages/onlyalpha-web-console/.impeccable/live/server.json"}
GENERATED_DIRECTORY_NAMES = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".test-cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "test-results",
}

# These are exact durable identities or formal architecture identifiers. They
# are not directory-wide waivers and may not be extended for convenience.
IDENTITY_ALLOWLIST = {
    "a0_golden_v1": "immutable Binance Golden bundle kind",
    "authorized-a0-corrections.json": "one-shot OpenAPI correction manifest filename",
    "0109-product-api-v2-a0-pre-freeze-contract-correction.md": "accepted ADR filename referenced by the correction manifest",
    "authorized_a0_corrections": "authority handle for the exact correction manifest",
    "authorized_a0_correction": "serialized OpenAPI correction identity",
    "required_a0_contract_correction": "correction manifest classification",
    "p9_calculation_equivalence_v2": "historical calculation-equivalence evidence identity",
    "onlyalpha_p9_calculation_equivalence_v2": "historical calculation-equivalence authority identity",
    "a01": "product authority contract actor identity",
    "a03": "product authority contract actor identity",
    "a05": "product authority contract actor identity",
    "a07": "product authority contract actor identity",
    "a10": "product authority contract actor identity",
    "a12": "product authority contract actor identity",
    "a13": "product authority contract actor identity",
    "a16": "product authority contract actor identity",
    "a17": "product authority contract actor identity",
    "a23": "product authority contract actor identity",
    "a99": "invalid product authority actor used by a negative test",
    "k06": "product authority contract constructor identity",
    "k07": "product authority contract constructor identity",
    "new_runtime_initialized": "canonical runtime recovery status",
}
PATH_ALLOWLIST = {
    "contracts/product-api/v2/authorized-a0-corrections.json": "one-shot OpenAPI correction manifest",
}
IDENTIFIER_ALLOWLIST = {"_b64": "standard base64 abbreviation"}


def _files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative in PERMANENT_SURFACES:
        surface = root / relative
        if surface.is_file():
            files.append(surface)
        elif surface.is_dir():
            files.extend(
                path
                for path in surface.rglob("*")
                if path.is_file() and not GENERATED_DIRECTORY_NAMES.intersection(path.parts)
            )
    return tuple(sorted(set(files)))


def _allowlisted(text: str, match: re.Match[str]) -> bool:
    normalized = text.casefold()
    start, end = match.span()
    while start and (normalized[start - 1].isalnum() or normalized[start - 1] in "_.-"):
        start -= 1
    while end < len(normalized) and (normalized[end].isalnum() or normalized[end] in "_.-"):
        end += 1
    return normalized[start:end] in IDENTITY_ALLOWLIST


def _matches(text: str, pattern: re.Pattern[str] = TOKEN) -> tuple[re.Match[str], ...]:
    return tuple(match for match in pattern.finditer(text) if not _allowlisted(text, match))


def _diagnostic(relative: str, line: int | None, category: str, identifier: str, token: str) -> str:
    location = f"{relative}:{line}" if line is not None else relative
    return (
        f"{location}: {category} {identifier!r} contains forbidden process token {token!r}; "
        "rename it by stable domain behavior or invariant"
    )


def _python_violations(path: Path, relative: str) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name not in IDENTIFIER_ALLOWLIST:
                for match in _matches(node.name, IDENTIFIER_TOKEN):
                    violations.append(
                        _diagnostic(relative, node.lineno, "python identifier", node.name, match.group(1))
                    )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    for match in _matches(target.id, IDENTIFIER_TOKEN):
                        violations.append(
                            _diagnostic(relative, node.lineno, "constant identifier", target.id, match.group(1))
                        )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if UUID4.fullmatch(node.value):
                continue
            for pattern in (TOKEN, IDENTIFIER_TOKEN):
                for match in _matches(node.value, pattern):
                    token = match.group(1) if pattern is IDENTIFIER_TOKEN else match.group(0)
                    violations.append(_diagnostic(relative, node.lineno, "canonical ID", node.value, token))
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            for match in _matches(token.string):
                violations.append(
                    _diagnostic(relative, token.start[0], "comment", token.string.strip(), match.group(0))
                )
    return violations


def _text_violations(path: Path, relative: str) -> list[str]:
    violations: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for pattern in (TOKEN, IDENTIFIER_TOKEN):
            for match in _matches(line, pattern):
                token = match.group(1) if pattern is IDENTIFIER_TOKEN else match.group(0)
                violations.append(_diagnostic(relative, line_number, "canonical ID", line.strip(), token))
    return violations


def semantic_identity_violations(root: Path = ROOT) -> tuple[str, ...]:
    violations: list[str] = []
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        if relative in IGNORED_RUNTIME_ARTIFACTS:
            continue
        migration = MIGRATION.fullmatch(path.name) if "database/postgres/migrations" in relative else None
        if migration:
            for match in _matches(migration.group("suffix"), IDENTIFIER_TOKEN):
                violations.append(
                    _diagnostic(relative, None, "migration suffix", migration.group("suffix"), match.group(1))
                )
        elif relative not in PATH_ALLOWLIST:
            for part in Path(relative).parts:
                for match in _matches(part, IDENTIFIER_TOKEN):
                    violations.append(_diagnostic(relative, None, "path", relative, match.group(1)))
        if path.suffix not in TEXT_SUFFIXES:
            continue
        if relative in CONTENT_SCAN_EXCLUSIONS:
            continue
        try:
            violations.extend(
                _python_violations(path, relative) if path.suffix == ".py" else _text_violations(path, relative)
            )
        except (SyntaxError, UnicodeDecodeError):
            continue
    return tuple(dict.fromkeys(violations))


def test_permanent_repository_assets_use_semantic_identity() -> None:
    assert semantic_identity_violations() == ()


def test_semantic_identity_allowlists_are_explicit_and_narrow() -> None:
    assert IDENTITY_ALLOWLIST
    assert PATH_ALLOWLIST
    assert all("*" not in entry and "?" not in entry for entry in PATH_ALLOWLIST)
    assert all(reason.strip() for reason in IDENTITY_ALLOWLIST.values())
    assert all(reason.strip() for reason in PATH_ALLOWLIST.values())
    assert all("*" not in entry and "?" not in entry for entry in IGNORED_RUNTIME_ARTIFACTS)


def test_ignored_runtime_artifact_is_not_a_semantic_project_input(tmp_path: Path) -> None:
    artifact = tmp_path / "packages/onlyalpha-web-console/.impeccable/live/server.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"token":"phase-1"}', encoding="utf-8")

    assert semantic_identity_violations(tmp_path) == ()


def test_repository_semantic_identity_gate_reports_each_asset_category(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "database/postgres/migrations").mkdir(parents=True)
    (tmp_path / "test-data/golden").mkdir(parents=True)
    (tmp_path / "src/p9_strategy.py").write_text("VALUE = 'stable'\n", encoding="utf-8")
    (tmp_path / "tests/test_runtime.py").write_text(
        "def test_b31_runtime():\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "database/postgres/migrations/0010_p9_0_closure.sql").write_text(
        "CREATE TABLE stable_fact (id INTEGER);\n",
        encoding="utf-8",
    )
    (tmp_path / "test-data/golden/case.json").write_text(
        '{"case_id": "closure_2"}\n',
        encoding="utf-8",
    )

    violations = semantic_identity_violations(tmp_path)

    assert any("src/p9_strategy.py" in item and "path" in item and "p9" in item for item in violations)
    assert any(
        "tests/test_runtime.py:1" in item and "python identifier" in item and "b31" in item for item in violations
    )
    assert any("0010_p9_0_closure.sql" in item and "migration suffix" in item for item in violations)
    assert any("test-data/golden/case.json:1" in item and "canonical ID" in item for item in violations)


def test_repository_semantic_identity_gate_allows_process_docs_and_business_identifiers(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs/tasks").mkdir(parents=True)
    (tmp_path / "packages/example/build").mkdir(parents=True)
    (tmp_path / "src/business.py").write_text(
        "def _b64(value: bytes) -> str:\n    return value.hex()\n\nSYMBOL = 'CAB1'\nARCHITECTURE_ACTOR = 'A05'\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/tasks/PA-4_AUDIT.md").write_text("P9 closure task\n", encoding="utf-8")
    (tmp_path / "packages/example/build/p9_stale.py").write_text("P9 = 'generated'\n", encoding="utf-8")

    assert semantic_identity_violations(tmp_path) == ()


def test_repository_semantic_identity_allowlist_rejects_prefixed_or_suffixed_identity(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/business.py").write_text(
        "CASE_ID = 'prefix-a0_golden_v1-suffix'\n",
        encoding="utf-8",
    )

    violations = semantic_identity_violations(tmp_path)

    assert any("prefix-a0_golden_v1-suffix" in item and "a0" in item for item in violations)
