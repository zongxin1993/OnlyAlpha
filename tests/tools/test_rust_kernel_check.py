from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from scripts.rust_kernel_check import build_commands, compiler_environment, module_path


def test_rust_commands_cover_locked_offline_profiles_without_parallel_tests() -> None:
    commands = build_commands("aarch64-unknown-linux-gnu")
    assert any(command[:2] == ["cargo", "fmt"] for command in commands)
    assert any(command[:2] == ["cargo", "clippy"] and command[-2:] == ["-D", "warnings"] for command in commands)
    for action in ("test", "build"):
        selected = [command for command in commands if command[1] == action]
        assert len(selected) == 2
        assert sum("--release" in command for command in selected) == 1
        assert all("--frozen" in command and "--offline" in command and "-j1" in command for command in selected)
        if action == "test":
            assert all("--test-threads=1" in command for command in selected)


def test_compiler_environment_removes_ambient_flags_and_wrappers(tmp_path: Path) -> None:
    env = compiler_environment(
        {
            "PATH": "/tools",
            "RUSTUP_HOME": "/official",
            "RUSTFLAGS": "-C overflow-checks=no",
            "RUSTC_WRAPPER": "/untrusted",
            "CARGO_PROFILE_RELEASE_PANIC": "abort",
        },
        tmp_path,
    )
    assert env["PATH"] == "/tools" and env["RUSTUP_HOME"] == "/official"
    assert "RUSTFLAGS" not in env and "RUSTC_WRAPPER" not in env
    assert "CARGO_PROFILE_RELEASE_PANIC" not in env
    assert env["CARGO_NET_OFFLINE"] == "true"
    assert env["RUSTUP_AUTO_INSTALL"] == "0"
    assert env["CARGO_TARGET_DIR"] == str(tmp_path)


def test_rejected_host_cannot_leave_a_prior_build_receipt(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    import pytest

    import scripts.rust_kernel_check as check

    receipt = tmp_path / "test-results/rust-kernel/last-run.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"prior":"build"}')
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr("sys.platform", "darwin")
    with pytest.raises(ValueError, match="LINUX_REQUIRED"):
        check.main()
    assert not receipt.exists()


def test_domain_workspace_rejects_reverse_dependencies_and_external_package_aliases(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_workspace

    (tmp_path / "Cargo.toml").write_text(
        '[workspace]\nmembers=["packages/onlyalpha-gateway-protocol","packages/onlyalpha-calculation-worker","crates/onlyalpha-kernel/domain","crates/onlyalpha-kernel/core","crates/onlyalpha-kernel/clock","crates/onlyalpha-kernel/event","crates/onlyalpha-kernel/market_data/state","crates/onlyalpha-kernel/market_data/construction","crates/onlyalpha-kernel/market_data/delivery","crates/onlyalpha-kernel/market_data/pipeline","crates/onlyalpha-kernel/calculation","crates/onlyalpha-kernel/strategy","crates/onlyalpha-kernel/order"]\n'
    )
    (tmp_path / "Cargo.lock").write_text(
        'version=4\n[[package]]\nname="onlyalpha-domain"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-kernel"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-clock"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-event"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-market-data-state"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-market-data-construction"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-market-data-delivery"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-market-data-pipeline"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-order"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-strategy"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-calculation"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-gateway-protocol"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-calculation-worker"\nversion="0.10.7"\n'
    )
    for name in (
        "domain",
        "core",
        "clock",
        "event",
        "market_data_state",
        "market_data_construction",
        "market_data_delivery",
        "market_data_pipeline",
        "order",
        "strategy",
        "calculation",
        "gateway_protocol",
        "calculation_worker",
    ):
        path = tmp_path / module_path(name) / "Cargo.toml"
        path.parent.mkdir(parents=True)
        package = "kernel" if name == "core" else name.replace("_", "-")
        path.write_text(f'[package]\nname="onlyalpha-{package}"\n')
    validate_workspace(tmp_path)
    manifest = tmp_path / "crates/onlyalpha-kernel/domain/Cargo.toml"
    original = manifest.read_text()
    for dependency in (
        'onlyalpha-kernel = { path = "../onlyalpha-kernel" }',
        'onlyalpha-clock = { path = "../clock" }',
        'onlyalpha-event = { path = "../event" }',
        'alias = { package = "onlyalpha-kernel", path = "../onlyalpha-kernel" }',
        'serde = "1"',
    ):
        manifest.write_text(original + "\n[dependencies]\n" + dependency + "\n")
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_workspace(tmp_path)
    manifest.write_text(original)
    (tmp_path / "Cargo.lock").write_text(
        (tmp_path / "Cargo.lock").read_text() + '\n[[package]]\nname="unreviewed"\nversion="1"\n'
    )
    with pytest.raises(ValueError, match="DEPENDENCY_REVIEW"):
        validate_workspace(tmp_path)


def test_domain_registry_admission_binds_exact_lock_graph_and_features(tmp_path: Path) -> None:
    import shutil

    import pytest

    from scripts.rust_kernel_check import ROOT, validate_workspace

    for name in (
        "Cargo.toml",
        "Cargo.lock",
        "crates/onlyalpha-kernel/domain/Cargo.toml",
        "crates/onlyalpha-kernel/core/Cargo.toml",
        "crates/onlyalpha-kernel/clock/Cargo.toml",
        "crates/onlyalpha-kernel/event/Cargo.toml",
        "crates/onlyalpha-kernel/market_data/state/Cargo.toml",
        "crates/onlyalpha-kernel/market_data/construction/Cargo.toml",
        "crates/onlyalpha-kernel/market_data/delivery/Cargo.toml",
        "crates/onlyalpha-kernel/market_data/pipeline/Cargo.toml",
        "crates/onlyalpha-kernel/strategy/Cargo.toml",
        "crates/onlyalpha-kernel/order/Cargo.toml",
        "crates/onlyalpha-kernel/calculation/Cargo.toml",
        "packages/onlyalpha-gateway-protocol/Cargo.toml",
        "packages/onlyalpha-calculation-worker/Cargo.toml",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    validate_workspace(tmp_path)
    lock = tmp_path / "Cargo.lock"
    original = lock.read_text()
    lock.write_text(original.replace('name = "memchr"', 'name = "unreviewed"'))
    with pytest.raises(ValueError, match="DEPENDENCY_REVIEW"):
        validate_workspace(tmp_path)
    lock.write_text(original)
    event = tmp_path / "crates/onlyalpha-kernel/event/Cargo.toml"
    original_event = event.read_text()
    for altered in (
        original_event.replace('path = "../domain"', 'path = "../clock"'),
        original_event.replace("onlyalpha-domain =", "alias ="),
        original_event.replace("default-features = false", "default-features = true"),
        original_event + '\n[dev-dependencies]\nonlyalpha-clock = { path = "../clock" }\n',
    ):
        event.write_text(altered)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_workspace(tmp_path)
    event.write_text(original_event)
    domain = tmp_path / "crates/onlyalpha-kernel/domain/Cargo.toml"
    domain.write_text(
        domain.read_text().replace('"std", "arbitrary_precision"', '"std", "arbitrary_precision", "unbounded_depth"')
    )
    with pytest.raises(ValueError, match="BOUNDARY"):
        validate_workspace(tmp_path)


def test_offline_cargo_home_cannot_reuse_mutated_source_or_config(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import prepare_cargo_home

    registry = tmp_path / "image-registry"
    registry.mkdir()
    (registry / "trusted").write_text("locked bytes")
    home = tmp_path / "cargo-home"
    home.mkdir()
    (home / "config.toml").write_text("untrusted source replacement")
    prepare_cargo_home(registry, home)
    assert not (home / "config.toml").exists()
    assert (home / "registry/trusted").read_text() == "locked bytes"
    (home / "registry/trusted").write_text("mutated bytes")
    prepare_cargo_home(registry, home)
    assert (home / "registry/trusted").read_text() == "locked bytes"
    link = tmp_path / "outside"
    link.symlink_to(home, target_is_directory=True)
    with pytest.raises(ValueError, match="CARGO_HOME"):
        prepare_cargo_home(registry, link)


def test_domain_source_boundary_rejects_hidden_include_and_build_escapes(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_domain_sources

    source = tmp_path / "crates/onlyalpha-kernel/domain/src/lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text("pub struct Domain;\n")
    validate_domain_sources(tmp_path)
    for escape in (
        'include!("/workspace/crates/onlyalpha-kernel/core/src/lib.rs");',
        '#[path="../../onlyalpha-kernel/src/lib.rs"] mod kernel;',
        '#[cfg_attr(all(), path="../../core/src/lib.rs")] mod hidden;',
        'const INPUT: &str = env!("UNDECLARED_DOMAIN_INPUT");',
    ):
        source.write_text(escape)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_domain_sources(tmp_path)
    source.write_text("pub struct Domain;\n")
    (source.parent.parent / "build.rs").write_text("fn main() {}")
    with pytest.raises(ValueError, match="BOUNDARY"):
        validate_domain_sources(tmp_path)


def test_domain_manifest_cannot_redirect_its_library_or_build_script(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_domain_sources

    domain = tmp_path / "crates/onlyalpha-kernel/domain"
    (domain / "src").mkdir(parents=True)
    (domain / "src/lib.rs").write_text("pub struct Domain;\n")
    manifest = domain / "Cargo.toml"
    for content in ('[package]\nbuild="../../escape.rs"\n', '[lib]\npath="../onlyalpha-kernel/src/lib.rs"\n'):
        manifest.write_text(content)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_domain_sources(tmp_path)


def test_kernel_umbrella_groups_independently_buildable_modules() -> None:
    import tomllib

    from scripts.rust_kernel_check import ROOT

    members = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["members"]
    expected = {
        "domain": "onlyalpha-domain",
        "core": "onlyalpha-kernel",
        "clock": "onlyalpha-clock",
        "event": "onlyalpha-event",
        "market_data_state": "onlyalpha-market-data-state",
        "market_data_construction": "onlyalpha-market-data-construction",
        "market_data_delivery": "onlyalpha-market-data-delivery",
        "market_data_pipeline": "onlyalpha-market-data-pipeline",
        "strategy": "onlyalpha-strategy",
        "order": "onlyalpha-order",
        "calculation": "onlyalpha-calculation",
        "gateway_protocol": "onlyalpha-gateway-protocol",
        "calculation_worker": "onlyalpha-calculation-worker",
    }
    assert set(members) == {str(module_path(area)) for area in expected}
    for area, name in expected.items():
        manifest = ROOT / module_path(area) / "Cargo.toml"
        assert tomllib.loads(manifest.read_text())["package"]["name"] == name
    assert not (ROOT / "crates/onlyalpha-kernel/Cargo.toml").exists()
    assert not (ROOT / "crates/onlyalpha-domain").exists()
