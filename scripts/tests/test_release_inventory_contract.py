"""Explicit retirement removes current discovery without rewriting archived identities."""

from __future__ import annotations

import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts import build_algorithm_sdk
from scripts.release_metadata import VersionSyncError, load_release_units, validate_inventory

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]
RETIRED = "plugin-generic-t0-cash"


@pytest.mark.parametrize("unit", ["agent", RETIRED])
def test_only_explicit_single_unit_retirements_are_accepted(unit):
    assert validate_inventory({"backend": "1.0.0", unit: "1.0.0"}, {"backend": "1.0.0"}) is False


@pytest.mark.parametrize("removed", ["backend", "libs", "frontend", "plugin-other", "plugin-generic-t0-cash-extra"])
def test_other_release_unit_removals_still_require_explicit_migration(removed):
    with pytest.raises(VersionSyncError, match="explicit inventory migration"):
        validate_inventory({"kept": "1.0.0", removed: "1.0.0"}, {"kept": "1.0.0"})


def test_retirement_does_not_allow_collateral_removal_or_addition():
    base = {"backend": "1.0.0", "frontend": "1.0.0", RETIRED: "1.0.0"}
    for candidate in ({"backend": "1.0.0"}, {"backend": "1.0.0", "frontend": "1.0.0", "plugin-other": "1.0.0"}):
        with pytest.raises(VersionSyncError, match="explicit inventory migration"):
            validate_inventory(base, candidate)
    assert validate_inventory({"backend": "1.0.0"}, {"backend": "1.0.0", "agent": "0.1.0"}) is True
    assert validate_inventory({"backend": "1.0.0"}, {"backend": "1.0.0"}) is False
    with pytest.raises(VersionSyncError, match="explicit inventory migration"):
        validate_inventory({"backend": "1.0.0"}, {"backend": "1.0.0", RETIRED: "1.0.0"})


def test_retired_market_is_absent_from_current_workspace_ci_and_wheels(tmp_path):
    distribution = "onlyalpha-" + RETIRED
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert not (ROOT / "plugs" / distribution).exists()
    assert "plugs/" + distribution not in project["tool"]["uv"]["workspace"]["members"]
    assert distribution not in {package["name"] for package in lock["package"]}
    assert RETIRED not in load_release_units(ROOT)
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert "generic-market-product" not in workflow["jobs"]
    assert distribution not in (ROOT / ".github/workflows/ci.yml").read_text()
    wheels = build_algorithm_sdk.build(tmp_path)
    assert wheels
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            assert not any(name.startswith("onlyalpha/plugin/") for name in archive.namelist())
            for name in archive.namelist():
                assert distribution.encode() not in archive.read(name)


def test_current_plugin_source_closure_and_inventory(monkeypatch):
    from scripts import release_sources
    from scripts.dev_verification import source_inputs

    units = load_release_units(ROOT)
    expected = {
        "plugin-onlyalpha-market-cn-ashare",
        "plugin-onlyalpha-market-crypto",
        "plugin-onlyalpha-data-source-binance",
        "plugin-onlyalpha-data-source-tushare",
    }
    assert release_sources.required_units(ROOT) == {"libs", *expected}
    inputs = source_inputs(ROOT)
    monkeypatch.setattr(release_sources, "source_inputs", lambda root: inputs)
    cargo_members = set(tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["members"])
    python_members = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["workspace"]["members"]
    # Literal Rust include_* inputs belong to the existing source-artifact
    # contract even when the shared reference vectors live outside the plugin.
    shared_inputs = {
        "plugin-onlyalpha-broker-binance": {
            "test-data/broker/domain-inputs.json",
            "test-data/execution/domain-inputs.json",
            "test-data/private-protocol-tls/ca.pem",
            "test-data/private-protocol-tls/server.pem",
            "test-data/private-protocol-tls/server-key.pem",
            "test-data/settlement/common-v1.json",
        },
        "plugin-onlyalpha-data-source-tushare": {
            "test-data/private-protocol-tls/ca.pem",
            "test-data/private-protocol-tls/server.pem",
            "test-data/private-protocol-tls/server-key.pem",
        },
        "plugin-onlyalpha-broker-virtual": {
            "test-data/broker/domain-inputs.json",
            "test-data/domain/fact-records-v1.jsonl",
        },
        "plugin-onlyalpha-market-cn-ashare": {
            "test-data/fee/common-v1.json",
            "test-data/reference/cn_a_share_v1/manifest.json",
            "test-data/reference/cn_a_share_v1/references.json",
        },
        "plugin-onlyalpha-market-crypto": {"test-data/domain/fact-records-v1.jsonl"},
    }
    for member in sorted(cargo_members | set(python_members)):
        if not member.startswith("plugs/"):
            continue
        rust = member in cargo_members
        manifest = "Cargo.toml" if rust else "pyproject.toml"
        package = tomllib.loads((ROOT / member / manifest).read_text())["package" if rust else "project"]
        unit = "plugin-" + package["name"].removeprefix("onlyalpha-plugin-")
        assert unit in units
        item = release_sources.inventory(ROOT, unit)
        assert member + "/" + manifest in item["files"]
        external_inputs = {name for name in item["files"] if not name.startswith(member + "/")}
        assert external_inputs == {"LICENSE", *shared_inputs.get(unit, set())}
        assert bool(item["workspace"]) == (member in cargo_members)
    with pytest.raises(ValueError, match="RELEASE_SOURCE_UNKNOWN_UNIT"):
        release_sources.inventory(ROOT, "plugin-market-crypto")


def test_tushare_isolated_build_contains_actual_dependency_and_test_inputs(tmp_path):
    from scripts.rust_kernel_check import isolated_plugin_tushare

    manifest = isolated_plugin_tushare(ROOT, tmp_path / "isolated")
    root = manifest.parent
    members = tomllib.loads(manifest.read_text())["workspace"]["members"]
    packages = {str((root / member).resolve()) for member in members}
    for member in members:
        area = root / member
        package = tomllib.loads((area / "Cargo.toml").read_text())
        for section in ("dependencies", "dev-dependencies"):
            for dependency in package.get(section, {}).values():
                if isinstance(dependency, dict) and "path" in dependency:
                    assert str((area / dependency["path"]).resolve()) in packages
    for name in (
        "plugs/onlyalpha-market-cn-ashare/src/fee_sources.json",
        "plugs/onlyalpha-data-source-tushare/tests/support/mod.rs",
        "test-data/fee/common-v1.json",
        "test-data/reference/cn_a_share_v1/references.json",
        "test-data/reference/cn_a_share_v1/manifest.json",
        "test-data/private-protocol-tls/ca.pem",
        "test-data/private-protocol-tls/server.pem",
        "test-data/private-protocol-tls/server-key.pem",
    ):
        assert (root / name).read_bytes() == (ROOT / name).read_bytes()
    assert not list((root / "plugs").rglob("*.py"))


def _plugin_workspace(root, rust, python):
    import json

    (root / "Cargo.toml").write_text(
        "[workspace]\nmembers = "
        + json.dumps(["packages/backend", *rust])
        + '\n[workspace.package]\nversion = "1.0.0"\n'
    )
    (root / "pyproject.toml").write_text("[tool.uv.workspace]\nmembers = " + json.dumps(list(python)) + "\n")
    for members, filename, section in ((rust, "Cargo.toml", "package"), (python, "pyproject.toml", "project")):
        for directory, name in members.items():
            target = root / directory
            target.mkdir(parents=True, exist_ok=True)
            (target / filename).write_text(f'[{section}]\nname = "{name}"\nversion = "1.0.0"\n')
    (root / "packages/backend").mkdir(parents=True, exist_ok=True)
    (root / "packages/backend/Cargo.toml").write_text('[package]\nname = "onlyalpha-backend"\nversion = "1.0.0"\n')
    (root / "packages/backend/python/algorithms").mkdir(parents=True)
    (root / "packages/backend/python/algorithms/pyproject.toml").write_text("[project]\ndependencies = []\n")
    (root / "packages/frontend").mkdir(parents=True, exist_ok=True)
    (root / "packages/frontend/package.json").write_text('{"version":"1.0.0"}')


def test_legacy_and_relocated_plugin_sources_use_declared_members(tmp_path):
    from scripts.release_sources import inventory

    _plugin_workspace(
        tmp_path,
        {"plugs/relocated-market": "onlyalpha-market-crypto"},
        {"plugs/onlyalpha-plugin-generic-t0-cash": "onlyalpha-plugin-generic-t0-cash"},
    )
    assert inventory(tmp_path, "plugin-onlyalpha-market-crypto")["files"].keys() == {
        "plugs/relocated-market/Cargo.toml"
    }
    historical = inventory(tmp_path, RETIRED)
    assert historical["files"].keys() == {"plugs/onlyalpha-plugin-generic-t0-cash/pyproject.toml"}
    assert historical["workspace"] == {}


@pytest.mark.parametrize(
    ("rust", "python"),
    [
        ({"plugs/one": "onlyalpha-plugin-crypto"}, {"plugs/two": "onlyalpha-plugin-crypto"}),
        ({"plugs/one": "onlyalpha-plugin-crypto"}, {"plugs/one": "onlyalpha-market-crypto"}),
        ({"plugs/one": "onlyalpha-plugin-onlyalpha-market-crypto"}, {"plugs/two": "onlyalpha-market-crypto"}),
        ({"plugs/../foreign": "onlyalpha-plugin-crypto"}, {}),
        ({"plugs/one": "foreign-crypto"}, {}),
    ],
)
def test_ambiguous_plugin_release_mapping_is_rejected(tmp_path, rust, python):
    from scripts.release_sources import inventory

    _plugin_workspace(tmp_path, rust, python)
    with pytest.raises(VersionSyncError, match="cannot establish exact release-unit metadata"):
        load_release_units(tmp_path)
    with pytest.raises(VersionSyncError):
        inventory(tmp_path, "plugin-crypto")


def test_same_directory_rust_python_plugin_is_one_release_unit(tmp_path):
    from scripts.release_sources import inventory

    members = {"plugs/shared": "onlyalpha-plugin-crypto"}
    _plugin_workspace(tmp_path, members, members)
    units = load_release_units(tmp_path)
    assert set(units) == {"libs", "backend", "frontend", "plugin-crypto"}
    item = inventory(tmp_path, "plugin-crypto")
    assert set(item["files"]) == {"plugs/shared/Cargo.toml", "plugs/shared/pyproject.toml"}
    assert item["workspace"]


@pytest.mark.parametrize("member", ["", ".", "/plugs/foreign", "plugs/../foreign"])
def test_invalid_plugin_workspace_path_is_rejected(tmp_path, member):
    import json

    from scripts.release_metadata import plugin_release_members

    _plugin_workspace(tmp_path, {}, {})
    (tmp_path / "Cargo.toml").write_text(
        "[workspace]\nmembers = " + json.dumps([member]) + '\n[workspace.package]\nversion = "1.0.0"\n'
    )
    with pytest.raises(VersionSyncError, match="invalid plugin workspace path"):
        plugin_release_members(tmp_path)
    with pytest.raises(VersionSyncError, match="cannot establish exact release-unit metadata"):
        load_release_units(tmp_path)


@pytest.mark.parametrize("name", ["onlyalpha-plugin-generic-t0-cash", "onlyalpha-data-source-tushare"])
def test_python_executor_plugin_requirement_uses_same_release_unit(tmp_path, name):
    from scripts.release_metadata import plugin_release_unit
    from scripts.release_sources import required_units

    _plugin_workspace(tmp_path, {}, {"plugs/python-distribution": name})
    (tmp_path / "packages/backend/python/algorithms/pyproject.toml").write_text(
        f'[project]\ndependencies = ["{name}==1.0.0"]\n'
    )
    assert required_units(tmp_path) == {"libs", plugin_release_unit(name)}


@pytest.mark.parametrize(
    ("requirement", "error"),
    [
        ("onlyalpha-market-missing==1.0.0", "RELEASE_SOURCE_DEPENDENCY_UNKNOWN"),
        ("onlyalpha-plugin-missing==1.0.0", "RELEASE_SOURCE_DEPENDENCY_UNKNOWN"),
        ("onlyalpha-market-crypto>=1.0.0", "RELEASE_SOURCE_DEPENDENCY_UNPINNED"),
    ],
)
def test_python_executor_unknown_or_unpinned_plugin_is_rejected(tmp_path, requirement, error):
    from scripts.release_sources import required_units

    _plugin_workspace(tmp_path, {}, {})
    (tmp_path / "packages/backend/python/algorithms/pyproject.toml").write_text(
        f'[project]\ndependencies = ["{requirement}"]\n'
    )
    with pytest.raises(ValueError, match=error):
        required_units(tmp_path)


def test_virtual_isolated_build_contains_only_its_actual_rust_dependency_closure(tmp_path):
    from scripts.rust_kernel_check import isolated_plugin_virtual

    manifest = isolated_plugin_virtual(ROOT, tmp_path / "isolated")
    root = manifest.parent
    members = set(tomllib.loads(manifest.read_text())["workspace"]["members"])
    assert members == {"crates/domain", "crates/broker", "plugs/onlyalpha-broker-virtual"}
    packages = {(root / member).resolve() for member in members}
    for member in members:
        area = root / member
        package = tomllib.loads((area / "Cargo.toml").read_text())
        for section in ("dependencies", "dev-dependencies"):
            for dependency in package.get(section, {}).values():
                if isinstance(dependency, dict) and "path" in dependency:
                    assert (area / dependency["path"]).resolve() in packages
    for name in (ROOT / "plugs/onlyalpha-broker-virtual/src").rglob("*.rs"):
        assert (root / name.relative_to(ROOT)).read_bytes() == name.read_bytes()
    for name in ("test-data/broker/domain-inputs.json", "test-data/domain/fact-records-v1.jsonl"):
        assert (root / name).read_bytes() == (ROOT / name).read_bytes()
    assert not list((root / "plugs").rglob("*.py"))


def test_binance_broker_isolated_build_contains_its_exact_native_dependency_closure(tmp_path):
    from scripts.rust_kernel_check import isolated_broker_binance

    manifest = isolated_broker_binance(ROOT, tmp_path / "isolated")
    root = manifest.parent
    members = set(tomllib.loads(manifest.read_text())["workspace"]["members"])
    assert members == {
        "crates/domain",
        "crates/broker",
        "crates/metadata-json",
        "crates/market-data-construction",
        "crates/integration-contract",
        "plugs/onlyalpha-broker-binance",
        "crates/order",
        "crates/position",
        "crates/account",
        "crates/strategy-ledger",
        "crates/risk",
        "crates/fee",
        "crates/settlement",
        "crates/margin",
        "crates/execution",
        "crates/runtime",
        "plugs/onlyalpha-broker-virtual",
    }
    broker = tomllib.loads((root / "plugs/onlyalpha-broker-binance/Cargo.toml").read_text())
    assert {"onlyalpha-execution", "onlyalpha-runtime"}.isdisjoint(broker["dependencies"])
    assert broker["dev-dependencies"] == {
        "onlyalpha-execution": {"path": "../../crates/execution"},
        "onlyalpha-runtime": {"path": "../../crates/runtime"},
    }
    packages = {(root / member).resolve() for member in members}
    for member in members:
        package = tomllib.loads((root / member / "Cargo.toml").read_text())
        for section in ("dependencies", "dev-dependencies"):
            for dependency in package.get(section, {}).values():
                if isinstance(dependency, dict) and "path" in dependency:
                    assert (root / member / dependency["path"]).resolve() in packages
    for name in (ROOT / "plugs/onlyalpha-broker-binance/src").rglob("*.rs"):
        assert (root / name.relative_to(ROOT)).read_bytes() == name.read_bytes()
    for name in ("ca.pem", "server.pem", "server-key.pem"):
        relative = Path("test-data/private-protocol-tls") / name
        assert (root / relative).read_bytes() == (ROOT / relative).read_bytes()
    assert not list((root / "plugs").rglob("*.py"))


@pytest.mark.parametrize("plugin", ["crypto", "binance"])
def test_reference_isolated_build_carries_exact_registered_local_fixtures(tmp_path, plugin):
    from scripts.rust_kernel_check import isolated_market_crypto, isolated_plugin_binance

    materialize = isolated_market_crypto if plugin == "crypto" else isolated_plugin_binance
    manifest = materialize(ROOT, tmp_path / plugin)
    root = manifest.parent
    member = "plugs/onlyalpha-market-crypto" if plugin == "crypto" else "plugs/onlyalpha-data-source-binance"
    expected = (
        ("spot-resource.json", "usdm-public-resource.json", "usdm-account-resource.json")
        if plugin == "crypto"
        else (
            "spot-exchange.json",
            "spot-execution.json",
            "usdm-exchange.json",
            "usdm-funding.json",
            "usdm-brackets.json",
            "usdm-account.json",
        )
    )
    for name in expected:
        relative = Path(member) / "tests/fixtures" / name
        assert (root / relative).read_bytes() == (ROOT / relative).read_bytes()
    packages = tomllib.loads((root / "Cargo.toml").read_text())["workspace"]["members"]
    assert len(packages) == (4 if plugin == "crypto" else 18)
    for selected in packages:
        if selected.startswith("plugs/"):
            assert not list((root / selected).rglob("*.py"))


@pytest.mark.parametrize("mutation", ["duplicate_execution_dev", "provider_dev_edge"])
def test_assembled_dependency_admission_keeps_exact_scope_and_kind(monkeypatch, mutation):
    from scripts.rust_kernel_check import validate_workspace

    original = Path.read_text
    selected = ROOT / (
        "crates/execution/Cargo.toml"
        if mutation == "duplicate_execution_dev"
        else "plugs/onlyalpha-data-source-binance/Cargo.toml"
    )

    def read(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path == selected:
            if mutation == "duplicate_execution_dev":
                return text + '\n[dev-dependencies]\nonlyalpha-broker = { path = "../broker" }\n'
            return text + '\nonlyalpha-broker-binance = { path = "../onlyalpha-broker-binance" }\n'
        return text

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_workspace(ROOT)


@pytest.mark.parametrize("mutation", ["production_execution", "provider_test_edge", "wrong_test_path"])
def test_broker_cash_consumer_cannot_expand_production_or_unrelated_test_dependencies(monkeypatch, mutation):
    from scripts.rust_kernel_check import validate_workspace

    original = Path.read_text
    owner = ROOT / "plugs/onlyalpha-broker-binance/Cargo.toml"

    def read(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path != owner:
            return text
        if mutation == "production_execution":
            return text.replace(
                "\n[dev-dependencies]\n",
                '\nonlyalpha-execution = { path = "../../crates/execution" }\n\n[dev-dependencies]\n',
            )
        if mutation == "provider_test_edge":
            return text + '\nonlyalpha-data-source-binance = { path = "../onlyalpha-data-source-binance" }\n'
        return text.replace('path = "../../crates/execution"', 'path = "../../crates/domain"')

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_workspace(ROOT)


def test_isolated_ledger_contains_the_actual_position_producer_dependency(tmp_path):
    from scripts.rust_kernel_check import isolated_strategy_ledger

    manifest = isolated_strategy_ledger(ROOT, tmp_path / "ledger")
    root = manifest.parent
    members = tomllib.loads(manifest.read_text())["workspace"]["members"]
    assert set(members) == {"crates/domain", "crates/position", "crates/strategy-ledger"}
    packages = {(root / member).resolve() for member in members}
    for member in members:
        package = tomllib.loads((root / member / "Cargo.toml").read_text())
        for kind in ("dependencies", "dev-dependencies"):
            for dependency in package.get(kind, {}).values():
                if isinstance(dependency, dict) and "path" in dependency:
                    assert (root / member / dependency["path"]).resolve() in packages
    reference = "test-data/position/lifecycle-v1.jsonl"
    assert (root / reference).read_bytes() == (ROOT / reference).read_bytes()
