"""Regression checks for the source-linked timestamp symbolic boundary."""

from __future__ import annotations

import ctypes
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# This belongs to the Domain owner and imports only its repository check tool.
REPOSITORY = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "timestamp_conversion_formal", REPOSITORY / "scripts/timestamp_conversion_formal.py"
)
assert SPEC is not None and SPEC.loader is not None
formal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(formal)


@pytest.fixture
def source_tree(tmp_path):
    for relative in (*formal.BINDING_SHA256, formal.SOURCE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, target)
    return tmp_path


@pytest.mark.parametrize(
    "before,after",
    [
        ("use bigdecimal::num_bigint::BigInt;", "type BigInt = i128;"),
        ("use num_integer::Integer;", "use other_integer::Integer;"),
        ("unix_nanos: BigInt,", "unix_nanos: i128,"),
        ("unix_nanos: BigInt,", "unix_nanos: BigInt, other: bool,"),
        ("PartialEq, Eq,", "PartialOrd, Eq,"),
        ("Self { unix_nanos: value }", "Self { unix_nanos: value + 1 }"),
        ("pub struct OnlyTimestamp", "#[cfg(any())]\npub struct OnlyTimestamp"),
        ("impl OnlyTimestamp {", "#[cfg(any())]\nimpl OnlyTimestamp {"),
        ("impl OnlyTimestamp {", "impl OnlyTimestamp {\n    #[cfg(any())]"),
        ("value * 1000_u32", "value / 1000_u32"),
        ("value * 1000_u32", "value * 0_u32"),
        ("value * 1000_u32", "value * 4294967296_u32"),
        ("value * 1000_u32", "value * { 1000_u32 }"),
        ("self.unix_nanos.div_floor(&BigInt::from(1000_u32))", "self.unix_nanos / BigInt::from(1000_u32)"),
        ("Self::from_unix_nanos(value * 1000_u32)", "let value = value + 1; Self::from_unix_nanos(value * 1000_u32)"),
        ("impl OnlyTimestamp {", "impl PartialEq for OnlyTimestamp { }\nimpl OnlyTimestamp {"),
        ("impl OnlyTimestamp {", "impl OnlyTimestamp { }\nimpl OnlyTimestamp {"),
    ],
)
def test_unsupported_rust_shape_is_refused(source_tree, before, after):
    path = source_tree / formal.SOURCE
    source = path.read_text()
    assert before in source
    path.write_text(source.replace(before, after, 1))
    with pytest.raises(ValueError, match="TIMESTAMP_FORMAL_"):
        formal.source_projection(source_tree)


@pytest.mark.parametrize("relative", tuple(formal.BINDING_SHA256))
def test_module_type_or_dependency_binding_drift_is_refused(source_tree, relative):
    path = source_tree / relative
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="BINDING_REVIEW_REQUIRED"):
        formal.source_projection(source_tree)


def test_cargo_config_override_is_refused(source_tree):
    path = source_tree / ".cargo/config.toml"
    path.parent.mkdir()
    path.write_text("[patch.crates-io]\n")
    with pytest.raises(ValueError, match="CARGO_CONFIG_REVIEW_REQUIRED"):
        formal.source_projection(source_tree)


def test_projection_preserves_signed_floor_and_unbounded_integer_inputs(source_tree):
    expressions, _ = formal.source_projection(source_tree)
    projection, locations = formal.render_projection(expressions)
    namespace = {}
    exec(compile(projection, "projection.py", "exec"), namespace)
    assert set(locations) == set(formal.CONTRACTS)
    for value in (0, 1, -1, 1001, -1001, 10**1000, -(10**1000)):
        assert namespace["unix_micros_round_trip"](value) == value
        assert namespace["unix_millis_round_trip"](value) == value
        assert namespace["timestamp_unit_hierarchy"](value)
    assert namespace["to_unix_micros"](-1) == -1
    assert namespace["to_unix_micros"](-1001) == -2
    assert namespace["to_unix_millis"](-1) == -1
    assert namespace["to_unix_seconds"](-1) == -1


@pytest.mark.parametrize("variation", ("empty", "unknown", "missing", "duplicate", "wrong-line", "stderr", "nonzero"))
def test_exit_zero_or_incomplete_confirmation_never_confers_proof(variation):
    path = Path("/tmp/projection.py")
    locations = dict(zip(formal.CONTRACTS, (10, 20, 30), strict=True))
    lines = [f"{path}:{line}: info: Confirmed over all paths." for line in locations.values()]
    code, stderr = 0, ""
    if variation == "empty":
        lines = []
    elif variation == "unknown":
        lines[0] = f"{path}:10: info: Not confirmed."
    elif variation == "missing":
        lines.pop()
    elif variation == "duplicate":
        lines[0] = lines[1]
    elif variation == "wrong-line":
        lines[0] = f"{path}:11: info: Confirmed over all paths."
    elif variation == "stderr":
        stderr = "unrecognized analysis\n"
    else:
        code = 2
    result = subprocess.CompletedProcess([], code, "\n".join(lines), stderr)
    with pytest.raises(ValueError, match="NOT_ALL_CONFIRMED"):
        formal.require_confirmed(result, path, locations)


def test_real_crosshair_confirms_all_three_source_linked_contracts(source_tree):
    assert formal.verify(source_tree) == 0
    assert (source_tree / "test-results/timestamp-conversion-formal/last-run.json").is_file()


def test_changed_actual_multiplier_is_refuted_by_real_crosshair(source_tree):
    path = source_tree / formal.SOURCE
    path.write_text(path.read_text().replace("value * 1000_u32", "value * 1001_u32", 1))
    expressions, _ = formal.source_projection(source_tree)
    assert expressions["from_unix_micros"] == "value * 1001"
    with pytest.raises(ValueError, match="NOT_ALL_CONFIRMED"):
        formal.verify(source_tree)
    output = source_tree / "test-results/timestamp-conversion-formal"
    assert "false when calling unix_micros_round_trip(" in (output / "crosshair.stdout").read_text()
    assert not (output / "last-run.json").exists()


@pytest.mark.parametrize("variation", ("version", "path", "loader"))
def test_wrong_native_solver_or_library_outside_installed_package_is_refused(tmp_path, monkeypatch, variation):
    package = tmp_path / "z3"
    package.mkdir()
    init = package / "__init__.py"
    init.write_text("")
    library = package / "libz3.so"
    library.write_bytes(b"controlled native identity fixture")
    if variation == "path":
        library = tmp_path / "system-libz3.so"
        library.write_bytes(b"controlled wrong owner fixture")
    native = (4, 15, 5, 0) if variation == "version" else (4, 15, 4, 0)
    handle = ctypes.CDLL(None)
    pointer = handle.getpid
    handle._name = str(library)

    def getter():
        return None

    getter.__defaults__ = () if variation == "loader" else (SimpleNamespace(f=pointer),)
    monkeypatch.setitem(
        sys.modules,
        "z3",
        SimpleNamespace(
            get_version=lambda: native,
            __file__=str(init),
            z3core=SimpleNamespace(Z3_get_version=getter),
        ),
    )
    with pytest.raises(ValueError, match="NATIVE_SOLVER_.*_REVIEW_REQUIRED"):
        formal.solver_identity()
