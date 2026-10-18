"""Locked offline Linux validation of the non-activated Rust Kernel library."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dev_verification import source_inputs  # noqa: E402


def build_commands(target: str) -> list[list[str]]:
    base = ["--workspace", "--frozen", "--offline", "--target", target, "-j1"]
    return [
        ["cargo", "fmt", "--all", "--", "--check"],
        ["cargo", "clippy", *base, "--all-targets", "--", "-D", "warnings"],
        *[
            ["cargo", action, *base, *profile, *(["--", "--test-threads=1"] if action == "test" else [])]
            for action in ("test", "build")
            for profile in ([], ["--release"])
        ],
    ]


def compiler_environment(inherited: Mapping[str, str], target_dir: Path) -> dict[str, str]:
    env = {
        key: value for key, value in inherited.items() if not key.startswith(("RUST", "CARGO")) or key == "RUSTUP_HOME"
    }
    env.update(
        CARGO_HOME=str(target_dir.parent / "cargo-home"),
        CARGO_NET_OFFLINE="true",
        RUSTUP_AUTO_INSTALL="0",
        CARGO_BUILD_JOBS="1",
        CARGO_TARGET_DIR=str(target_dir),
    )
    return env


# Independently reviewed public registry closure, excluding local release metadata.
REGISTRY_LOCK_SHA256 = "5b640f52cbcb0afc623fd1755692efee625a444ec9dbd17e0869eafba4f6a03f"
DOMAIN_DEPENDENCIES = {
    "tz-rs": {"version": "=0.7.3", "default-features": False, "features": ["alloc"]},
    "jiff": {"version": "=0.2.38", "default-features": False, "features": ["std"]},
    "sha2": {"version": "=0.11.1", "default-features": False},
    "bigdecimal": {"version": "=0.4.11", "default-features": False, "features": ["std"]},
    "num-integer": {"version": "=0.1.46", "default-features": False, "features": ["std"]},
    "serde_json": {"version": "=1.0.154", "default-features": False, "features": ["std", "arbitrary_precision"]},
}


CLOCK_DEPENDENCIES = {
    "onlyalpha-domain": {"path": "../domain"},
    "num-bigint": {"version": "=0.4.8", "default-features": False, "features": ["std"]},
}


MARKET_DATA_STATE_DEPENDENCIES = {**CLOCK_DEPENDENCIES, "serde_json": DOMAIN_DEPENDENCIES["serde_json"]}


EVENT_DEPENDENCIES = {**CLOCK_DEPENDENCIES, "serde_json": DOMAIN_DEPENDENCIES["serde_json"]}


def validate_workspace(root: Path) -> None:
    modules = {
        "onlyalpha-domain": "crates/onlyalpha-kernel/domain",
        "onlyalpha-kernel": "crates/onlyalpha-kernel/core",
        "onlyalpha-clock": "crates/onlyalpha-kernel/clock",
        "onlyalpha-event": "crates/onlyalpha-kernel/event",
        "onlyalpha-market-data-state": "crates/onlyalpha-kernel/market_data_state",
    }
    expected = set(modules)
    workspace = tomllib.loads((root / "Cargo.toml").read_text())["workspace"]
    if set(workspace["members"]) != set(modules.values()):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    packages = tomllib.loads((root / "Cargo.lock").read_text())["package"]
    local = [item for item in packages if "source" not in item]
    registry = sorted((item for item in packages if "source" in item), key=lambda item: (item["name"], item["version"]))
    if len(local) != len(expected) or {item["name"] for item in local} != expected:
        raise ValueError("RUST_KERNEL_DEPENDENCY_REVIEW_REQUIRED")
    domain = tomllib.loads((root / "crates/onlyalpha-kernel/domain/Cargo.toml").read_text())
    if registry:
        digest = hashlib.sha256(json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if REGISTRY_LOCK_SHA256 != digest or any(
            item["source"] != "registry+https://github.com/rust-lang/crates.io-index"
            or re.fullmatch(r"[0-9a-f]{64}", item.get("checksum", "")) is None
            for item in registry
        ):
            raise ValueError("RUST_KERNEL_DEPENDENCY_REVIEW_REQUIRED")
    for name in expected:
        manifest = tomllib.loads((root / modules[name] / "Cargo.toml").read_text())
        if manifest["package"]["name"] != name:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        sections = [manifest, *manifest.get("target", {}).values()]
        for section in sections:
            for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
                for alias, config in section.get(kind, {}).items():
                    dependency = config.get("package", alias) if isinstance(config, dict) else alias
                    admitted = (
                        name == "onlyalpha-domain"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == DOMAIN_DEPENDENCIES.get(alias)
                    ) or (
                        name == "onlyalpha-kernel"
                        and dependency == "onlyalpha-domain"
                        and config == {"path": "../domain"}
                    )
                    admitted = admitted or (
                        name == "onlyalpha-clock"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == CLOCK_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-event"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == EVENT_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-market-data-state"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == MARKET_DATA_STATE_DEPENDENCIES.get(alias)
                    )
                    if not admitted:
                        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if registry and domain.get("dependencies") != DOMAIN_DEPENDENCIES:
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if registry:
        clock = tomllib.loads((root / modules["onlyalpha-clock"] / "Cargo.toml").read_text())
        if clock.get("dependencies") != CLOCK_DEPENDENCIES:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

        event = tomllib.loads((root / modules["onlyalpha-event"] / "Cargo.toml").read_text())
        if event.get("dependencies") != EVENT_DEPENDENCIES:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

        state = tomllib.loads((root / modules["onlyalpha-market-data-state"] / "Cargo.toml").read_text())
        if state.get("dependencies") != MARKET_DATA_STATE_DEPENDENCIES:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def prepare_cargo_home(registry: Path, home: Path) -> None:
    """Seed offline builds from the admitted immutable dev image, not a mutable prior cache."""
    if home.is_symlink() or not registry.is_dir() or registry.is_symlink():
        raise ValueError("RUST_KERNEL_CARGO_HOME_NOT_ADMITTED")
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    shutil.copytree(registry, home / "registry")


def _hidden_rust_input(text: str) -> bool:
    return bool(re.search(r"#\s*\[\s*(?:path\s*=|cfg_attr\b)|\b(?:include|env|option_env)\s*!", text))


def validate_domain_sources(root: Path) -> None:
    """Reject implicit source/build inputs that bypass the declared Cargo graph."""
    domain = root / "crates/onlyalpha-kernel/domain"
    if (domain / "build.rs").exists():
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    manifest_path = domain / "Cargo.toml"
    if manifest_path.exists():
        manifest = tomllib.loads(manifest_path.read_text())
        if (
            manifest.get("package", {}).get("build", False) is not False
            or manifest.get("lib", {}).get("path", "src/lib.rs") != "src/lib.rs"
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    permitted = {
        "../../../../test-data/domain/numeric-v1.tsv",
        "../../../../test-data/domain/rounding-v1.tsv",
        "../../../../test-data/domain/value-records-v1.jsonl",
        "../../../../test-data/domain/fee-authority-v1.jsonl",
        "../../../../test-data/domain/instrument-records-v2.jsonl",
        "../../../../test-data/domain/fact-records-v1.jsonl",
        "../../../../test-data/domain/temporal-records-v1.jsonl",
        "../../../../test-data/domain/timezone-v1.jsonl",
        "../../../../test-data/domain/calendar-boundaries-v1.jsonl",
        "../../../../test-data/domain/bar-identity-v3.jsonl",
        "../../../../test-data/domain/instant-conversion-v1.tsv",
        "../../../../test-data/domain/time-ranges-v1.jsonl",
    }
    for path in domain.rglob("*.rs"):
        text = path.read_text()
        if path.is_symlink() or _hidden_rust_input(text):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        for macro in re.finditer(r"\b(include_str|include_bytes)\s*!\s*\(([^)]*)\)", text):
            argument = macro[2].strip()
            admitted = path.parent == domain / "tests" and argument in {f'"{name}"' for name in permitted}
            if path == domain / "src/tzdb_rules.rs" and macro[1] == "include_bytes":
                dataset = json.loads((domain / "resources/tzdata/2026.3/dataset.json").read_text())
                admitted = argument in {f'"../resources/tzdata/2026.3/{name}"' for name in dataset["zones"]}
            if not admitted:
                raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_clock_sources(root: Path) -> None:
    """Keep native effects and undeclared source inputs outside deterministic Clock modules."""
    clock = root / "crates/onlyalpha-kernel/clock"
    if (clock / "build.rs").exists():
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    manifest_path = clock / "Cargo.toml"
    if manifest_path.exists():
        manifest = tomllib.loads(manifest_path.read_text())
        if (
            manifest.get("package", {}).get("build", False) is not False
            or manifest.get("lib", {}).get("path", "src/lib.rs") != "src/lib.rs"
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    for path in clock.rglob("*.rs"):
        text = path.read_text()
        if path.is_symlink() or _hidden_rust_input(text):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        for macro in re.finditer(r"\b(include_str|include_bytes)\s*!\s*\(\s*([^)]*)\)", text):
            if not (
                path.parent == clock / "tests"
                and macro[1] == "include_str"
                and macro[2].strip()
                in {'"../../../../test-data/clock/timers-v1.tsv"', '"../../../../test-data/clock/lifecycle-v1.tsv"'}
            ):
                raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        if path.is_relative_to(clock / "src") and path != clock / "src/native.rs":
            if re.search(
                r"\b(?:SystemTime|Instant|UNIX_EPOCH|Condvar|thread|sleep)\b|\bstd\s*::\s*time\b|\buse\s+std\s*::\s*\{[^;]*\btime\b",
                text,
            ):
                raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def _validate_pure_sources(root: Path, area: str, permitted: set[str]) -> None:
    event = root / "crates/onlyalpha-kernel" / area
    manifest_path = event / "Cargo.toml"
    if (event / "build.rs").exists():
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if manifest_path.exists():
        manifest = tomllib.loads(manifest_path.read_text())
        if (
            manifest.get("package", {}).get("build", False) is not False
            or manifest.get("lib", {}).get("path", "src/lib.rs") != "src/lib.rs"
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    for path in event.rglob("*.rs"):
        text = path.read_text()
        if path.is_symlink() or _hidden_rust_input(text):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        for macro in re.finditer(r"\b(include_str|include_bytes)\s*!\s*\(([^)]*)\)", text):
            if path.parent != event / "tests" or macro[1] != "include_str" or macro[2].strip() not in permitted:
                raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        code = re.sub(r"(?m)^\s*//.*$", "", text)
        if path.is_relative_to(event / "src") and re.search(
            r"\b(?:SystemTime|Instant|UNIX_EPOCH|Condvar|thread|sleep|new_v4|new_v7|random|File|TcpStream|UdpSocket|Command|getrandom)\b|\bstd\s*::\s*(?:time|fs|net|process|env)\b|\buse\s+std\s*::\s*\{[^;]*\b(?:time|fs|net|process|env)\b",
            code,
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_event_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "event",
        {
            '"../../../../test-data/event/records-v2.jsonl"',
            '"../../../../test-data/event/delivery-v1.jsonl"',
        },
    )


def validate_market_data_state_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "market_data_state",
        {
            '"../../../../test-data/market-data-state/operations-v1.jsonl"',
            '"../../../../test-data/market-data-state/records-v2.jsonl"',
        },
    )
    for path in (root / "crates/onlyalpha-kernel/market_data_state/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?:clock|event|kernel|runtime|indicator|factor|provider|storage)\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def _isolated_modules(root: Path, destination: Path, modules: tuple[str, ...]) -> Path:
    destination.mkdir(parents=True)
    for module in modules:
        relative = Path("crates/onlyalpha-kernel") / module
        shutil.copytree(root / relative, destination / relative)
        data = Path("test-data") / module.replace("_", "-")
        shutil.copytree(root / data, destination / data)
    members = [f"crates/onlyalpha-kernel/{module}" for module in modules]
    manifest = re.sub(
        r"(?m)^members\s*=.*$", "members = " + json.dumps(members), (root / "Cargo.toml").read_text(), count=1
    )
    (destination / "Cargo.toml").write_text(manifest)
    shutil.copyfile(root / "rust-toolchain.toml", destination / "rust-toolchain.toml")
    chunks = (root / "Cargo.lock").read_text().split("\n[[package]]\n")
    retained = []
    for chunk in chunks[1:]:
        package = tomllib.loads("[[package]]\n" + chunk)["package"][0]
        if "source" in package or package["name"] in {"onlyalpha-" + module.replace("_", "-") for module in modules}:
            retained.append(chunk)
    (destination / "Cargo.lock").write_text(chunks[0] + "".join("\n[[package]]\n" + chunk for chunk in retained))
    return destination / "Cargo.toml"


def isolated_domain(root: Path, destination: Path) -> Path:
    """Materialize Domain without Kernel/Clock, application or undeclared source."""
    return _isolated_modules(root, destination, ("domain",))


def isolated_clock(root: Path, destination: Path) -> Path:
    """Materialize Clock and its declared Domain closure; never the Predicate/application tree."""
    return _isolated_modules(root, destination, ("domain", "clock"))


def isolated_event(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "event"))


def isolated_market_data_state(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "market_data_state"))


def main() -> int:
    artifacts = ROOT / "test-results/rust-kernel"
    artifacts.mkdir(parents=True, exist_ok=True)
    receipt = artifacts / "last-run.json"
    receipt.unlink(missing_ok=True)
    if sys.platform != "linux":
        raise ValueError("RUST_KERNEL_LINUX_REQUIRED: use the canonical dev container")
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    env = compiler_environment(os.environ, artifacts / "target")
    channel = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    env["RUSTUP_TOOLCHAIN"] = channel
    compiler = subprocess.check_output(["rustc", "--version", "--verbose"], cwd=ROOT, env=env, text=True)
    if f"release: {channel}\n" not in compiler or f"host: {target}\n" not in compiler:
        raise ValueError("RUST_KERNEL_TOOLCHAIN_MISMATCH")
    validate_workspace(ROOT)
    validate_domain_sources(ROOT)
    validate_clock_sources(ROOT)
    validate_event_sources(ROOT)
    validate_market_data_state_sources(ROOT)
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    before = source_inputs(ROOT)
    for guard in (
        "scripts/domain_unicode_tables.py",
        "scripts/domain_timezone_data.py",
        "scripts/predicate_vectors.py",
        "scripts/integer_predicate_vectors.py",
        "scripts/integer_literal_vectors.py",
        "scripts/scalar_equality_vectors.py",
        "scripts/decimal_predicate_vectors.py",
        "scripts/decimal_literal_vectors.py",
    ):
        subprocess.run([sys.executable, str(ROOT / guard), "--check"], cwd=ROOT, env=env, check=True)
    for command in build_commands(target):
        print("CHECK", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, env=env, check=True)
    for name, materialize in (
        ("domain", isolated_domain),
        ("clock", isolated_clock),
        ("event", isolated_event),
        ("market-data-state", isolated_market_data_state),
    ):
        with tempfile.TemporaryDirectory(prefix=f"{name}-isolated-", dir=artifacts) as directory:
            manifest = materialize(ROOT, Path(directory) / "source")
            isolated_env = dict(env, CARGO_TARGET_DIR=str(Path(directory) / "target"))
            for profile in ([], ["--release"]):
                command = [
                    "cargo",
                    "test",
                    "--manifest-path",
                    str(manifest),
                    "-p",
                    f"onlyalpha-{name}",
                    "--frozen",
                    "--offline",
                    "--target",
                    target,
                    "-j1",
                    *profile,
                    "--",
                    "--test-threads=1",
                ]
                print(f"{name.upper()}_ISOLATED", " ".join(command), flush=True)
                subprocess.run(command, cwd=manifest.parent, env=isolated_env, check=True)
    if before != source_inputs(ROOT):
        raise ValueError("RUST_KERNEL_SOURCE_CHANGED")

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    binaries = {
        profile: digest(artifacts / "target" / target / profile / "libonlyalpha_kernel.rlib")
        for profile in ("debug", "release")
    }
    binaries.update(
        {
            f"{profile}_predicate_diagnostic": digest(artifacts / "target" / target / profile / "predicate-diagnostic")
            for profile in ("debug", "release")
        }
    )
    receipt.write_text(
        json.dumps(
            {
                "compiler": compiler,
                "cargo": subprocess.check_output(["cargo", "--version"], cwd=ROOT, env=env, text=True).strip(),
                "target": target,
                "source_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
                "cargo_lock_sha256": digest(ROOT / "Cargo.lock"),
                "vector_sha256": digest(ROOT / "test-data/predicate/boolean-v1.tsv"),
                "integer_vector_sha256": digest(ROOT / "test-data/predicate/integer-refs-v1.tsv"),
                "integer_literal_vector_sha256": digest(ROOT / "test-data/predicate/integer-literal-v1.tsv"),
                "scalar_equality_vector_sha256": digest(ROOT / "test-data/predicate/scalar-equality-v1.tsv"),
                "decimal_vector_sha256": digest(ROOT / "test-data/predicate/decimal-refs-v1.tsv"),
                "decimal_literal_vector_sha256": digest(ROOT / "test-data/predicate/decimal-literal-v1.tsv"),
                "artifacts_sha256": binaries,
            },
            indent=2,
        )
        + "\n"
    )
    print("RUST_KERNEL_OFFLINE_DEBUG_RELEASE: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
