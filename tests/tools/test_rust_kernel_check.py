from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch, mark

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
        check.main([])
    assert not receipt.exists()


def test_domain_workspace_rejects_reverse_dependencies_and_external_package_aliases(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_workspace

    (tmp_path / "Cargo.toml").write_text(
        '[workspace]\nmembers=["plugs/onlyalpha-plugin-binance","plugs/onlyalpha-plugin-tushare","crates/onlyalpha-metadata-json","crates/onlyalpha-integration-contract","packages/backend","crates/onlyalpha-backtest","crates/onlyalpha-runtime-persistence","crates/onlyalpha-gateway-protocol","crates/onlyalpha-calculation-bridge","crates/onlyalpha-kernel/domain","crates/onlyalpha-kernel/predicates","crates/onlyalpha-kernel/clock","crates/onlyalpha-kernel/event","crates/onlyalpha-kernel/market_data/state","crates/onlyalpha-kernel/market_data/construction","crates/onlyalpha-kernel/market_data/delivery","crates/onlyalpha-kernel/market_data/pipeline","crates/onlyalpha-kernel/calculation","crates/onlyalpha-kernel/strategy","crates/onlyalpha-kernel/order","crates/onlyalpha-kernel/position","crates/onlyalpha-kernel/account","crates/onlyalpha-kernel/strategy_ledger","crates/onlyalpha-kernel/risk","crates/onlyalpha-kernel/execution","crates/onlyalpha-kernel/broker","crates/onlyalpha-kernel/fee","crates/onlyalpha-kernel/settlement","crates/onlyalpha-kernel/margin"]\n'
    )
    (tmp_path / "Cargo.lock").write_text(
        'version=4\n[[package]]\nname="onlyalpha-plugin-binance"\nversion="0.10.21"\n[[package]]\nname="onlyalpha-plugin-tushare"\nversion="0.10.21"\n[[package]]\nname="onlyalpha-metadata-json"\nversion="0.10.21"\n[[package]]\nname="onlyalpha-integration-contract"\nversion="0.10.21"\n[[package]]\nname="onlyalpha-backend"\nversion="0.10.21"\n[[package]]\nname="onlyalpha-backtest"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-runtime-persistence"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-domain"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-predicates"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-clock"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-event"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-market-data-state"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-market-data-construction"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-market-data-delivery"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-market-data-pipeline"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-execution"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-broker"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-fee"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-settlement"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-margin"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-risk"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-strategy-ledger"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-account"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-position"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-order"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-strategy"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-calculation"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-gateway-protocol"\nversion="0.10.7"\n[[package]]\nname="onlyalpha-calculation-bridge"\nversion="0.10.7"\n'
    )
    for name in (
        "domain",
        "predicates",
        "clock",
        "event",
        "market_data_state",
        "market_data_construction",
        "market_data_delivery",
        "market_data_pipeline",
        "order",
        "position",
        "account",
        "strategy_ledger",
        "risk",
        "execution",
        "broker",
        "fee",
        "settlement",
        "margin",
        "strategy",
        "calculation",
        "gateway_protocol",
        "calculation_bridge",
        "runtime_persistence",
        "backtest",
        "backend",
        "metadata_json",
        "integration_contract",
        "plugin_binance",
        "plugin_tushare",
    ):
        path = tmp_path / module_path(name) / "Cargo.toml"
        path.parent.mkdir(parents=True)
        package = name.replace("_", "-")
        path.write_text(f'[package]\nname="onlyalpha-{package}"\n')
    validate_workspace(tmp_path)
    manifest = tmp_path / "crates/onlyalpha-kernel/domain/Cargo.toml"
    original = manifest.read_text()
    for dependency in (
        'onlyalpha-kernel = { path = "../onlyalpha-kernel" }',
        'onlyalpha-clock = { path = "../clock" }',
        'onlyalpha-event = { path = "../event" }',
        'alias = { package = "onlyalpha-predicates", path = "../onlyalpha-kernel" }',
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
        "crates/onlyalpha-kernel/predicates/Cargo.toml",
        "crates/onlyalpha-kernel/clock/Cargo.toml",
        "crates/onlyalpha-kernel/event/Cargo.toml",
        "crates/onlyalpha-kernel/market_data/state/Cargo.toml",
        "crates/onlyalpha-kernel/market_data/construction/Cargo.toml",
        "crates/onlyalpha-kernel/market_data/delivery/Cargo.toml",
        "crates/onlyalpha-kernel/market_data/pipeline/Cargo.toml",
        "crates/onlyalpha-kernel/strategy/Cargo.toml",
        "crates/onlyalpha-kernel/order/Cargo.toml",
        "crates/onlyalpha-kernel/position/Cargo.toml",
        "crates/onlyalpha-kernel/account/Cargo.toml",
        "crates/onlyalpha-kernel/strategy_ledger/Cargo.toml",
        "crates/onlyalpha-kernel/risk/Cargo.toml",
        "crates/onlyalpha-kernel/execution/Cargo.toml",
        "crates/onlyalpha-kernel/broker/Cargo.toml",
        "crates/onlyalpha-kernel/fee/Cargo.toml",
        "crates/onlyalpha-kernel/settlement/Cargo.toml",
        "crates/onlyalpha-kernel/margin/Cargo.toml",
        "crates/onlyalpha-kernel/calculation/Cargo.toml",
        "crates/onlyalpha-gateway-protocol/Cargo.toml",
        "crates/onlyalpha-calculation-bridge/Cargo.toml",
        "crates/onlyalpha-runtime-persistence/Cargo.toml",
        "crates/onlyalpha-backtest/Cargo.toml",
        "packages/backend/Cargo.toml",
        "packages/backend/Cargo.toml",
        "crates/onlyalpha-metadata-json/Cargo.toml",
        "crates/onlyalpha-integration-contract/Cargo.toml",
        "plugs/onlyalpha-plugin-binance/Cargo.toml",
        "plugs/onlyalpha-plugin-tushare/Cargo.toml",
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
    product = tmp_path / "packages/backend/Cargo.toml"
    original_product = product.read_text()
    for altered in (
        original_product.replace('features = ["runtime"]', 'features = ["runtime", "with-uuid-1"]'),
        original_product.replace(
            'features = ["io-util", "macros", "net", "rt", "signal", "sync", "time"]', 'features = ["full"]'
        ),
        original_product.replace(
            'features = ["io-util", "macros", "net", "rt", "signal", "sync", "time"]', 'features = ["rt-multi-thread"]'
        ),
        original_product.replace("tokio-postgres =", "alias ="),
        original_product.replace(
            'features = ["aes", "alloc", "zeroize"]', 'features = ["aes", "alloc", "zeroize", "hazmat"]'
        ),
        original_product.replace('features = ["aes", "alloc", "zeroize"]', 'features = ["aes", "alloc"]'),
        original_product.replace(
            'hkdf = { version = "=0.13.0", default-features = false }',
            'hkdf = { version = "=0.13.0", default-features = false, features = ["kdf"] }',
        ),
        original_product.replace(
            'features = ["arbitrary_precision", "raw_value", "std"]',
            'features = ["std", "arbitrary_precision", "raw_value", "preserve_order"]',
        ),
        original_product.replace('features = ["arbitrary_precision", "raw_value", "std"]', 'features = ["std"]'),
        original_product.replace('serde = { version = "=1.0.229"', 'serde = { version = "1.0"'),
        original_product.replace('version = "=0.7.18"', 'version = "0.7"'),
        original_product.replace(
            'subtle = { version = "=2.6.1", default-features = false }',
            'subtle = { version = "=2.6.1", default-features = false, features = ["std"] }',
        ),
        original_product + '\n[build-dependencies]\nserde_json = "1"\n',
        original_product + "\n[target.'cfg(unix)'.dependencies]\ntokio = \"1\"\n",
    ):
        assert altered != original_product, "negative dependency case must mutate the actual manifest"
        product.write_text(altered)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_workspace(tmp_path)
    product.write_text(original_product)
    http = tmp_path / "packages/backend/Cargo.toml"
    original_http = http.read_text()
    for altered in (
        original_http.replace('features = ["fs", "process", "std"]', 'features = ["all-apis"]'),
        original_http.replace('version = "=1.5.0"', 'version = "1"'),
        original_http.replace(
            '"arbitrary_precision", "raw_value"', '"arbitrary_precision", "raw_value", "unbounded_depth"'
        ),
        original_http.replace("onlyalpha-plugin-binance =", "alias ="),
        original_http + '\n[build-dependencies]\nhttp = "1"\n',
        original_http + "\n[target.'cfg(unix)'.dependencies]\nhttp = \"1\"\n",
    ):
        assert altered != original_http, "negative dependency case must mutate the actual manifest"
        http.write_text(altered)
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_workspace(tmp_path)
    http.write_text(original_http)
    original_domain = (tmp_path / "crates/onlyalpha-kernel/domain/Cargo.toml").read_text()
    for dependency in (
        'onlyalpha-backend = { path = "../../../packages/backend" }',
        'tokio-postgres = { version = "=0.7.18", default-features = false, features = ["runtime"] }',
    ):
        path = tmp_path / "crates/onlyalpha-kernel/domain/Cargo.toml"
        path.write_text(original_domain + "\n" + dependency + "\n")
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_workspace(tmp_path)
    (tmp_path / "crates/onlyalpha-kernel/domain/Cargo.toml").write_text(original_domain)
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
        'include!("/workspace/crates/onlyalpha-kernel/predicates/src/lib.rs");',
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
        "predicates": "onlyalpha-predicates",
        "clock": "onlyalpha-clock",
        "event": "onlyalpha-event",
        "market_data_state": "onlyalpha-market-data-state",
        "market_data_construction": "onlyalpha-market-data-construction",
        "market_data_delivery": "onlyalpha-market-data-delivery",
        "market_data_pipeline": "onlyalpha-market-data-pipeline",
        "strategy": "onlyalpha-strategy",
        "order": "onlyalpha-order",
        "position": "onlyalpha-position",
        "account": "onlyalpha-account",
        "strategy_ledger": "onlyalpha-strategy-ledger",
        "risk": "onlyalpha-risk",
        "execution": "onlyalpha-execution",
        "broker": "onlyalpha-broker",
        "fee": "onlyalpha-fee",
        "settlement": "onlyalpha-settlement",
        "margin": "onlyalpha-margin",
        "calculation": "onlyalpha-calculation",
        "gateway_protocol": "onlyalpha-gateway-protocol",
        "calculation_bridge": "onlyalpha-calculation-bridge",
        "runtime_persistence": "onlyalpha-runtime-persistence",
        "backtest": "onlyalpha-backtest",
        "backend": "onlyalpha-backend",
        "metadata_json": "onlyalpha-metadata-json",
        "integration_contract": "onlyalpha-integration-contract",
        "plugin_binance": "onlyalpha-plugin-binance",
        "plugin_tushare": "onlyalpha-plugin-tushare",
    }
    assert set(members) == {str(module_path(area)) for area in expected}
    for area, name in expected.items():
        manifest = ROOT / module_path(area) / "Cargo.toml"
        assert tomllib.loads(manifest.read_text())["package"]["name"] == name
    assert not (ROOT / "crates/onlyalpha-kernel/Cargo.toml").exists()
    assert not (ROOT / "crates/onlyalpha-domain").exists()


def test_account_position_producer_edge_is_exact_and_cannot_admit_alias_or_reverse_edge(tmp_path: Path) -> None:
    import shutil
    import tomllib

    import pytest

    from scripts.rust_kernel_check import ROOT, validate_workspace

    for name in ("Cargo.toml", "Cargo.lock"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    members = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["members"]
    for member in members:
        destination = tmp_path / member / "Cargo.toml"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / member / "Cargo.toml", destination)
    validate_workspace(tmp_path)
    manifest = tmp_path / "crates/onlyalpha-kernel/account/Cargo.toml"
    original = manifest.read_text()
    for invalid in (
        'position-alias = { package = "onlyalpha-position", path = "../position" }',
        'onlyalpha-position = { path = "../strategy_ledger" }',
        'onlyalpha-strategy-ledger = { path = "../strategy_ledger" }',
    ):
        manifest.write_text(original.replace('onlyalpha-position = { path = "../position" }', invalid))
        with pytest.raises(ValueError, match="BOUNDARY"):
            validate_workspace(tmp_path)
    manifest.write_text(original)
    position = tmp_path / "crates/onlyalpha-kernel/position/Cargo.toml"
    position.write_text(position.read_text() + '\nonlyalpha-account = { path = "../account" }\n')
    with pytest.raises(ValueError, match="BOUNDARY"):
        validate_workspace(tmp_path)


def test_native_sqlite_build_cannot_select_system_library_or_hidden_c_flags(tmp_path: Path) -> None:
    overrides = {
        "LIBSQLITE3_SYS_USE_PKG_CONFIG": "1",
        "LIBSQLITE3_FLAGS": "-DSQLITE_OMIT_FSYNC",
        "SQLITE_MAX_COLUMN": "1",
        "CFLAGS_aarch64_unknown_linux_gnu": "-DSQLITE_OMIT_FSYNC",
        "GCC_EXEC_PREFIX": "/untrusted/",
        "COMPILER_PATH": "/untrusted",
        "LD_PRELOAD": "/untrusted/inject.so",
        "LD_LIBRARY_PATH": "/untrusted",
        "LD_AUDIT": "/untrusted/audit.so",
        "HOST_CC": "/untrusted",
        "CRATE_CC_NO_DEFAULTS": "1",
        "PKG_CONFIG_PATH": "/untrusted",
        "AARCH64_UNKNOWN_LINUX_GNU_SQLITE3_LIB_DIR": "/untrusted",
        "CPATH": "/untrusted",
        "CC": "/untrusted",
        "AR": "/untrusted",
    }
    env = compiler_environment(overrides, tmp_path)
    assert set(overrides) & set(env) == {"CC", "AR"}
    assert env["CC"] == "/usr/bin/gcc" and env["AR"] == "/usr/bin/ar"


def _infrastructure_source_tree(tmp_path: Path) -> None:
    for module in (
        "gateway_protocol",
        "calculation_bridge",
        "runtime_persistence",
        "backtest",
        "metadata_json",
        "integration_contract",
        "backend",
        "plugin_binance",
        "plugin_tushare",
    ):
        area = tmp_path / module_path(module)
        source = "src" if module == "backend" else "rust"
        (area / source).mkdir(parents=True)
        (area / "Cargo.toml").write_text(
            f'[package]\nname="onlyalpha-{module.replace("_", "-")}"\nbuild=false\n[lib]\npath="{source}/lib.rs"\n'
        )
        (area / source / "lib.rs").write_text("")
        if module == "backend":
            (area / source / "bootstrap").mkdir()


def test_native_application_descriptor_uses_only_declared_cargo_version(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_infrastructure_sources

    _infrastructure_source_tree(tmp_path)
    main = tmp_path / "packages/backend/examples/native_backtest_reference.rs"
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_text('const VERSION: &str = env!("CARGO_PKG_VERSION");')
    validate_infrastructure_sources(tmp_path)
    for text in ('const INPUT: &str = env!("UNDECLARED_INPUT");', 'const INPUT: &str = include_str!("extra.txt");'):
        main.write_text(text)
        with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
            validate_infrastructure_sources(tmp_path)
    main.write_text("")
    (main.parent / "lib.rs").write_text('const VERSION: &str = env!("CARGO_PKG_VERSION");')
    with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
        validate_infrastructure_sources(tmp_path)


def test_product_application_isolation_has_only_domain_and_its_declared_registry_closure(tmp_path: Path) -> None:
    import tomllib

    from scripts.rust_kernel_check import ROOT, isolated_backend

    manifest = isolated_backend(ROOT, tmp_path / "product")
    workspace = tomllib.loads(manifest.read_text())["workspace"]
    assert set(workspace["members"]) == {
        "crates/onlyalpha-kernel/domain",
        "crates/onlyalpha-kernel/calculation",
        "crates/onlyalpha-kernel/market_data/construction",
        "crates/onlyalpha-kernel/strategy",
        "crates/onlyalpha-kernel/event",
        "crates/onlyalpha-kernel/market_data/state",
        "crates/onlyalpha-kernel/market_data/delivery",
        "crates/onlyalpha-kernel/market_data/pipeline",
        "crates/onlyalpha-gateway-protocol",
        "crates/onlyalpha-calculation-bridge",
        "packages/backend",
        "crates/onlyalpha-backtest",
        "crates/onlyalpha-runtime-persistence",
        "crates/onlyalpha-kernel/execution",
        "crates/onlyalpha-kernel/clock",
        "crates/onlyalpha-kernel/order",
        "crates/onlyalpha-kernel/position",
        "crates/onlyalpha-kernel/account",
        "crates/onlyalpha-kernel/strategy_ledger",
        "crates/onlyalpha-kernel/risk",
        "crates/onlyalpha-kernel/broker",
        "crates/onlyalpha-kernel/fee",
        "crates/onlyalpha-kernel/settlement",
        "crates/onlyalpha-kernel/margin",
        "plugs/onlyalpha-plugin-binance",
        "plugs/onlyalpha-plugin-tushare",
        "crates/onlyalpha-metadata-json",
        "crates/onlyalpha-integration-contract",
    }
    packages = tomllib.loads(manifest.with_name("Cargo.lock").read_text())["package"]
    assert {package["name"] for package in packages if "source" not in package} == {
        "onlyalpha-domain",
        "onlyalpha-calculation",
        "onlyalpha-market-data-construction",
        "onlyalpha-strategy",
        "onlyalpha-event",
        "onlyalpha-market-data-state",
        "onlyalpha-market-data-delivery",
        "onlyalpha-market-data-pipeline",
        "onlyalpha-gateway-protocol",
        "onlyalpha-calculation-bridge",
        "onlyalpha-metadata-json",
        "onlyalpha-integration-contract",
        "onlyalpha-backend",
        "onlyalpha-backtest",
        "onlyalpha-runtime-persistence",
        "onlyalpha-execution",
        "onlyalpha-clock",
        "onlyalpha-order",
        "onlyalpha-position",
        "onlyalpha-account",
        "onlyalpha-strategy-ledger",
        "onlyalpha-risk",
        "onlyalpha-broker",
        "onlyalpha-fee",
        "onlyalpha-settlement",
        "onlyalpha-margin",
        "onlyalpha-plugin-binance",
        "onlyalpha-plugin-tushare",
    }
    assert not (manifest.parent / "src/onlyalpha").exists()
    assert not (manifest.parent / "crates/onlyalpha-kernel/predicates").exists()


def test_http_server_isolation_excludes_python_http_sources(tmp_path: Path) -> None:
    import tomllib

    from scripts.rust_kernel_check import ROOT, isolated_backend

    manifest = isolated_backend(ROOT, tmp_path / "http")
    assert set(tomllib.loads(manifest.read_text())["workspace"]["members"]) == {
        "crates/onlyalpha-kernel/domain",
        "crates/onlyalpha-kernel/calculation",
        "crates/onlyalpha-kernel/market_data/construction",
        "crates/onlyalpha-kernel/strategy",
        "crates/onlyalpha-kernel/event",
        "crates/onlyalpha-kernel/market_data/state",
        "crates/onlyalpha-kernel/market_data/delivery",
        "crates/onlyalpha-kernel/market_data/pipeline",
        "crates/onlyalpha-gateway-protocol",
        "crates/onlyalpha-calculation-bridge",
        "crates/onlyalpha-metadata-json",
        "crates/onlyalpha-integration-contract",
        "packages/backend",
        "crates/onlyalpha-backtest",
        "crates/onlyalpha-runtime-persistence",
        "crates/onlyalpha-kernel/execution",
        "crates/onlyalpha-kernel/clock",
        "crates/onlyalpha-kernel/order",
        "crates/onlyalpha-kernel/position",
        "crates/onlyalpha-kernel/account",
        "crates/onlyalpha-kernel/strategy_ledger",
        "crates/onlyalpha-kernel/risk",
        "crates/onlyalpha-kernel/broker",
        "crates/onlyalpha-kernel/fee",
        "crates/onlyalpha-kernel/settlement",
        "crates/onlyalpha-kernel/margin",
        "plugs/onlyalpha-plugin-binance",
        "plugs/onlyalpha-plugin-tushare",
    }
    assert not (manifest.parent / "src/onlyalpha").exists()
    assert not list((manifest.parent / "packages/backend/src").rglob("*.py"))
    assert not (manifest.parent / "packages/backend/pyproject.toml").exists()
    assert (manifest.parent / "packages/backend/tests/transport/support/integration_http_probe.rs").is_file()
    assert (manifest.parent / "packages/backend/tests/transport/support/http.rs").is_file()
    packages = tomllib.loads(manifest.with_name("Cargo.lock").read_text())["package"]
    assert {package["name"] for package in packages if "source" not in package} == {
        "onlyalpha-domain",
        "onlyalpha-calculation",
        "onlyalpha-market-data-construction",
        "onlyalpha-strategy",
        "onlyalpha-event",
        "onlyalpha-market-data-state",
        "onlyalpha-market-data-delivery",
        "onlyalpha-market-data-pipeline",
        "onlyalpha-gateway-protocol",
        "onlyalpha-calculation-bridge",
        "onlyalpha-metadata-json",
        "onlyalpha-integration-contract",
        "onlyalpha-backend",
        "onlyalpha-backtest",
        "onlyalpha-runtime-persistence",
        "onlyalpha-execution",
        "onlyalpha-clock",
        "onlyalpha-order",
        "onlyalpha-position",
        "onlyalpha-account",
        "onlyalpha-strategy-ledger",
        "onlyalpha-risk",
        "onlyalpha-broker",
        "onlyalpha-fee",
        "onlyalpha-settlement",
        "onlyalpha-margin",
        "onlyalpha-plugin-binance",
        "onlyalpha-plugin-tushare",
    }


def test_isolated_lock_resolution_only_removes_optional_dependencies(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    import subprocess

    import pytest

    from scripts.rust_kernel_check import prepare_isolated_lock

    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[workspace]\n")
    original = (
        'version=4\n[[package]]\nname="root"\nversion="1"\ndependencies=["shared 1", "optional"]\n'
        '[[package]]\nname="shared"\nversion="1"\nchecksum="exact"\n'
        '[[package]]\nname="shared"\nversion="2"\nchecksum="other"\n'
        '[[package]]\nname="optional"\nversion="1"\n'
    )
    reduced = (
        'version=4\n[[package]]\nname="root"\nversion="1"\ndependencies=["shared"]\n'
        '[[package]]\nname="shared"\nversion="1"\nchecksum="exact"\n'
    )
    original = original.replace('name="shared"', 'source="registry"\nname="shared"').replace(
        'name="optional"', 'source="registry"\nname="optional"'
    )
    reduced = reduced.replace('name="shared"', 'source="registry"\nname="shared"')
    lock = manifest.with_name("Cargo.lock")
    candidates = [
        reduced,
        reduced.replace('checksum="exact"', 'checksum="changed"'),
        reduced.replace('version="1"\nchecksum=', 'version="3"\nchecksum='),
        reduced.replace('dependencies=["shared"]', 'dependencies=["shared", "new"]')
        + '[[package]]\nname="new"\nversion="1"\n',
        reduced.replace('name="shared"', 'source="untrusted"\nname="shared"'),
        reduced.replace('dependencies=["shared"]', 'dependencies=["shared", "root"]'),
    ]
    candidates += [
        reduced.replace("version=4", "version=3"),
        reduced.replace('name="root"', 'name="removed-workspace-member"'),
        reduced + '[[package]]\nname="shared"\nversion="1"\nsource="registry"\nchecksum="exact"\n',
        reduced.replace('dependencies=["shared"]', 'dependencies=["missing"]'),
        "malformed TOML",
    ]
    for candidate in candidates:
        lock.write_text(original)

        def resolve(
            command: list[str], *, selected: str = candidate, **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            assert command == [
                "cargo",
                "metadata",
                "--offline",
                "--format-version",
                "1",
                "--manifest-path",
                str(manifest),
            ]
            assert kwargs["env"] == {"CONTROLLED": "1"}
            lock.write_text(selected)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr("scripts.rust_kernel_check.subprocess.run", resolve)
        if candidate == reduced:
            prepare_isolated_lock(manifest, {"CONTROLLED": "1"})
            assert lock.read_text() == reduced
        else:
            with pytest.raises(ValueError, match="RUST_ISOLATED_LOCK_CHANGED"):
                prepare_isolated_lock(manifest, {"CONTROLLED": "1"})
            assert lock.read_text() == original

    lock.write_text(original)

    def failed_resolution(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        lock.write_text("partially written lock")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("scripts.rust_kernel_check.subprocess.run", failed_resolution)
    with pytest.raises(ValueError, match="RUST_ISOLATED_LOCK_CHANGED"):
        prepare_isolated_lock(manifest, {"CONTROLLED": "1"})
    assert lock.read_bytes() == original.encode()


def test_public_contracts_have_independent_pure_source_closures(tmp_path: Path) -> None:
    import tomllib

    from scripts.rust_kernel_check import ROOT, isolated_integration_contract, isolated_metadata_json

    for materialize, expected in [
        (isolated_metadata_json, {"onlyalpha-metadata-json"}),
        (
            isolated_integration_contract,
            {
                "onlyalpha-domain",
                "onlyalpha-market-data-construction",
                "onlyalpha-metadata-json",
                "onlyalpha-integration-contract",
            },
        ),
    ]:
        manifest = materialize(ROOT, tmp_path / materialize.__name__)
        packages = tomllib.loads(manifest.with_name("Cargo.lock").read_text())["package"]
        assert {item["name"] for item in packages if "source" not in item} == expected
        for prohibited in ["onlyalpha-backend", "onlyalpha-backend", "onlyalpha-backtest"]:
            assert not (manifest.parent / "packages" / prohibited).exists()
        assert not (manifest.parent / "src").exists()


def test_public_contracts_cannot_acquire_process_or_network_inputs(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_infrastructure_sources

    _infrastructure_source_tree(tmp_path)
    for component in ["onlyalpha-metadata-json", "onlyalpha-integration-contract"]:
        path = tmp_path / "crates" / component / "rust/lib.rs"
        for source in [
            "use std::process::Command;",
            "use std::net::TcpStream;",
            "use std::{fs::File};",
            "use std::time::SystemTime;",
        ]:
            path.write_text(source)
            with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
                validate_infrastructure_sources(tmp_path)
        path.write_text("")

    for filename in ("spot_rest.rs", "spot_source.rs", "spot_temporary.rs"):
        transport = tmp_path / "plugs/onlyalpha-plugin-binance/rust" / filename
        transport.write_text("use std::time::{Duration, Instant};\n")
        validate_infrastructure_sources(tmp_path)
        for forbidden in (
            "use std::fs::File;",
            "use std::process::Command;",
            'env!("HIDDEN");',
            'include_str!("/untrusted");',
        ):
            transport.write_text(forbidden)
            with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
                validate_infrastructure_sources(tmp_path)
        transport.write_text("")
    for relative in (
        "onlyalpha-plugin-binance/rust/lib.rs",
        "onlyalpha-plugin-binance/rust/metadata.rs",
        "onlyalpha-plugin-tushare/rust/spot_rest.rs",
    ):
        path = tmp_path / "plugs" / relative
        path.write_text("use std::time::Instant;")
        with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
            validate_infrastructure_sources(tmp_path)
        path.write_text("")


def test_public_contracts_reject_reverse_and_undeclared_manifest_edges(tmp_path: Path) -> None:
    import shutil
    import tomllib

    import pytest

    from scripts.rust_kernel_check import ROOT, validate_workspace

    for filename in ("Cargo.toml", "Cargo.lock"):
        shutil.copyfile(ROOT / filename, tmp_path / filename)
    for relative in tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["members"]:
        destination = tmp_path / relative / "Cargo.toml"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / relative / "Cargo.toml", destination)
    validate_workspace(tmp_path)
    for component, dependency in [
        ("onlyalpha-metadata-json", "onlyalpha-integration-contract"),
        ("onlyalpha-integration-contract", "onlyalpha-backend"),
    ]:
        manifest = tmp_path / "crates" / component / "Cargo.toml"
        original = manifest.read_text()
        candidates = [
            original.replace(
                "[dependencies]", "[dependencies]\n" + dependency + ' = { path = "../' + dependency + '" }'
            ),
            original + '[dev-dependencies]\nonlyalpha-backend = { path = "../onlyalpha-backend" }\n',
            original.replace('features = ["std"]', 'features = ["std", "derive"]', 1),
            original.replace("[dependencies]", "[target.'cfg(unix)'.dependencies]", 1),
        ]
        for candidate in candidates:
            manifest.write_text(candidate)
            with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
                validate_workspace(tmp_path)
        manifest.write_text(original)


def test_source_authoring_isolated_closures_exclude_python_and_product(tmp_path: Path) -> None:
    import tomllib

    from scripts.rust_kernel_check import ROOT, isolated_plugin_binance, isolated_plugin_tushare

    for name, materialize in [("binance", isolated_plugin_binance), ("tushare", isolated_plugin_tushare)]:
        manifest = materialize(ROOT, tmp_path / name)
        packages = tomllib.loads(manifest.with_name("Cargo.lock").read_text())["package"]
        expected = {
            "onlyalpha-domain",
            "onlyalpha-market-data-construction",
            "onlyalpha-metadata-json",
            "onlyalpha-integration-contract",
            "onlyalpha-plugin-" + name,
        }
        if name == "binance":
            expected.add("onlyalpha-domain")
        assert {p["name"] for p in packages if "source" not in p} == expected
        area = manifest.parent / "plugs" / ("onlyalpha-plugin-" + name)
        assert not (area / "src").exists()
        assert not (area / "pyproject.toml").exists()
        assert not (manifest.parent / "packages/backend").exists()


def test_source_authoring_admits_only_exact_reviewed_dependencies(tmp_path: Path) -> None:
    import shutil
    import tomllib

    import pytest

    from scripts.rust_kernel_check import ROOT, validate_workspace

    for name in ("Cargo.toml", "Cargo.lock"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    for relative in tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["members"]:
        destination = tmp_path / relative / "Cargo.toml"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / relative / "Cargo.toml", destination)
    validate_workspace(tmp_path)
    for name in ("binance", "tushare"):
        manifest = tmp_path / "plugs" / ("onlyalpha-plugin-" + name) / "Cargo.toml"
        original = manifest.read_text()
        for candidate in [
            original.replace("onlyalpha-integration-contract =", "alias ="),
            original.replace("[dependencies]", "[target.'cfg(unix)'.dependencies]"),
            original.replace(
                'features = ["std", "arbitrary_precision", "raw_value"]',
                'features = ["std", "arbitrary_precision", "raw_value", "float_roundtrip"]',
            ),
            (
                original.replace(
                    "[dev-dependencies]",
                    '[dev-dependencies]\nonlyalpha-backend = { path = "../../packages/backend" }',
                )
                if "[dev-dependencies]" in original
                else original + '[dev-dependencies]\nonlyalpha-backend = { path = "../../packages/backend" }\n'
            ),
        ]:
            manifest.write_text(candidate)
            with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
                validate_workspace(tmp_path)
        manifest.write_text(original)


def test_crypto_build_uses_pinned_bundled_code_instead_of_ambient_libraries(tmp_path: Path) -> None:
    overrides = {
        "AWS_LC_SYS_USE_SYSTEM": "1",
        "AWS_LC_SYS_SYSTEM_DIR": "/untrusted",
        "AWS_LC_SYS_SYSTEM_BINDINGS": "/untrusted/bindings.rs",
        "AWS_LC_SYS_SYSTEM_SKIP_VERSION_CHECK": "1",
        "AWS_LC_SYS_STATIC": "0",
        "AWS_LC_SYS_USE_SYSTEM_aarch64_unknown_linux_gnu": "1",
        "CMAKE_TOOLCHAIN_FILE": "/untrusted/toolchain.cmake",
        "CMAKE_GENERATOR": "untrusted",
        "TARGET_CMAKE_PREFIX_PATH": "/untrusted",
        "CMAKE_aarch64_unknown_linux_gnu": "/untrusted/cmake",
        "ICU4X_DATA_DIR": "/untrusted/generated-source",
    }
    env = compiler_environment(overrides, tmp_path)
    assert env["AWS_LC_SYS_USE_SYSTEM"] == "0"
    assert env["AWS_LC_SYS_STATIC"] == "1"
    assert set(overrides) & set(env) == {"AWS_LC_SYS_USE_SYSTEM", "AWS_LC_SYS_STATIC"}


def test_infrastructure_declared_compile_inputs_are_validated(tmp_path: Path) -> None:
    import pytest

    from scripts import rust_kernel_check as check

    _infrastructure_source_tree(tmp_path)
    declarations = (
        ("chart/admission_tests.rs", "admission-vector.json"),
        ("chart/admission_tests.rs", "admission-definition.json"),
        ("market_product/temporary_tests.rs", "../../../../../test-data/domain/instrument-records-v2.jsonl"),
    )
    for source, argument in declarations:
        path = tmp_path / "packages/backend/src/application" / source
        path.parent.mkdir(parents=True, exist_ok=True)
        resource = (path.parent / argument).resolve()
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("{}")
        path.write_text(f'const INPUT: &str = include_str!("{argument}");')
        check.validate_infrastructure_sources(tmp_path)
        for mutation in (
            f'include_bytes!("{argument}")',
            f'include_str!(concat!("{argument}"))',
            'include_str!("extra.json")',
            'env!("UNDECLARED_INPUT")',
            'option_env!("CARGO_PKG_VERSION")',
            '#[path="hidden.rs"] mod hidden;',
        ):
            path.write_text(mutation)
            with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
                check.validate_infrastructure_sources(tmp_path)
        path.write_text(f'include_str!("{argument}")')
        resource.unlink()
        with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
            check.validate_infrastructure_sources(tmp_path)
        resource.symlink_to(path)
        with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
            check.validate_infrastructure_sources(tmp_path)
        resource.unlink()
        resource.write_text("{}")
        wrong_owner = path.with_name("other_tests.rs")
        wrong_owner.write_text(path.read_text())
        with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
            check.validate_infrastructure_sources(tmp_path)
        wrong_owner.unlink()
        if argument.startswith("../"):
            moved = tmp_path / "relocated-domain"
            resource.parent.rename(moved)
            resource.parent.symlink_to(moved, target_is_directory=True)
            with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
                check.validate_infrastructure_sources(tmp_path)


def test_http_descriptors_admit_only_cargo_package_version(tmp_path: Path) -> None:
    import pytest

    from scripts.rust_kernel_check import validate_infrastructure_sources

    _infrastructure_source_tree(tmp_path)
    for name in ("main.rs", "bootstrap/workstation_startup.rs"):
        path = tmp_path / "packages/backend/src" / name
        path.write_text('env!("CARGO_PKG_VERSION")')
        validate_infrastructure_sources(tmp_path)
        for mutation in ('env!("UNDECLARED_INPUT")', 'option_env!("CARGO_PKG_VERSION")'):
            path.write_text(mutation)
            with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
                validate_infrastructure_sources(tmp_path)
        path.write_text("")
    path.with_name("lib.rs").write_text('env!("CARGO_PKG_VERSION")')
    with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
        validate_infrastructure_sources(tmp_path)


@mark.parametrize("materializer", ("isolated_backend",))
def test_declared_product_resources_are_in_fingerprinted_isolated_closure(tmp_path: Path, materializer: str) -> None:
    from scripts import rust_kernel_check as check
    from scripts.dev_verification import source_inputs

    check.validate_infrastructure_sources(check.ROOT)
    manifest = getattr(check, materializer)(check.ROOT, tmp_path / "isolated")
    inputs = source_inputs(manifest.parent)
    original = source_inputs(check.ROOT)
    resources = [
        "packages/backend/src/application/chart/admission-vector.json",
        "packages/backend/src/application/chart/admission-definition.json",
        "test-data/domain/instrument-records-v2.jsonl",
        "packages/backend/src/application/market_product/temporary_tests.rs",
        "packages/backend/src/application/market_product/temporary_reference_tests.rs",
        "packages/backend/Cargo.toml",
    ]
    if materializer == "isolated_backend":
        resources += [
            "plugs/onlyalpha-plugin-binance/rust/spot_temporary.rs",
            "packages/backend/Cargo.toml",
        ]
    for relative in resources:
        assert inputs[relative] == original[relative]
        copied = manifest.parent / relative
        assert copied.resolve().is_relative_to(tmp_path.resolve())
        # Fault injection mutates only this test-owned copy of frozen inputs.
        copied.chmod(copied.stat().st_mode | 0o200)
        copied.write_bytes(copied.read_bytes() + b"\n")
        assert source_inputs(manifest.parent)[relative] != inputs[relative]


def test_infrastructure_source_modules_are_exact_and_physical(tmp_path: Path) -> None:
    import pytest

    from scripts import rust_kernel_check as check

    _infrastructure_source_tree(tmp_path)
    for directory, owner, target in (
        ("packages/backend/src/application/market_product", "queries.rs", "temporary_reference_tests.rs"),
        ("packages/backend/src/application/market_product", "temporary.rs", "temporary_tests.rs"),
        ("plugs/onlyalpha-plugin-binance/rust", "spot_source.rs", "spot_temporary.rs"),
    ):
        path = tmp_path / directory / owner
        path.parent.mkdir(parents=True, exist_ok=True)
        module = path.with_name(target)
        module.write_text("")
        path.write_text(f'#[path = "{target}"] mod tests;')
        check.validate_infrastructure_sources(tmp_path)
        module.unlink()
        with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
            check.validate_infrastructure_sources(tmp_path)
        module.symlink_to(path)
        with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
            check.validate_infrastructure_sources(tmp_path)
        module.unlink()
        module.write_text("")
        for mutation in ('#[path="other.rs"] mod tests;', f'#[cfg_attr(test, path="{target}")] mod tests;'):
            path.write_text(mutation)
            with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
                check.validate_infrastructure_sources(tmp_path)
        path.write_text("")


def test_rust_macro_guard_distinguishes_inequality_from_macro_invocation() -> None:
    from scripts.rust_kernel_check import _hidden_rust_input

    assert not _hidden_rust_input('if include != request["preview_stream_id"].is_string() {}')
    for macro in ("include", "env", "option_env"):
        for expression in (
            f'{macro}!("hidden")',
            f'{macro}! ["hidden"]',
            f'{macro}! {{"hidden"}}',
            f'{macro}! /* source input */ ("hidden")',
        ):
            assert _hidden_rust_input(expression)


@mark.parametrize("materializer", ("isolated_backend",))
def test_isolated_declared_inputs_reuse_frozen_resource_bytes(tmp_path: Path, materializer: str) -> None:
    from scripts import rust_kernel_check as check

    isolate = getattr(check, materializer)
    frozen = isolate(check.ROOT, tmp_path / "frozen").parent
    for path in frozen.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    result = isolate(frozen, tmp_path / "result").parent
    resource = "packages/backend/src/application/chart/admission-vector.json"
    assert (result / resource).read_bytes() == (frozen / resource).read_bytes()
    assert (result / resource).stat().st_mode & 0o222 == 0


@mark.parametrize("mutation", ("conflict", "symlink"))
def test_isolated_declared_inputs_reject_conflicting_copies(
    tmp_path: Path, monkeypatch: MonkeyPatch, mutation: str
) -> None:
    import shutil
    from typing import Any

    import pytest

    from scripts import rust_kernel_check as check

    original = shutil.copytree
    observed = []

    def copytree(*args: Any, **kwargs: Any) -> object:
        result = original(*args, **kwargs)
        destination = Path(str(args[1])) / "src/application/chart/admission-vector.json"
        if destination.is_file():
            destination.unlink()
            if mutation == "conflict":
                destination.write_bytes(b"conflicting bytes")
            else:
                destination.symlink_to(check.ROOT / "packages/backend/src/application/chart/admission-vector.json")
            observed.append(destination)
        return result

    monkeypatch.setattr(shutil, "copytree", copytree)
    with pytest.raises(ValueError, match="BOUNDARY_INVALID"):
        check.isolated_backend(check.ROOT, tmp_path / "result")
    assert len(observed) == 1
    if mutation == "conflict":
        assert observed[0].read_bytes() == b"conflicting bytes"
    else:
        assert observed[0].is_symlink()


def test_local_fee_changes_select_only_owner_and_direct_consumers() -> None:
    from scripts import rust_kernel_check as check

    assert check.affected_packages(check.ROOT, ("crates/onlyalpha-kernel/fee/src/lib.rs",)) == (
        "onlyalpha-execution",
        "onlyalpha-fee",
    )
    assert check.affected_packages(check.ROOT, ("test-data/fee/common-v1.json",)) == (
        "onlyalpha-execution",
        "onlyalpha-fee",
    )
    commands = check.targeted_build_commands("aarch64-unknown-linux-gnu", ("onlyalpha-execution", "onlyalpha-fee"))
    assert [command[1] for command in commands] == ["fmt", "clippy", "test"]
    assert all("--workspace" not in command and "--release" not in command for command in commands)
    assert all(
        "onlyalpha-account" not in command and "onlyalpha-strategy-ledger" not in command for command in commands
    )
    for command in commands[1:]:
        assert all(flag in command for flag in ("--frozen", "--offline", "-j1"))
    assert commands[-1][-2:] == ["--", "--test-threads=1"]
    assert any("--release" in command for command in check.build_commands("aarch64-unknown-linux-gnu"))


def test_local_unknown_rust_and_workspace_metadata_require_explicit_impact_review() -> None:
    import pytest

    from scripts import rust_kernel_check as check

    for path in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "crates/onlyalpha-kernel/unknown/src/lib.rs"):
        with pytest.raises(ValueError, match="RUST_IMPACT_REVIEW_REQUIRED"):
            check.affected_packages(check.ROOT, (path,))
    assert check.affected_packages(check.ROOT, ("scripts/rust_kernel_check.py",)) == ()


def test_local_source_guard_removes_stale_full_gate_receipt(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from scripts import rust_kernel_check as check

    receipt = tmp_path / "test-results/rust-kernel/last-run.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("stale full gate")
    monkeypatch.setattr(check, "ROOT", tmp_path)
    guarded = []
    monkeypatch.setattr(check, "validate_sources", lambda root: guarded.append(root))
    monkeypatch.setattr(
        "scripts.rust_kernel_check.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cargo")),
    )
    assert check.main(["--source-check"]) == 0
    assert guarded == [tmp_path]
    assert not receipt.exists()


@mark.parametrize(
    "owner,needs_replay",
    (("fee", False), ("strategy", True), ("calculation_bridge", True), ("backtest", True), ("backend", True)),
)
def test_local_package_mode_runs_only_default_profile_without_full_receipt(
    tmp_path: Path, monkeypatch: MonkeyPatch, owner: str, needs_replay: bool
) -> None:
    from scripts import rust_kernel_check as check

    packages = check.affected_packages(check.ROOT, (str(check.module_path(owner) / "Cargo.toml"),))
    prepared = []

    def replay_environment(root: Path, artifacts: Path) -> dict[str, str]:
        prepared.append((root, artifacts))
        return {"REPLAY_PYTHON": "controlled-python"}

    monkeypatch.setattr("scripts.backtest_replay_check.replay_environment", replay_environment)
    receipt = tmp_path / "test-results/rust-kernel/last-run.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("stale full gate")
    (tmp_path / "rust-toolchain.toml").write_text('[toolchain]\nchannel="1.99.1"\n')
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("scripts.rust_kernel_check.platform.machine", lambda: "aarch64")
    monkeypatch.setattr(check, "_workspace_packages", lambda root: dict.fromkeys(packages))
    monkeypatch.setattr(check, "validate_sources", lambda root: None)
    monkeypatch.setattr(check, "source_inputs", lambda root: {})
    monkeypatch.setattr(check, "compiler_environment", lambda inherited, target: {"CARGO_HOME": str(tmp_path)})
    monkeypatch.setattr(check, "prepare_cargo_home", lambda *args: None)
    monkeypatch.setattr(
        "scripts.rust_kernel_check.subprocess.check_output",
        lambda *args, **kwargs: "release: 1.99.1\nhost: aarch64-unknown-linux-gnu\n",
    )
    commands = []
    environments = []

    def run(command: list[str], **kwargs: object) -> None:
        commands.append(command)
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        environments.append(environment)

    monkeypatch.setattr("scripts.rust_kernel_check.subprocess.run", run)
    assert check.main([flag for package in packages for flag in ("--package", package)]) == 0
    assert commands == check.targeted_build_commands("aarch64-unknown-linux-gnu", packages)
    assert len(prepared) == int(needs_replay)
    assert all(("REPLAY_PYTHON" in environment) == needs_replay for environment in environments)
    assert not receipt.exists()
