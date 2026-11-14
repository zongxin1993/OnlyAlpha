"""Provider boundaries admit only their declared inputs, including Cargo versions."""

import tomllib
from pathlib import Path

import pytest

from scripts.rust_kernel_check import validate_infrastructure_sources

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    ROOT / "plugs/onlyalpha-market-crypto/src/reference.rs",
    ROOT / "plugs/onlyalpha-market-crypto/src/market_policy.rs",
    ROOT / "plugs/onlyalpha-data-source-binance/src/reference_capture.rs",
    ROOT / "plugs/onlyalpha-data-source-binance/src/spot_reference.rs",
    ROOT / "plugs/onlyalpha-data-source-binance/src/usdm_reference.rs",
    ROOT / "plugs/onlyalpha-broker-binance/src/lib.rs",
    ROOT / "plugs/onlyalpha-broker-binance/src/private_http.rs",
    ROOT / "plugs/onlyalpha-broker-binance/src/stream.rs",
    ROOT / "plugs/onlyalpha-broker-binance/src/tests/loopback_tls.rs",
    ROOT / "plugs/onlyalpha-broker-virtual/src/lib.rs",
    ROOT / "plugs/onlyalpha-broker-virtual/src/plan.rs",
    ROOT / "plugs/onlyalpha-data-source-binance/src/usdm_rest.rs",
    ROOT / "plugs/onlyalpha-data-source-binance/src/tests/usdm_rest.rs",
    ROOT / "plugs/onlyalpha-data-source-tushare/src/http.rs",
    ROOT / "plugs/onlyalpha-data-source-tushare/src/daily.rs",
    ROOT / "plugs/onlyalpha-data-source-tushare/src/tests/http.rs",
    ROOT / "plugs/onlyalpha-data-source-tushare/src/source.rs",
)


def test_current_plugin_transport_has_only_declared_inputs():
    validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize(
    "expression",
    [
        'std::fs::read("hidden-input")',
        'std::env::var("HIDDEN_INPUT")',
        'env!("HIDDEN_INPUT")',
        'std::process::Command::new("hidden-input")',
        "std::time::SystemTime::now()",
        '#[path = "undeclared.rs"] mod hidden',
        'include_str!("undeclared-input.json")',
        'include_bytes!("undeclared-input.pem")',
        f'include_bytes!("{ROOT / "PROJECT_CONSTITUTION.md"}")',
    ],
)
@pytest.mark.parametrize("transport", SOURCES)
def test_transport_admission_still_rejects_hidden_inputs(monkeypatch, expression, transport):
    original = Path.read_text

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        if path == transport:
            return content + "\nfn forbidden_input() {" + expression + ";}\n"
        return content

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize(
    "expression",
    [
        'std::env::var("HIDDEN_INPUT")',
        'std::process::Command::new("hidden-input")',
        "std::time::SystemTime::now()",
        "std::time::Instant::now()",
        'std::net::TcpStream::connect("127.0.0.1:1")',
        "reqwest::Client::new()",
        "std::io::stdin()",
        'include_bytes!("undeclared-input.pem")',
        f'include_bytes!("{ROOT / "PROJECT_CONSTITUTION.md"}")',
    ],
)
def test_reference_file_store_rejects_ambient_process_network_and_undeclared_inputs(monkeypatch, expression):
    original = Path.read_text
    target = ROOT / "plugs/onlyalpha-data-source-binance/src/reference_store.rs"

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        if path == target:
            return content + "\nfn forbidden_input() {" + expression + ";}\n"
        return content

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


def test_reference_file_store_admits_its_owned_filesystem_input(monkeypatch):
    original = Path.read_text
    target = ROOT / "plugs/onlyalpha-data-source-binance/src/reference_store.rs"

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        if path == target:
            return content + '\nfn owned_input() { let _ = std::fs::read("captures/fixed-sha"); }\n'
        return content

    monkeypatch.setattr(Path, "read_text", read)
    validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize(
    "expression, admitted",
    [
        ("use onlyalpha_broker::Fact as OriginalBrokerFact;", True),
        ("use onlyalpha_data_source_binance::ReferenceCapture;", False),
    ],
)
def test_execution_admits_canonical_broker_types_but_not_provider_implementation(monkeypatch, expression, admitted):
    from scripts.rust_kernel_check import validate_execution_sources

    original = Path.read_text
    target = ROOT / "crates/execution/src/planning.rs"

    def read(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        return text + "\n" + expression + "\n" if path == target else text

    monkeypatch.setattr(Path, "read_text", read)
    if admitted:
        validate_execution_sources(ROOT)
    else:
        with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
            validate_execution_sources(ROOT)


def test_current_financial_owner_dependencies_have_their_exact_declared_kind():
    from scripts.rust_kernel_check import validate_workspace

    validate_workspace(ROOT)


@pytest.mark.parametrize(
    "manifest, dependency, directory",
    [("runtime", "onlyalpha-broker", "broker"), ("strategy-ledger", "onlyalpha-position", "position")],
)
@pytest.mark.parametrize("mutation", ["alias", "features", "registry", "dev"])
def test_financial_producer_edges_reject_aliases_options_registry_and_wrong_kind(
    monkeypatch, manifest, dependency, directory, mutation
):
    from scripts.rust_kernel_check import validate_workspace

    original = Path.read_text
    target = ROOT / "crates" / manifest / "Cargo.toml"
    declaration = f'{dependency} = {{ path = "../{directory}" }}'

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        if path != target:
            return content
        assert content.count(declaration) == 1
        if mutation == "dev":
            content = content.replace(declaration + "\n", "", 1)
            heading = "[dev-dependencies]\n"
            if heading in content:
                return content.replace(heading, heading + declaration + "\n", 1)
            return content + "\n" + heading + declaration + "\n"
        replacement = {
            "alias": f'producer = {{ package = "{dependency}", path = "../{directory}" }}',
            "features": f'{dependency} = {{ path = "../{directory}", features = ["unapproved"] }}',
            "registry": f'{dependency} = {{ version = "=0.11.1" }}',
        }[mutation]
        return content.replace(declaration, replacement, 1)

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_workspace(ROOT)


@pytest.mark.parametrize(
    "expression, admitted",
    [("use onlyalpha_position::FundingEffect;", True), ("use onlyalpha_market_crypto::MarketBinding;", False)],
)
def test_ledger_consumes_position_effects_without_provider_implementation(monkeypatch, expression, admitted):
    from scripts.rust_kernel_check import validate_strategy_ledger_sources

    original = Path.read_text
    target = ROOT / "crates/strategy-ledger/src/manager.rs"

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        return content + "\n" + expression + "\n" if path == target else content

    monkeypatch.setattr(Path, "read_text", read)
    if admitted:
        validate_strategy_ledger_sources(ROOT)
    else:
        with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
            validate_strategy_ledger_sources(ROOT)


@pytest.mark.parametrize("source", ["src/lib.rs", "src/plan.rs"])
@pytest.mark.parametrize("expression", ["use rusqlite::Connection;", "use rusqlite as hidden_store;"])
def test_virtual_sqlite_stays_in_the_source_host(monkeypatch, source, expression):
    original = Path.read_text
    target = ROOT / "plugs/onlyalpha-broker-virtual" / source

    def read(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        return value + "\n" + expression if path == target else value

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize(
    "expression, admitted",
    [
        ('fn explicit_store() { let _ = rusqlite::Connection::open("owned.sqlite3"); }', True),
        ('fn explicit_store() { let _ = std::fs::metadata("owned.sqlite3"); }', True),
        ('fn ambient_input() { let _ = std::env::var("DATABASE_PATH"); }', False),
        ("fn ambient_input() { let _ = std::time::SystemTime::now(); }", False),
        ('fn ambient_input() { let _ = std::process::Command::new("sqlite3"); }', False),
        ('fn ambient_input() { let _ = std::net::TcpStream::connect("127.0.0.1:1"); }', False),
        ("fn ambient_input() { let _ = std::io::stdin(); }", False),
        ('fn ambient_input() { let _ = include_str!("undeclared.db"); }', False),
    ],
)
def test_virtual_source_host_admits_only_owned_storage(monkeypatch, expression, admitted):
    original = Path.read_text
    target = ROOT / "plugs/onlyalpha-broker-virtual/src/source_host.rs"

    def read(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        return value + "\n" + expression if path == target else value

    monkeypatch.setattr(Path, "read_text", read)
    if admitted:
        validate_infrastructure_sources(ROOT)
    else:
        with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
            validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize("mutation", ["version", "features", "defaults", "alias", "kind"])
def test_virtual_source_storage_dependency_is_exact_and_normal(monkeypatch, mutation):
    from scripts.rust_kernel_check import validate_workspace

    target = ROOT / "plugs/onlyalpha-broker-virtual/Cargo.toml"
    original = Path.read_text
    line = 'rusqlite = { version = "=0.40.2", default-features = false, features = ["bundled"] }'

    def read(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path != target:
            return value
        assert value.count(line) == 1
        if mutation == "version":
            return value.replace(line, line.replace("=0.40.2", "^0.40"))
        if mutation == "features":
            return value.replace(line, line.replace('["bundled"]', '["bundled", "functions"]'))
        if mutation == "defaults":
            return value.replace(line, line.replace("false", "true"))
        if mutation == "alias":
            return value.replace(line, line.replace("rusqlite = {", 'store = { package = "rusqlite",'))
        return value.replace(line, "") + "\n[dev-dependencies]\n" + line + "\n"

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_workspace(ROOT)


def test_backtest_isolation_keeps_every_declared_local_dependency(tmp_path):
    from scripts.rust_kernel_check import isolated_backtest

    manifest = isolated_backtest(ROOT, tmp_path / "workspace")
    isolated = manifest.parent
    members = tomllib.loads(manifest.read_text())["workspace"]["members"]
    missing = []
    for member in members:
        package = isolated / member / "Cargo.toml"
        declaration = tomllib.loads(package.read_text())
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            for name, dependency in declaration.get(section, {}).items():
                if isinstance(dependency, dict) and "path" in dependency:
                    required = package.parent / dependency["path"] / "Cargo.toml"
                    if not required.is_file():
                        missing.append((member, section, name, dependency["path"]))
    assert not missing, missing


@pytest.mark.parametrize(
    "owner,expression",
    [
        ("crates/runtime/tests/support/perpetual_run.rs", 'include_str!("undeclared-funding.json")'),
        ("crates/runtime/src/tests/funding_commit.rs", '#[path = "undeclared-funding.rs"] mod hidden;'),
        ("crates/runtime/src/transcript.rs", '#[path = "undeclared-source.rs"] mod hidden;'),
        ("crates/runtime/src/transcript.rs", 'include_str!("undeclared-result.json")'),
    ],
)
def test_funding_fault_helpers_reject_undeclared_inputs(monkeypatch, owner, expression):
    original = Path.read_text

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        if path == ROOT / owner:
            return content + "\n" + expression + "\n"
        return content

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


def test_runtime_isolation_keeps_shared_funding_fixture_with_its_consumer(tmp_path):
    from scripts.rust_kernel_check import isolated_runtime_persistence

    manifest = isolated_runtime_persistence(ROOT, tmp_path / "workspace")
    consumer = manifest.parent / "crates/runtime/tests/support/perpetual_run.rs"
    resource = consumer.parent / "../../../../test-data/execution/linear-perpetual.json"
    assert consumer.is_file()
    assert resource.resolve() == (manifest.parent / "test-data/execution/linear-perpetual.json").resolve()
    assert resource.read_bytes() == (ROOT / "test-data/execution/linear-perpetual.json").read_bytes()


@pytest.mark.parametrize(
    "expression",
    [
        'fn hidden_env() { let _ = std::env::var("HIDDEN_PROBE_INPUT"); }',
        'fn hidden_file() { let _ = std::fs::read("hidden-probe-input"); }',
        '#[path = "undeclared-probe.rs"] mod hidden;',
    ],
)
def test_probe_transport_tests_keep_environment_files_and_extra_modules_forbidden(monkeypatch, expression):
    original = Path.read_text
    owner = ROOT / "plugs/onlyalpha-data-source-binance/src/tests/spot_probe.rs"

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        return content + "\n" + expression + "\n" if path == owner else content

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize(
    "expression",
    [
        'std::fs::write("unexpected-output", b"data")',
        "std::env::temp_dir()",
        "std::time::SystemTime::now()",
        'std::process::Command::new("unexpected-process")',
        '#[path = "undeclared-testnet.rs"] mod hidden',
        'include_str!("undeclared-testnet-input.json")',
    ],
)
def test_external_testnet_entry_rejects_writes_processes_and_undeclared_inputs(monkeypatch, expression):
    original = Path.read_text
    owner = ROOT / "plugs/onlyalpha-broker-binance/src/tests/spot_testnet_external.rs"

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        return content + "\nfn forbidden_input() {" + expression + ";}\n" if path == owner else content

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize("missing", ["test_only_mount", "ignored_entry", "production_alias"])
def test_external_testnet_io_cannot_enter_production_or_default_tests(monkeypatch, missing):
    import re

    original = Path.read_text
    owner = ROOT / (
        "plugs/onlyalpha-broker-binance/src/private_http.rs"
        if missing in {"test_only_mount", "production_alias"}
        else "plugs/onlyalpha-broker-binance/src/tests/spot_testnet_external.rs"
    )

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        if path != owner:
            return content
        if missing == "production_alias":
            return content + '\n#[path = "tests/spot_testnet_external.rs"] mod unsafe_production_alias;\n'
        pattern = (
            r'#\[cfg\(test\)\](\s*#\[path\s*=\s*"tests/spot_testnet_external\.rs"\])'
            if missing == "test_only_mount"
            else r'#\[ignore\s*=\s*"[^"\n]+"\]\s*'
        )
        changed, count = re.subn(pattern, r"\1" if missing == "test_only_mount" else "", content)
        assert count == 1
        return changed

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize(
    "expression",
    [
        'std::env::var("UNDECLARED_CREDENTIAL")',
        "std::time::Instant::now()",
        'std::net::TcpStream::connect("127.0.0.1:1")',
        'std::process::Command::new("unexpected-process")',
        "std::thread::spawn(|| {})",
        'include_str!("undeclared-cash-input.json")',
        '#[path = "undeclared-cash.rs"] mod hidden',
    ],
)
def test_cash_consumer_owned_files_do_not_admit_external_inputs(monkeypatch, expression):
    original = Path.read_text
    owner = ROOT / "plugs/onlyalpha-broker-binance/src/tests/cash_execution.rs"

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        return content + "\nfn forbidden_input() {" + expression + ";}\n" if path == owner else content

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize("mutation", ["not_linux", "not_test", "production_alias", "non_linux_alias"])
def test_cash_consumer_filesystem_capability_stays_in_linux_tests(monkeypatch, mutation):
    import re

    original = Path.read_text
    parent = ROOT / "plugs/onlyalpha-broker-binance/src/tests/venue_recovery.rs"
    enclosing = ROOT / "plugs/onlyalpha-broker-binance/src/lib.rs"
    owner = enclosing if mutation in {"not_test", "production_alias"} else parent

    def read(path, *args, **kwargs):
        content = original(path, *args, **kwargs)
        if path != owner:
            return content
        if mutation == "production_alias":
            return content + '\n#[path = "tests/venue_recovery.rs"] mod unsafe_production_alias;\n'
        if mutation == "non_linux_alias":
            return content + '\n#[path = "cash_execution.rs"] mod unsafe_cross_platform_alias;\n'
        pattern = (
            r'#\[cfg\(test\)\](\s*#\[path\s*=\s*"tests/venue_recovery\.rs"\])'
            if mutation == "not_test"
            else r'#\[cfg\(target_os\s*=\s*"linux"\)\](\s*#\[path\s*=\s*"cash_execution\.rs"\])'
        )
        changed, count = re.subn(pattern, r"\1", content)
        assert count == 1
        return changed

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="RUST_MODULE_BOUNDARY_INVALID"):
        validate_infrastructure_sources(ROOT)


@pytest.mark.parametrize(
    "owner",
    [
        "isolated_runtime_persistence",
        "isolated_backtest",
        "isolated_backend",
        "isolated_plugin_binance",
        "isolated_broker_binance",
    ],
)
def test_runtime_consumers_copy_their_complete_declared_local_dependency_closure(tmp_path, owner):
    from scripts import rust_kernel_check

    manifest = getattr(rust_kernel_check, owner)(ROOT, tmp_path / "workspace")
    isolated = manifest.parent
    for member in tomllib.loads(manifest.read_text())["workspace"]["members"]:
        package = isolated / member / "Cargo.toml"
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            for name, dependency in tomllib.loads(package.read_text()).get(section, {}).items():
                if isinstance(dependency, dict) and "path" in dependency:
                    assert (package.parent / dependency["path"] / "Cargo.toml").is_file(), (owner, member, name)
