"""Check the three timestamp contracts on a closed, source-linked integer projection.

This is not execution or verification of arbitrary Rust. The audited closure is
BigInt multiplication and num_integer::Integer.div_floor with positive u32
constants. Rust build, dependency, vector and replay gates remain independent.
Any source shape or dependency binding outside this closure requires review.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "crates/domain/src/time.rs"
TOOL_VERSIONS = {"crosshair-tool": "0.0.109", "z3-solver": "4.15.4.0"}
# Reviewed source envelope, excluding only the six extracted expression bodies.
ENVELOPE_SHA256 = "f0d7aa11928ee171416b49b717b43abdeb4e02cfd4e2ef4e098ae372a978bd33"
# Bind module loading, external type resolution, exact dependency versions and
# registry checksums. These conservative guards deliberately need fresh review
# after unrelated Cargo changes too; they never infer semantic compatibility.
BINDING_SHA256 = {
    "crates/domain/src/lib.rs": "db40d167a7e83ebd99e68c7b76073e2bf22756344950f2b34be3e7da5e04a211",
    "crates/domain/Cargo.toml": "59088d6dabee08a60eb840229378eb8a43d9c10089cc5a784e0880609f785cb7",
    "Cargo.toml": "ef57fd25346799ee37dc428626d9f765834540c4b133cb37291809c887e5bd27",
    "Cargo.lock": "720d80be9e4f81678d1633b0da8bb3d7d28a05c216e2482d6e684402339a10f7",
}
CONTRACTS = ("unix_micros_round_trip", "unix_millis_round_trip", "timestamp_unit_hierarchy")
NUMBER = r"([0-9]+(?:_[0-9]+)*)_u32"


def source_projection(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    bindings = {}
    for relative, expected in BINDING_SHA256.items():
        path = root / relative
        if path.is_symlink():
            raise ValueError("TIMESTAMP_FORMAL_BINDING_SYMLINK: " + relative)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("TIMESTAMP_FORMAL_BINDING_REVIEW_REQUIRED: " + relative)
        bindings[relative] = actual
    for directory in (root, root / "crates", root / "crates/domain"):
        if any((directory / ".cargo" / name).exists() for name in ("config", "config.toml")):
            raise ValueError("TIMESTAMP_FORMAL_CARGO_CONFIG_REVIEW_REQUIRED")
    path = root / SOURCE
    if path.is_symlink():
        raise ValueError("TIMESTAMP_FORMAL_SOURCE_SYMLINK")
    raw = path.read_bytes()
    source = raw.decode("utf-8")
    masked = source
    expressions = {}
    for unit in ("micros", "millis", "seconds"):
        for direction in ("from", "to"):
            name = f"{direction}_unix_{unit}"
            if direction == "from":
                signature = f"pub fn {name}(value: BigInt) -> Self"
                body = rf"Self::from_unix_nanos\(value \* {NUMBER}\)"
            else:
                signature = f"pub fn {name}(&self) -> BigInt"
                body = rf"self\.unix_nanos\.div_floor\(&BigInt::from\({NUMBER}\)\)"
            pattern = re.escape(signature) + r" \{\n        (" + body + r")\n    \}"
            matches = list(re.finditer(pattern, masked))
            if len(matches) != 1:
                raise ValueError("TIMESTAMP_FORMAL_UNSUPPORTED_SOURCE: " + name)
            match = matches[0]
            divisor = int(match.group(2).replace("_", ""))
            if not 0 < divisor <= 2**32 - 1:
                raise ValueError("TIMESTAMP_FORMAL_CONSTANT_OUTSIDE_POSITIVE_U32: " + name)
            expressions[name] = f"value {'*' if direction == 'from' else '//'} {divisor}"
            masked = masked[: match.start(1)] + f"__FORMAL_{name}__" + masked[match.end(1) :]
    if hashlib.sha256(masked.encode()).hexdigest() != ENVELOPE_SHA256:
        raise ValueError("TIMESTAMP_FORMAL_SOURCE_SHAPE_REVIEW_REQUIRED")
    bindings[SOURCE] = hashlib.sha256(raw).hexdigest()
    return expressions, bindings


def render_projection(expressions: dict[str, str]) -> tuple[str, dict[str, int]]:
    lines = [
        '"""Generated source-linked mathematical projection; not a Rust runtime."""',
        "",
    ]
    for name, expression in expressions.items():
        lines += [f"def {name}(value: int) -> int:", f"    return {expression}", ""]
    bodies = {
        "unix_micros_round_trip": ("int", "_ == value", "to_unix_micros(from_unix_micros(value))"),
        "unix_millis_round_trip": ("int", "_ == value", "to_unix_millis(from_unix_millis(value))"),
        "timestamp_unit_hierarchy": ("bool", "_", "from_unix_seconds(value) == from_unix_millis(value * 1000)"),
    }
    locations = {}
    for name in CONTRACTS:
        result, condition, expression = bodies[name]
        lines += [f"def {name}(value: int) -> {result}:", '    """', f"    post: {condition}"]
        locations[name] = len(lines)
        lines += ['    """', f"    return {expression}", ""]
    return "\n".join(lines), locations


def require_confirmed(result: subprocess.CompletedProcess[str], path: Path, locations: dict[str, int]) -> None:
    expected = {f"{path}:{line}: info: Confirmed over all paths." for line in locations.values()}
    actual = result.stdout.splitlines()
    if result.returncode != 0 or len(actual) != len(expected) or set(actual) != expected or result.stderr:
        raise ValueError("TIMESTAMP_FORMAL_NOT_ALL_CONFIRMED")


def solver_identity() -> tuple[tuple[int, ...], Path]:
    import z3

    native_version = tuple(z3.get_version())
    expected_native = tuple(int(part) for part in TOOL_VERSIONS["z3-solver"].split("."))
    if native_version != expected_native:
        raise ValueError("TIMESTAMP_FORMAL_NATIVE_SOLVER_VERSION_REVIEW_REQUIRED")
    defaults = z3.z3core.Z3_get_version.__defaults__
    if not isinstance(defaults, tuple) or len(defaults) != 1:
        raise ValueError("TIMESTAMP_FORMAL_NATIVE_SOLVER_LOADER_REVIEW_REQUIRED")
    function = getattr(defaults[0], "f", None)
    objects = getattr(function, "_objects", None)
    if not isinstance(function, ctypes._CFuncPtr) or not isinstance(objects, dict):
        raise ValueError("TIMESTAMP_FORMAL_NATIVE_SOLVER_LOADER_REVIEW_REQUIRED")
    libraries = [value for value in objects.values() if isinstance(value, ctypes.CDLL)]
    if len(libraries) != 1 or not isinstance(libraries[0]._name, str):
        raise ValueError("TIMESTAMP_FORMAL_NATIVE_SOLVER_LOADER_REVIEW_REQUIRED")
    native_library = Path(libraries[0]._name)
    if not native_library.is_absolute():
        raise ValueError("TIMESTAMP_FORMAL_NATIVE_SOLVER_PATH_REVIEW_REQUIRED")
    native_library = native_library.resolve(strict=True)
    package_directory = Path(z3.__file__).resolve(strict=True).parent
    if not native_library.is_relative_to(package_directory):
        raise ValueError("TIMESTAMP_FORMAL_NATIVE_SOLVER_PATH_REVIEW_REQUIRED")
    return native_version, native_library


def verify(root: Path) -> int:
    output = root / "test-results/timestamp-conversion-formal"
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "last-run.json"
    receipt.unlink(missing_ok=True)
    for name in ("crosshair.stdout", "crosshair.stderr", "projection.py"):
        (output / name).unlink(missing_ok=True)
    expressions, bindings = source_projection(root)
    versions = {name: importlib.metadata.version(name) for name in TOOL_VERSIONS}
    if versions != TOOL_VERSIONS:
        raise ValueError("TIMESTAMP_FORMAL_TOOL_VERSION_REVIEW_REQUIRED")
    native_version, native_library = solver_identity()
    projection, locations = render_projection(expressions)
    (output / "projection.py").write_text(projection, encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="projection-", dir=output) as temporary:
        path = Path(temporary).resolve() / "timestamp_contracts.py"
        path.write_text(projection, encoding="utf-8")
        command = [
            sys.executable,
            "-I",
            "-m",
            "crosshair",
            "check",
            "--analysis_kind=PEP316",
            "--report_all",
            "--per_condition_timeout=30",
            str(path),
        ]
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False, timeout=120)
        (output / "crosshair.stdout").write_text(result.stdout, encoding="utf-8")
        (output / "crosshair.stderr").write_text(result.stderr, encoding="utf-8")
        require_confirmed(result, path, locations)
    # A successful result is tied to the same source and dependency bindings.
    if source_projection(root) != (expressions, bindings):
        raise ValueError("TIMESTAMP_FORMAL_SOURCE_CHANGED")
    receipt.write_text(
        json.dumps(
            {
                "scope": "source-linked BigInt timestamp conversion projection; not arbitrary Rust verification",
                "source_sha256": bindings,
                "tools": versions,
                "native_solver_version": native_version,
                "native_solver_library": str(native_library),
                "expressions": expressions,
                "projection_sha256": hashlib.sha256(projection.encode()).hexdigest(),
                "contracts": {name: "CONFIRMED" for name in CONTRACTS},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print("TIMESTAMP_CONVERSION_FORMAL: 3 source-linked contracts CONFIRMED")
    return 0


if __name__ == "__main__":
    raise SystemExit(verify(ROOT))
