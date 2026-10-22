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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

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
        key: value
        for key, value in inherited.items()
        if (not key.startswith(("RUST", "CARGO")) or key == "RUSTUP_HOME")
        and not key.startswith(("SQLITE", "LIBSQLITE", "PKG_CONFIG", "VCPKG", "CRATE_CC_", "CC_", "LD_"))
        and "AWS_LC_" not in key
        and "CMAKE" not in key
        and "ICU4X_" not in key
        and re.search(r"(?:^|_)(?:CC|CXX|AR|RANLIB|CFLAGS|CPPFLAGS|CXXFLAGS|ARFLAGS|SQLITE3)(?:_|$)", key) is None
        and key
        not in {
            "CROSS_COMPILE",
            "CPATH",
            "C_INCLUDE_PATH",
            "CPLUS_INCLUDE_PATH",
            "LIBRARY_PATH",
            "GCC_EXEC_PREFIX",
            "COMPILER_PATH",
        }
    }
    env.update(
        AWS_LC_SYS_USE_SYSTEM="0",
        AWS_LC_SYS_STATIC="1",
        CC="/usr/bin/gcc",
        AR="/usr/bin/ar",
        CARGO_HOME=str(target_dir.parent / "cargo-home"),
        CARGO_NET_OFFLINE="true",
        RUSTUP_AUTO_INSTALL="0",
        CARGO_BUILD_JOBS="1",
        CARGO_TARGET_DIR=str(target_dir),
    )
    return env


# Independently reviewed public registry closure, excluding local release metadata.
REGISTRY_LOCK_SHA256 = "4678100e7688bdc3dd71ef0c32dc7db79d2652c4a8ec476491837df6bc144324"
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


MARKET_DATA_STATE_DEPENDENCIES = {
    **CLOCK_DEPENDENCIES,
    "onlyalpha-domain": {"path": "../../domain"},
    "serde_json": DOMAIN_DEPENDENCIES["serde_json"],
}


CONSTRUCTION_DEPENDENCIES = {**MARKET_DATA_STATE_DEPENDENCIES, "sha2": DOMAIN_DEPENDENCIES["sha2"]}


DELIVERY_DEPENDENCIES = {
    **MARKET_DATA_STATE_DEPENDENCIES,
    "onlyalpha-market-data-state": {"path": "../state"},
    "onlyalpha-market-data-construction": {"path": "../construction"},
}

PROTOCOL_DEPENDENCIES = {
    "prost": {"version": "=0.14.4"},
    "prost-build": {"version": "=0.14.4", "optional": True},
    "prost-types": {"version": "=0.14.4", "optional": True},
}
PIPELINE_DEPENDENCIES = {
    **DELIVERY_DEPENDENCIES,
    "onlyalpha-calculation": {"path": "../../calculation"},
    "onlyalpha-market-data-delivery": {"path": "../delivery"},
    "sha2": DOMAIN_DEPENDENCIES["sha2"],
}
STRATEGY_DEPENDENCIES = {
    "onlyalpha-domain": {"path": "../domain"},
    "onlyalpha-calculation": {"path": "../calculation"},
    "onlyalpha-market-data-construction": {"path": "../market_data/construction"},
    "num-bigint": CLOCK_DEPENDENCIES["num-bigint"],
    "serde_json": DOMAIN_DEPENDENCIES["serde_json"],
    "sha2": DOMAIN_DEPENDENCIES["sha2"],
}
ORDER_DEPENDENCIES = {
    "onlyalpha-domain": {"path": "../domain"},
    "num-bigint": CLOCK_DEPENDENCIES["num-bigint"],
    **{name: DOMAIN_DEPENDENCIES[name] for name in ("bigdecimal", "serde_json", "sha2")},
}

POSITION_DEPENDENCIES = dict(ORDER_DEPENDENCIES)
ACCOUNT_DEPENDENCIES = dict(ORDER_DEPENDENCIES)

WORKER_DEPENDENCIES = {
    "onlyalpha-strategy": {"path": "../../crates/onlyalpha-kernel/strategy"},
    "onlyalpha-market-data-pipeline": {"path": "../../crates/onlyalpha-kernel/market_data/pipeline"},
    "onlyalpha-calculation": {"path": "../../crates/onlyalpha-kernel/calculation"},
    "onlyalpha-domain": {"path": "../../crates/onlyalpha-kernel/domain"},
    "onlyalpha-gateway-protocol": {"path": "../onlyalpha-gateway-protocol"},
    "prost": {"version": "=0.14.4"},
    "sha2": DOMAIN_DEPENDENCIES["sha2"],
    "serde_json": DOMAIN_DEPENDENCIES["serde_json"],
}

CALCULATION_DEPENDENCIES = {name: DOMAIN_DEPENDENCIES[name] for name in ("bigdecimal", "sha2", "serde_json")}


EVENT_DEPENDENCIES = {**CLOCK_DEPENDENCIES, "serde_json": DOMAIN_DEPENDENCIES["serde_json"]}


BROKER_DEPENDENCIES = {name: config for name, config in ACCOUNT_DEPENDENCIES.items() if name != "num-bigint"}


EXECUTION_DEPENDENCIES = {
    **{name: config for name, config in ACCOUNT_DEPENDENCIES.items() if name != "num-bigint"},
    **{
        "onlyalpha-" + name.replace("_", "-"): {"path": "../" + name}
        for name in ("order", "position", "account", "strategy_ledger", "risk", "fee", "settlement", "margin")
    },
}


RUNTIME_PERSISTENCE_DEPENDENCIES = {
    "onlyalpha-execution": {"path": "../../crates/onlyalpha-kernel/execution"},
    "serde_json": DOMAIN_DEPENDENCIES["serde_json"],
    "rusqlite": {"version": "=0.40.2", "default-features": False, "features": ["bundled"]},
}
BACKTEST_DRIVER_DEPENDENCIES = {
    "onlyalpha-runtime-persistence": {"path": "../onlyalpha-runtime-persistence"},
    "onlyalpha-calculation-worker": {"path": "../onlyalpha-calculation-worker"},
    **{
        name: {"path": "../../crates/onlyalpha-kernel/" + directory}
        for name, directory in {
            "onlyalpha-clock": "clock",
            "onlyalpha-domain": "domain",
            "onlyalpha-execution": "execution",
            "onlyalpha-strategy": "strategy",
            "onlyalpha-market-data-pipeline": "market_data/pipeline",
        }.items()
    },
    "serde_json": DOMAIN_DEPENDENCIES["serde_json"],
}
BACKTEST_DRIVER_TEST_DEPENDENCIES = {"onlyalpha-calculation": {"path": "../../crates/onlyalpha-kernel/calculation"}}

RUNTIME_PERSISTENCE_TEST_DEPENDENCIES = {
    "onlyalpha-domain": {"path": "../../crates/onlyalpha-kernel/domain"},
    "onlyalpha-risk": {"path": "../../crates/onlyalpha-kernel/risk"},
    "bigdecimal": DOMAIN_DEPENDENCIES["bigdecimal"],
}


METADATA_JSON_DEPENDENCIES = {
    "serde": {"version": "=1.0.229", "default-features": False, "features": ["std"]},
    "serde_json": {**DOMAIN_DEPENDENCIES["serde_json"], "features": ["std", "arbitrary_precision", "raw_value"]},
    "sha2": DOMAIN_DEPENDENCIES["sha2"],
}
INTEGRATION_CONTRACT_DEPENDENCIES = {
    "bigdecimal": {"default-features": False, "features": ["std"], "version": "=0.4.11"},
    "onlyalpha-domain": {"path": "../../crates/onlyalpha-kernel/domain"},
    "onlyalpha-market-data-construction": {"path": "../../crates/onlyalpha-kernel/market_data/construction"},
    "onlyalpha-metadata-json": {"path": "../onlyalpha-metadata-json"},
    "serde": {"default-features": False, "features": ["std"], "version": "=1.0.229"},
    "serde_json": {
        "default-features": False,
        "features": ["std", "arbitrary_precision", "raw_value"],
        "version": "=1.0.154",
    },
}


SOURCE_AUTHORING_DEPENDENCIES = {
    "onlyalpha-integration-contract": {"path": "../../packages/onlyalpha-integration-contract"},
    "onlyalpha-metadata-json": {"path": "../../packages/onlyalpha-metadata-json"},
    "serde_json": METADATA_JSON_DEPENDENCIES["serde_json"],
}
BINANCE_DEPENDENCIES = {
    "bigdecimal": {"default-features": False, "features": ["std"], "version": "=0.4.11"},
    "flate2": {"default-features": False, "features": ["rust_backend"], "version": "=1.1.10"},
    "futures-util": {"default-features": False, "features": ["sink", "std"], "version": "=0.3.34"},
    "http": {"default-features": False, "features": ["std"], "version": "=1.5.0"},
    "onlyalpha-domain": {"path": "../../crates/onlyalpha-kernel/domain"},
    "onlyalpha-integration-contract": {"path": "../../packages/onlyalpha-integration-contract"},
    "onlyalpha-market-data-construction": {"path": "../../crates/onlyalpha-kernel/market_data/construction"},
    "onlyalpha-metadata-json": {"path": "../../packages/onlyalpha-metadata-json"},
    "reqwest": {"default-features": False, "features": ["rustls"], "version": "=0.13.5"},
    "rustls": {"default-features": False, "features": ["std", "tls12", "aws_lc_rs"], "version": "=0.23.46"},
    "serde_json": {
        "default-features": False,
        "features": ["std", "arbitrary_precision", "raw_value"],
        "version": "=1.0.154",
    },
    "sha2": {"default-features": False, "features": ["zeroize"], "version": "=0.11.1"},
    "tokio": {"default-features": False, "features": ["rt", "net", "time", "sync", "macros"], "version": "=1.54.1"},
    "tokio-tungstenite": {"default-features": False, "features": ["connect", "__rustls-tls"], "version": "=0.30.0"},
}
BINANCE_TEST_DEPENDENCIES: dict[str, object] = {}


PRODUCT_RUNTIME_DEPENDENCIES = {
    "onlyalpha-calculation": {"path": "../../crates/onlyalpha-kernel/calculation"},
    "onlyalpha-calculation-worker": {"path": "../onlyalpha-calculation-worker"},
    "aes-gcm": {"default-features": False, "features": ["aes", "alloc", "zeroize"], "version": "=0.11.1"},
    "base64": {"default-features": False, "features": ["alloc"], "version": "=0.23.1"},
    "getrandom": {"default-features": False, "version": "=0.4.3"},
    "hkdf": {"default-features": False, "version": "=0.13.0"},
    "hmac": {"default-features": False, "features": ["zeroize"], "version": "=0.13.0"},
    "onlyalpha-domain": {"path": "../../crates/onlyalpha-kernel/domain"},
    "onlyalpha-integration-contract": {"path": "../onlyalpha-integration-contract"},
    "onlyalpha-market-data-construction": {"path": "../../crates/onlyalpha-kernel/market_data/construction"},
    "onlyalpha-metadata-json": {"path": "../onlyalpha-metadata-json"},
    "onlyalpha-strategy": {"path": "../../crates/onlyalpha-kernel/strategy"},
    "reqwest": {"default-features": False, "features": ["rustls"], "version": "=0.13.5"},
    "rustix": {"default-features": False, "features": ["std", "fs", "process"], "version": "=1.1.5"},
    "serde": {"default-features": False, "features": ["std"], "version": "=1.0.229"},
    "serde_json": {
        "default-features": False,
        "features": ["std", "arbitrary_precision", "raw_value"],
        "version": "=1.0.154",
    },
    "sha2": {"default-features": False, "features": ["zeroize"], "version": "=0.11.1"},
    "subtle": {"default-features": False, "version": "=2.6.1"},
    "tokio": {"default-features": False, "features": ["rt", "sync", "time", "macros"], "version": "=1.54.1"},
    "tokio-postgres": {"default-features": False, "features": ["runtime"], "version": "=0.7.18"},
    "zeroize": {"default-features": False, "features": ["alloc"], "version": "=1.9.1"},
}
PRODUCT_RUNTIME_TEST_DEPENDENCIES: dict[str, object] = {}


HTTP_SERVER_DEPENDENCIES = {
    "tokio-postgres": {"version": "=0.7.18", "default-features": False, "features": ["runtime"]},
    "zeroize": {"version": "=1.9.1", "default-features": False, "features": ["alloc"]},
    "httparse": {"version": "=1.10.1", "default-features": False, "features": ["std"]},
    "onlyalpha-product-runtime": {"path": "../onlyalpha-product-runtime"},
    "onlyalpha-integration-contract": {"path": "../onlyalpha-integration-contract"},
    "http": {"version": "=1.5.0", "default-features": False, "features": ["std"]},
    "rustix": {"version": "=1.1.5", "default-features": False, "features": ["std", "fs", "process"]},
    "serde": {"version": "=1.0.229", "default-features": False, "features": ["std", "derive"]},
    "serde_json": {
        "version": "=1.0.154",
        "default-features": False,
        "features": ["std", "arbitrary_precision", "raw_value"],
    },
    "sha2": {"version": "=0.11.1", "default-features": False},
    "subtle": {"version": "=2.6.1", "default-features": False},
    "axum": {"version": "=0.8.9", "default-features": False, "features": ["json"]},
    "hyper": {"version": "=1.12.0", "default-features": False, "features": ["http1", "server"]},
    "hyper-util": {"version": "=0.1.21", "default-features": False, "features": ["tokio", "service"]},
    "tokio": {
        "version": "=1.54.1",
        "default-features": False,
        "features": ["rt", "net", "io-util", "sync", "time", "macros", "signal"],
    },
    "percent-encoding": {"version": "=2.3.2", "default-features": False, "features": ["std"]},
    "getrandom": {"version": "=0.4.3", "default-features": False},
}
HTTP_SERVER_DEPENDENCIES.update({
    "onlyalpha-domain": {"path": "../../crates/onlyalpha-kernel/domain"},
    "onlyalpha-market-data-construction": {"path": "../../crates/onlyalpha-kernel/market_data/construction"},
    "onlyalpha-metadata-json": {"path": "../onlyalpha-metadata-json"},
    "onlyalpha-calculation-worker": {"path": "../onlyalpha-calculation-worker"},
    "onlyalpha-plugin-binance": {"path": "../../plugs/onlyalpha-plugin-binance"},
    "onlyalpha-plugin-tushare": {"path": "../../plugs/onlyalpha-plugin-tushare"},
    "futures-util": {"version": "=0.3.34", "default-features": False, "features": ["sink", "std"]},
    "tokio-tungstenite": {"version": "=0.30.0", "default-features": False, "features": ["handshake"]},
    "utoipa": {"version": "=6.0.0", "default-features": False, "features": ["macros"]},
    "utoipa-axum": {"version": "=0.3.0", "default-features": False},
})
HTTP_SERVER_TEST_DEPENDENCIES = {
    "hyper": {"version": "=1.12.0", "default-features": False, "features": ["http1", "client"]},
    "tokio": {"version": "=1.54.1", "default-features": False, "features": ["test-util"]},
}


def validate_workspace(root: Path) -> None:
    modules = {
        "onlyalpha-plugin-binance": "plugs/onlyalpha-plugin-binance",
        "onlyalpha-plugin-tushare": "plugs/onlyalpha-plugin-tushare",
        "onlyalpha-domain": "crates/onlyalpha-kernel/domain",
        "onlyalpha-calculation": "crates/onlyalpha-kernel/calculation",
        "onlyalpha-gateway-protocol": "packages/onlyalpha-gateway-protocol",
        "onlyalpha-calculation-worker": "packages/onlyalpha-calculation-worker",
        "onlyalpha-runtime-persistence": "packages/onlyalpha-runtime-persistence",
        "onlyalpha-backtest-driver": "packages/onlyalpha-backtest-driver",
        "onlyalpha-product-runtime": "packages/onlyalpha-product-runtime",
        "onlyalpha-metadata-json": "packages/onlyalpha-metadata-json",
        "onlyalpha-integration-contract": "packages/onlyalpha-integration-contract",
        "onlyalpha-http-server": "packages/onlyalpha-http-server",
        "onlyalpha-kernel": "crates/onlyalpha-kernel/core",
        "onlyalpha-clock": "crates/onlyalpha-kernel/clock",
        "onlyalpha-event": "crates/onlyalpha-kernel/event",
        "onlyalpha-strategy": "crates/onlyalpha-kernel/strategy",
        "onlyalpha-order": "crates/onlyalpha-kernel/order",
        "onlyalpha-position": "crates/onlyalpha-kernel/position",
        "onlyalpha-account": "crates/onlyalpha-kernel/account",
        "onlyalpha-strategy-ledger": "crates/onlyalpha-kernel/strategy_ledger",
        "onlyalpha-risk": "crates/onlyalpha-kernel/risk",
        "onlyalpha-execution": "crates/onlyalpha-kernel/execution",
        "onlyalpha-broker": "crates/onlyalpha-kernel/broker",
        "onlyalpha-fee": "crates/onlyalpha-kernel/fee",
        "onlyalpha-settlement": "crates/onlyalpha-kernel/settlement",
        "onlyalpha-margin": "crates/onlyalpha-kernel/margin",
        "onlyalpha-market-data-state": "crates/onlyalpha-kernel/market_data/state",
        "onlyalpha-market-data-construction": "crates/onlyalpha-kernel/market_data/construction",
        "onlyalpha-market-data-delivery": "crates/onlyalpha-kernel/market_data/delivery",
        "onlyalpha-market-data-pipeline": "crates/onlyalpha-kernel/market_data/pipeline",
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
    driver = tomllib.loads((root / modules["onlyalpha-backtest-driver"] / "Cargo.toml").read_text())
    if registry and (
        driver.get("dependencies") != BACKTEST_DRIVER_DEPENDENCIES
        or driver.get("dev-dependencies") != BACKTEST_DRIVER_TEST_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    for name, dependencies, test_dependencies in (
        ("onlyalpha-plugin-binance", BINANCE_DEPENDENCIES, BINANCE_TEST_DEPENDENCIES),
        ("onlyalpha-plugin-tushare", SOURCE_AUTHORING_DEPENDENCIES, {}),
        ("onlyalpha-metadata-json", METADATA_JSON_DEPENDENCIES, {}),
        ("onlyalpha-integration-contract", INTEGRATION_CONTRACT_DEPENDENCIES, {}),
    ):
        manifest = tomllib.loads((root / modules[name] / "Cargo.toml").read_text())
        if registry and (
            manifest.get("dependencies") != dependencies
            or manifest.get("dev-dependencies", {}) != test_dependencies
            or manifest.get("build-dependencies", {})
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    product = tomllib.loads((root / modules["onlyalpha-product-runtime"] / "Cargo.toml").read_text())
    if registry and (
        product.get("dependencies") != PRODUCT_RUNTIME_DEPENDENCIES
        or product.get("dev-dependencies", {}) != PRODUCT_RUNTIME_TEST_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    http_server = tomllib.loads((root / modules["onlyalpha-http-server"] / "Cargo.toml").read_text())
    if registry and (
        http_server.get("dependencies") != HTTP_SERVER_DEPENDENCIES
        or http_server.get("dev-dependencies") != HTTP_SERVER_TEST_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
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
                    admitted = admitted or (
                        name == "onlyalpha-market-data-construction"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == CONSTRUCTION_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-market-data-delivery"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == DELIVERY_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-calculation"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == CALCULATION_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name in {"onlyalpha-gateway-protocol", "onlyalpha-calculation-worker"}
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config
                        == (PROTOCOL_DEPENDENCIES if name == "onlyalpha-gateway-protocol" else WORKER_DEPENDENCIES).get(
                            alias
                        )
                    )
                    admitted = admitted or (
                        name == "onlyalpha-market-data-pipeline"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == PIPELINE_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-account"
                        and section is manifest
                        and kind == "dependencies"
                        and alias in {"onlyalpha-margin", "onlyalpha-position"}
                        and dependency == alias
                        and config == {"path": "../" + alias.removeprefix("onlyalpha-")}
                    )
                    admitted = admitted or (
                        name == "onlyalpha-strategy"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == STRATEGY_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name
                        in {
                            "onlyalpha-order",
                            "onlyalpha-position",
                            "onlyalpha-account",
                            "onlyalpha-strategy-ledger",
                            "onlyalpha-risk",
                            "onlyalpha-margin",
                        }
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == ORDER_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-execution"
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == EXECUTION_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name in {"onlyalpha-broker", "onlyalpha-fee", "onlyalpha-settlement"}
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config == BROKER_DEPENDENCIES.get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-execution"
                        and section is manifest
                        and kind == "dev-dependencies"
                        and alias == dependency == "onlyalpha-broker"
                        and config == {"path": "../broker"}
                    )
                    admitted = admitted or (
                        name == "onlyalpha-runtime-persistence"
                        and section is manifest
                        and kind in {"dependencies", "dev-dependencies"}
                        and alias == dependency
                        and config
                        == (
                            RUNTIME_PERSISTENCE_DEPENDENCIES
                            if kind == "dependencies"
                            else RUNTIME_PERSISTENCE_TEST_DEPENDENCIES
                        ).get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-backtest-driver"
                        and section is manifest
                        and kind in {"dependencies", "dev-dependencies"}
                        and alias == dependency
                        and config
                        == (
                            BACKTEST_DRIVER_DEPENDENCIES
                            if kind == "dependencies"
                            else BACKTEST_DRIVER_TEST_DEPENDENCIES
                        ).get(alias)
                    )
                    admitted = admitted or (
                        name in {"onlyalpha-metadata-json", "onlyalpha-integration-contract"}
                        and section is manifest
                        and kind == "dependencies"
                        and alias == dependency
                        and config
                        == (
                            METADATA_JSON_DEPENDENCIES
                            if name == "onlyalpha-metadata-json"
                            else INTEGRATION_CONTRACT_DEPENDENCIES
                        ).get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-product-runtime"
                        and section is manifest
                        and kind in {"dependencies", "dev-dependencies"}
                        and alias == dependency
                        and config
                        == (
                            PRODUCT_RUNTIME_DEPENDENCIES
                            if kind == "dependencies"
                            else PRODUCT_RUNTIME_TEST_DEPENDENCIES
                        ).get(alias)
                    )
                    admitted = admitted or (
                        name == "onlyalpha-http-server"
                        and section is manifest
                        and kind in {"dependencies", "dev-dependencies"}
                        and alias == dependency
                        and config
                        == (HTTP_SERVER_DEPENDENCIES if kind == "dependencies" else HTTP_SERVER_TEST_DEPENDENCIES).get(
                            alias
                        )
                    )
                    admitted = admitted or (
                        name in {"onlyalpha-plugin-binance", "onlyalpha-plugin-tushare"}
                        and section is manifest
                        and kind in {"dependencies", "dev-dependencies"}
                        and alias == dependency
                        and config
                        == (
                            (BINANCE_DEPENDENCIES if kind == "dependencies" else BINANCE_TEST_DEPENDENCIES)
                            if name == "onlyalpha-plugin-binance"
                            else (SOURCE_AUTHORING_DEPENDENCIES if kind == "dependencies" else {})
                        ).get(alias)
                    )
                    if not admitted:
                        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if (
        registry
        and tomllib.loads((root / modules["onlyalpha-position"] / "Cargo.toml").read_text()).get("dependencies")
        != POSITION_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if registry and tomllib.loads((root / modules["onlyalpha-account"] / "Cargo.toml").read_text()).get(
        "dependencies"
    ) != {
        **ACCOUNT_DEPENDENCIES,
        "onlyalpha-margin": {"path": "../margin"},
        "onlyalpha-position": {"path": "../position"},
    }:
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if (
        registry
        and tomllib.loads((root / modules["onlyalpha-strategy-ledger"] / "Cargo.toml").read_text()).get("dependencies")
        != ACCOUNT_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if (
        registry
        and tomllib.loads((root / modules["onlyalpha-risk"] / "Cargo.toml").read_text()).get("dependencies")
        != ACCOUNT_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if (
        registry
        and tomllib.loads((root / modules["onlyalpha-execution"] / "Cargo.toml").read_text()).get("dependencies")
        != EXECUTION_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if (
        registry
        and tomllib.loads((root / modules["onlyalpha-broker"] / "Cargo.toml").read_text()).get("dependencies")
        != BROKER_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if (
        registry
        and tomllib.loads((root / modules["onlyalpha-fee"] / "Cargo.toml").read_text()).get("dependencies")
        != BROKER_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if (
        registry
        and tomllib.loads((root / modules["onlyalpha-settlement"] / "Cargo.toml").read_text()).get("dependencies")
        != BROKER_DEPENDENCIES
    ):
        raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
    if (
        registry
        and tomllib.loads((root / modules["onlyalpha-margin"] / "Cargo.toml").read_text()).get("dependencies")
        != ACCOUNT_DEPENDENCIES
    ):
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

        construction = tomllib.loads((root / modules["onlyalpha-market-data-construction"] / "Cargo.toml").read_text())
        if construction.get("dependencies") != CONSTRUCTION_DEPENDENCIES:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

        delivery = tomllib.loads((root / modules["onlyalpha-market-data-delivery"] / "Cargo.toml").read_text())
        if delivery.get("dependencies") != DELIVERY_DEPENDENCIES:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

        pipeline = tomllib.loads((root / modules["onlyalpha-market-data-pipeline"] / "Cargo.toml").read_text())
        if pipeline.get("dependencies") != PIPELINE_DEPENDENCIES:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

        strategy = tomllib.loads((root / modules["onlyalpha-strategy"] / "Cargo.toml").read_text())
        if strategy.get("dependencies") != STRATEGY_DEPENDENCIES:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

        if (
            tomllib.loads((root / modules["onlyalpha-order"] / "Cargo.toml").read_text()).get("dependencies")
            != ORDER_DEPENDENCIES
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

        for component, dependencies in (
            ("onlyalpha-gateway-protocol", PROTOCOL_DEPENDENCIES),
            ("onlyalpha-calculation-worker", WORKER_DEPENDENCIES),
        ):
            component_manifest = tomllib.loads((root / modules[component] / "Cargo.toml").read_text())
            if component_manifest.get("dependencies") != dependencies:
                raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        protocol = tomllib.loads((root / modules["onlyalpha-gateway-protocol"] / "Cargo.toml").read_text())
        if protocol.get("features") != {"codegen": ["dep:prost-build", "dep:prost-types"]}:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

        calculation = tomllib.loads((root / modules["onlyalpha-calculation"] / "Cargo.toml").read_text())
        if calculation.get("dependencies") != CALCULATION_DEPENDENCIES:
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def prepare_cargo_home(registry: Path, home: Path) -> None:
    """Seed offline builds from the admitted immutable dev image, not a mutable prior cache."""
    if home.is_symlink() or not registry.is_dir() or registry.is_symlink():
        raise ValueError("RUST_KERNEL_CARGO_HOME_NOT_ADMITTED")
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    shutil.copytree(registry, home / "registry")


_PURE_INPUT_PATTERN = r"\b(?:SystemTime|Instant|UNIX_EPOCH|Condvar|thread|sleep|new_v4|new_v7|random|File|TcpStream|UdpSocket|Command|getrandom)\b|\bstd\s*::\s*(?:time|fs|net|process|env|io)\b|\buse\s+std\s*::\s*\{[^;]*\b(?:time|fs|net|process|env|io)\b"


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
            _PURE_INPUT_PATTERN,
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
        "market_data/state",
        {
            '"../../../../../test-data/market-data-state/operations-v1.jsonl"',
            '"../../../../../test-data/market-data-state/records-v2.jsonl"',
        },
    )
    for path in (root / "crates/onlyalpha-kernel/market_data/state/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?:clock|event|kernel|runtime|indicator|factor|provider|storage)\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_construction_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "market_data/construction",
        {
            '"../../../../../test-data/market-data-construction/models-v1.jsonl"',
            '"../../../../../test-data/market-data-construction/operations-v1.jsonl"',
        },
    )
    for path in (root / "crates/onlyalpha-kernel/market_data/construction/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(
            r"\bonlyalpha_(?:clock|event|market_data_state|kernel|core|runtime|indicator|factor|calculation|provider|storage)\b",
            code,
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_delivery_sources(root: Path) -> None:
    _validate_pure_sources(
        root, "market_data/delivery", {'"../../../../../test-data/market-data-delivery/routing-v1.jsonl"'}
    )
    for path in (root / "crates/onlyalpha-kernel/market_data/delivery/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(
            r"\bonlyalpha_(?:clock|event|kernel|core|runtime|cluster|strategy|indicator|factor|calculation|provider|storage)\b",
            code,
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_pipeline_sources(root: Path) -> None:
    _validate_pure_sources(
        root, "market_data/pipeline", {'"../../../../../test-data/market-data-pipeline/operations-v1.jsonl"'}
    )
    for path in (root / "crates/onlyalpha-kernel/market_data/pipeline/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(
            r"\bonlyalpha_(?:clock|event|kernel|core|runtime|cluster|strategy|indicator|factor|provider|storage|calculation_worker|gateway_protocol)\b",
            code,
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_strategy_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "strategy",
        {
            '"../../../../test-data/strategy/decisions-v2.jsonl"',
            '"../../../../test-data/strategy/product-sources-v1.jsonl"',
        },
    )
    for path in (root / "crates/onlyalpha-kernel/strategy/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(
            r"\bonlyalpha_(?:clock|event|kernel|core|runtime|cluster|provider|storage|calculation_worker|gateway_protocol|market_data_pipeline|market_data_state|market_data_delivery)\b",
            code,
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_order_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "order",
        {'"../../../../test-data/order/domain-inputs.json"', '"../../../../test-data/order/lifecycle-v1.jsonl"'},
    )
    for path in (root / "crates/onlyalpha-kernel/order/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_position_sources(root: Path) -> None:
    _validate_pure_sources(root, "position", {'"../../../../test-data/position/lifecycle-v1.jsonl"'})
    for path in (root / "crates/onlyalpha-kernel/position/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_account_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "account",
        {
            '"../../../../test-data/account/cash-v1.jsonl"',
            '"../../../../test-data/margin/common-v1.json"',
            '"../../../../test-data/account/performance-v1.jsonl"',
        },
    )
    for path in (root / "crates/onlyalpha-kernel/account/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b|margin\b|position\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_strategy_ledger_sources(root: Path) -> None:
    _validate_pure_sources(root, "strategy_ledger", {'"../../../../test-data/strategy-ledger/valuation-v1.jsonl"'})
    for path in (root / "crates/onlyalpha-kernel/strategy_ledger/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_risk_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "risk",
        {'"../../../../test-data/risk/decisions-v1.jsonl"', '"../../../../test-data/risk/reservations-v1.jsonl"'},
    )
    for path in (root / "crates/onlyalpha-kernel/risk/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_broker_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "broker",
        {'"../../../../test-data/broker/domain-inputs.json"', '"../../../../test-data/broker/virtual-v2.json"'},
    )
    for path in (root / "crates/onlyalpha-kernel/broker/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_fee_sources(root: Path) -> None:
    _validate_pure_sources(root, "fee", {'"../../../../test-data/fee/common-v1.json"'})
    for path in (root / "crates/onlyalpha-kernel/fee/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_settlement_sources(root: Path) -> None:
    _validate_pure_sources(root, "settlement", {'"../../../../test-data/settlement/common-v1.json"'})
    for path in (root / "crates/onlyalpha-kernel/settlement/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_margin_sources(root: Path) -> None:
    _validate_pure_sources(root, "margin", {'"../../../../test-data/margin/common-v1.json"'})
    for path in (root / "crates/onlyalpha-kernel/margin/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(r"\bonlyalpha_(?!domain\b)[a-z_]+\b", code):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_execution_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "execution",
        {
            '"../../../../test-data/execution/domain-inputs.json"',
            '"../../../../test-data/execution/economics-v1.json"',
            '"../../../../test-data/settlement/common-v1.json"',
            '"../../../../test-data/margin/common-v1.json"',
            '"../../../../test-data/position/valuation-order-contract.json"',
            '"../../../../test-data/execution/reconciliation-v1.jsonl"',
            '"../../../../test-data/execution/backtest-result-v1.jsonl"',
        },
    )
    for path in (root / "crates/onlyalpha-kernel/execution/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(
            r"\bonlyalpha_(?!domain\b|order\b|position\b|account\b|strategy_ledger\b|risk\b|fee\b|settlement\b|margin\b)[a-z_]+\b",
            code,
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_calculation_sources(root: Path) -> None:
    _validate_pure_sources(
        root,
        "calculation",
        {
            '"../../../../test-data/calculation/definitions-v1.jsonl"',
            '"../../../../test-data/calculation/product-readers-v1.jsonl"',
            '"../../../../test-data/calculation/parameters-v1.jsonl"',
            '"../../../../test-data/calculation/state-v1.jsonl"',
        },
    )
    for path in (root / "crates/onlyalpha-kernel/calculation/src").rglob("*.rs"):
        code = re.sub(r"(?m)^\s*//.*$", "", path.read_text())
        if re.search(
            r"\bonlyalpha_(?:clock|event|kernel|core|domain|runtime|cluster|strategy|indicator|factor|market_data|provider|storage)\b",
            code,
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def validate_infrastructure_sources(root: Path) -> None:
    for component in (
        "onlyalpha-gateway-protocol",
        "onlyalpha-calculation-worker",
        "onlyalpha-runtime-persistence",
        "onlyalpha-backtest-driver",
        "onlyalpha-product-runtime",
        "onlyalpha-metadata-json",
        "onlyalpha-integration-contract",
        "onlyalpha-http-server",
    ):
        area = root / "packages" / component
        manifest = tomllib.loads((area / "Cargo.toml").read_text())
        if (
            (area / "build.rs").exists()
            or manifest.get("package", {}).get("build", False) is not False
            or manifest.get("lib") != {"path": "rust/lib.rs"}
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        sources = (
            area / "rust"
            if component
            in {
                "onlyalpha-runtime-persistence",
                "onlyalpha-backtest-driver",
                "onlyalpha-product-runtime",
                "onlyalpha-metadata-json",
                "onlyalpha-integration-contract",
                "onlyalpha-http-server",
            }
            else area
        )
        for path in sources.rglob("*.rs"):
            text = path.read_text()
            if component == "onlyalpha-backtest-driver" and path == sources / "main.rs":
                # This value is already a pinned input in Cargo.toml/Cargo.lock.
                text = text.replace('env!("CARGO_PKG_VERSION")', '"declared-package-version"')
            if (
                path.is_symlink()
                or _hidden_rust_input(text)
                or re.search(r"\binclude_(?:str|bytes)\s*!", path.read_text())
            ):
                raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
            if component in {"onlyalpha-metadata-json", "onlyalpha-integration-contract"} and re.search(
                _PURE_INPUT_PATTERN, re.sub(r"(?m)^\s*//.*$", "", text)
            ):
                raise ValueError("RUST_MODULE_BOUNDARY_INVALID")

    for component in ("onlyalpha-plugin-binance", "onlyalpha-plugin-tushare"):
        area = root / "plugs" / component
        manifest = tomllib.loads((area / "Cargo.toml").read_text())
        if (
            (area / "build.rs").exists()
            or manifest.get("package", {}).get("build", False) is not False
            or manifest.get("lib") != {"path": "rust/lib.rs"}
        ):
            raise ValueError("RUST_MODULE_BOUNDARY_INVALID")
        for path in (area / "rust").rglob("*.rs"):
            text = path.read_text()
            if (
                path.is_symlink()
                or _hidden_rust_input(text)
                or re.search(r"\binclude_(?:str|bytes)\s*!", text)
                or re.search(
                    (
                        r"\b(?:SystemTime|UNIX_EPOCH|File|Command)\b|\bstd\s*::\s*(?:fs|process|env)\b|\buse\s+std\s*::\s*\{[^;]*\b(?:fs|process|env)\b"
                        if component == "onlyalpha-plugin-binance"
                        and path in {area / "rust/spot_rest.rs", area / "rust/spot_source.rs"}
                        else _PURE_INPUT_PATTERN
                    ),
                    re.sub(r"(?m)^\s*//.*$", "", text),
                )
            ):
                raise ValueError("RUST_MODULE_BOUNDARY_INVALID")


def module_directory(module: str) -> str:
    return "market_data/" + module.removeprefix("market_data_") if module.startswith("market_data_") else module


def module_path(module: str) -> Path:
    if module in {"plugin_binance", "plugin_tushare"}:
        return Path("plugs") / ("onlyalpha-" + module.replace("_", "-"))
    if module in {
        "gateway_protocol",
        "calculation_worker",
        "runtime_persistence",
        "backtest_driver",
        "product_runtime",
        "metadata_json",
        "integration_contract",
        "http_server",
    }:
        return Path("packages") / ("onlyalpha-" + module.replace("_", "-"))
    return Path("crates/onlyalpha-kernel") / module_directory(module)


def _isolated_modules(root: Path, destination: Path, modules: tuple[str, ...]) -> Path:
    destination.mkdir(parents=True)
    for module in modules:
        relative = module_path(module)
        if module in {"http_server", "plugin_binance", "plugin_tushare"}:
            area = destination / relative
            area.mkdir(parents=True)
            shutil.copyfile(root / relative / "Cargo.toml", area / "Cargo.toml")
            shutil.copytree(root / relative / "rust", area / "rust")
            if module == "http_server":
                (area / "tests/support").mkdir(parents=True)
                for support in ("integration_http_probe.rs", "http.rs"):
                    shutil.copyfile(root / relative / "tests/support" / support, area / "tests/support" / support)
            (area / "tests").mkdir(exist_ok=True)
            for test in sorted((root / relative / "tests").glob("*.rs")):
                shutil.copyfile(test, area / "tests" / test.name)
        else:
            shutil.copytree(root / relative, destination / relative)
        data = Path("test-data") / module.replace("_", "-")
        if module not in {
            "gateway_protocol",
            "calculation_worker",
            "runtime_persistence",
            "backtest_driver",
            "product_runtime",
            "metadata_json",
            "integration_contract",
            "http_server",
            "plugin_binance",
            "plugin_tushare",
        }:
            shutil.copytree(root / data, destination / data)
    members = [str(module_path(module)) for module in modules]
    manifest = re.sub(
        r"(?ms)^members\s*=\s*\[[^\]]*\]",
        "members = " + json.dumps(members),
        (root / "Cargo.toml").read_text(),
        count=1,
    )
    (destination / "Cargo.toml").write_text(manifest)
    shutil.copyfile(root / "rust-toolchain.toml", destination / "rust-toolchain.toml")
    chunks = (root / "Cargo.lock").read_text().split("\n[[package]]\n")
    packages = [tomllib.loads("[[package]]\n" + chunk)["package"][0] for chunk in chunks[1:]]
    roots = {"onlyalpha-" + module.replace("_", "-") for module in modules}
    selected = {index for index, package in enumerate(packages) if package["name"] in roots}

    def dependency_index(reference: str) -> int:
        parts = reference.split()
        matches = [
            index
            for index, package in enumerate(packages)
            if package["name"] == parts[0]
            and (len(parts) < 2 or package["version"] == parts[1])
            and (len(parts) < 3 or package.get("source") == parts[2].removeprefix("(").removesuffix(")"))
        ]
        if len(parts) > 3 or len(matches) != 1:
            raise ValueError("RUST_ISOLATED_LOCK_DEPENDENCY_AMBIGUOUS")
        return matches[0]

    pending = list(selected)
    while pending:
        index = pending.pop()
        for reference in packages[index].get("dependencies", []):
            dependency = dependency_index(reference)
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    retained = []
    for index in sorted(selected):
        package = packages[index]
        chunk = chunks[index + 1]
        for reference in package.get("dependencies", []):
            dependency = packages[dependency_index(reference)]
            same_name = [packages[i] for i in selected if packages[i]["name"] == dependency["name"]]
            spelling = dependency["name"]
            if len(same_name) > 1:
                spelling += " " + dependency["version"]
                if sum(item["version"] == dependency["version"] for item in same_name) > 1:
                    spelling += " (" + dependency["source"] + ")"
            chunk = chunk.replace(' "' + reference + '",', ' "' + spelling + '",')
        retained.append(chunk)
    (destination / "Cargo.lock").write_text(chunks[0] + "".join("\n[[package]]\n" + chunk for chunk in retained))
    return destination / "Cargo.toml"


def prepare_isolated_lock(manifest: Path, env: Mapping[str, str]) -> None:
    """Let Cargo shrink feature edges, without admitting any unreviewed lock input."""
    lock = manifest.with_name("Cargo.lock")
    original = lock.read_bytes()

    def graph(
        raw: bytes,
    ) -> tuple[
        dict[str, Any],
        dict[tuple[str, str, str | None], dict[str, Any]],
        dict[tuple[str, str, str | None], set[tuple[str, str, str | None]]],
    ]:
        data = tomllib.loads(raw.decode("utf-8"))
        packages = data.pop("package")
        records = {}
        for package in packages:
            identity = (package["name"], package["version"], package.get("source"))
            if identity in records:
                raise ValueError("duplicate package")
            records[identity] = package
        edges = {}
        for identity, package in records.items():
            dependencies = set()
            for reference in package.get("dependencies", []):
                parts = reference.split()
                matches = [
                    key
                    for key in records
                    if key[0] == parts[0]
                    and (len(parts) < 2 or key[1] == parts[1])
                    and (len(parts) < 3 or key[2] == parts[2].removeprefix("(").removesuffix(")"))
                ]
                if len(parts) > 3 or len(matches) != 1 or matches[0] in dependencies:
                    raise ValueError("invalid dependency")
                dependencies.add(matches[0])
            edges[identity] = dependencies
        return data, records, edges

    try:
        old_header, old_records, old_edges = graph(original)
        subprocess.run(
            # Resolve from the existing lock. generate-lockfile discards pinned
            # versions and cannot retain a subsequently yanked reviewed release.
            ["cargo", "metadata", "--offline", "--format-version", "1", "--manifest-path", str(manifest)],
            cwd=manifest.parent,
            env=env,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        new_header, new_records, new_edges = graph(lock.read_bytes())
        if new_header != old_header or any(key not in new_records for key in old_records if key[2] is None):
            raise ValueError("changed workspace input")
        for identity, package in new_records.items():
            previous = old_records.get(identity)
            if (
                previous is None
                or (
                    {key: value for key, value in package.items() if key != "dependencies"}
                    != {key: value for key, value in previous.items() if key != "dependencies"}
                )
                or not new_edges[identity] <= old_edges[identity]
            ):
                raise ValueError("changed dependency input")
    except Exception as error:
        lock.write_bytes(original)
        raise ValueError("RUST_ISOLATED_LOCK_CHANGED") from error


def isolated_metadata_json(root: Path, destination: Path) -> Path:
    """Pure shared metadata codec without Product, Domain or process access."""
    return _isolated_modules(root, destination, ("metadata_json",))


def isolated_integration_contract(root: Path, destination: Path) -> Path:
    """Public SPI with only pure exact-number/metadata dependencies."""
    return _isolated_modules(
        root, destination, ("domain", "market_data_construction", "metadata_json", "integration_contract")
    )


def isolated_plugin_binance(root: Path, destination: Path) -> Path:
    return _isolated_modules(
        root,
        destination,
        ("domain", "market_data_construction", "metadata_json", "integration_contract", "plugin_binance"),
    )


def isolated_plugin_tushare(root: Path, destination: Path) -> Path:
    return _isolated_modules(
        root,
        destination,
        ("domain", "market_data_construction", "metadata_json", "integration_contract", "plugin_tushare"),
    )


def isolated_product_runtime(root: Path, destination: Path) -> Path:
    """Product owner with declared immutable Strategy and PostgreSQL dependencies."""
    return _isolated_modules(
        root,
        destination,
        (
            "domain",
            "calculation",
            "market_data_construction",
            "strategy",
            "metadata_json",
            "integration_contract",
            "event",
            "market_data_state",
            "market_data_delivery",
            "market_data_pipeline",
            "gateway_protocol",
            "calculation_worker",
            "product_runtime",
        ),
    )


def isolated_http_server(root: Path, destination: Path) -> Path:
    """Native ingress uses only its declared Product/Strategy closure."""
    return _isolated_modules(
        root,
        destination,
        (
            "domain",
            "calculation",
            "market_data_construction",
            "strategy",
            "metadata_json",
            "integration_contract",
            "event",
            "market_data_state",
            "market_data_delivery",
            "market_data_pipeline",
            "gateway_protocol",
            "calculation_worker",
            "product_runtime",
            "http_server",
        ),
    )


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


def isolated_construction(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "market_data_construction"))


def isolated_delivery(root: Path, destination: Path) -> Path:
    return _isolated_modules(
        root, destination, ("domain", "market_data_state", "market_data_construction", "market_data_delivery")
    )


def isolated_calculation(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("calculation",))


def isolated_order(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "order"))


def isolated_position(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "position"))


def isolated_account(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "position", "margin", "account"))


def isolated_broker(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "broker"))


def isolated_fee(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "fee"))


def isolated_settlement(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "settlement"))


def isolated_margin(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "margin"))


def isolated_execution(root: Path, destination: Path) -> Path:
    return _isolated_modules(
        root,
        destination,
        (
            "domain",
            "order",
            "position",
            "account",
            "strategy_ledger",
            "risk",
            "broker",
            "fee",
            "settlement",
            "margin",
            "execution",
        ),
    )


def isolated_runtime_persistence(root: Path, destination: Path) -> Path:
    return _isolated_modules(
        root,
        destination,
        (
            "domain",
            "order",
            "position",
            "account",
            "strategy_ledger",
            "risk",
            "broker",
            "fee",
            "settlement",
            "margin",
            "execution",
            "runtime_persistence",
        ),
    )


def isolated_backtest_driver(root: Path, destination: Path) -> Path:
    return _isolated_modules(
        root,
        destination,
        (
            "domain",
            "clock",
            "order",
            "position",
            "account",
            "strategy_ledger",
            "risk",
            "broker",
            "fee",
            "settlement",
            "margin",
            "execution",
            "runtime_persistence",
            "calculation",
            "market_data_construction",
            "market_data_state",
            "market_data_delivery",
            "market_data_pipeline",
            "strategy",
            "gateway_protocol",
            "calculation_worker",
            "backtest_driver",
        ),
    )


def isolated_risk(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "risk"))


def isolated_strategy_ledger(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "strategy_ledger"))


def isolated_strategy(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("domain", "calculation", "market_data_construction", "strategy"))


def isolated_gateway_protocol(root: Path, destination: Path) -> Path:
    return _isolated_modules(root, destination, ("gateway_protocol",))


def isolated_pipeline(root: Path, destination: Path) -> Path:
    return _isolated_modules(
        root,
        destination,
        (
            "domain",
            "calculation",
            "market_data_state",
            "market_data_construction",
            "market_data_delivery",
            "market_data_pipeline",
        ),
    )


def isolated_calculation_worker(root: Path, destination: Path) -> Path:
    return _isolated_modules(
        root,
        destination,
        (
            "domain",
            "calculation",
            "market_data_state",
            "market_data_construction",
            "market_data_delivery",
            "market_data_pipeline",
            "strategy",
            "gateway_protocol",
            "calculation_worker",
        ),
    )


def _check_component_reference(
    root: Path,
    env: dict[str, str],
    target: str,
    module: str,
    compare: Callable[[list[dict[str, object]]], None],
) -> None:
    for profile in ([], ["--release"]):
        command = [
            "cargo",
            "test",
            "-p",
            f"onlyalpha-{module}",
            "--test",
            "lifecycle",
            "--target",
            target,
            "--frozen",
            "--offline",
            "-j1",
            *profile,
            "common_vector_outputs",
            "--",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ]
        result = subprocess.run(command, cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout, flush=True)
        result.check_returncode()
        prefix = f"{module.upper()}_VECTOR_OUTPUT "
        rows = [line.split(prefix, 1)[1] for line in result.stdout.splitlines() if prefix in line]
        if len(rows) != 1:
            raise ValueError(f"{module.upper()}_NATIVE_COMPARISON_OUTPUT_MISSING")
        compare(json.loads(rows[0]))
        print(f"{module.upper()}_PYTHON_NATIVE_COMMON_VECTORS_PASS", flush=True)


def check_order_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.order_reference_check import check_fixture, compare_native_outputs

    check_fixture()
    _check_component_reference(root, env, target, "order", compare_native_outputs)


def check_position_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.position_reference_check import compare_native_outputs

    _check_component_reference(root, env, target, "position", compare_native_outputs)


def check_account_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.account_reference_check import compare_native_outputs

    _check_component_reference(root, env, target, "account", compare_native_outputs)


def check_strategy_ledger_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.strategy_ledger_reference_check import compare_native_outputs

    _check_component_reference(root, env, target, "strategy-ledger", compare_native_outputs)


def check_broker_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.broker_reference_check import check_fixture, virtual_corpus

    check_fixture()
    cases = virtual_corpus()
    actual = subprocess.check_output(
        [
            "cargo",
            "run",
            "-p",
            "onlyalpha-broker",
            "--example",
            "identity",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
        ],
        cwd=root,
        env=env,
        text=True,
        input=json.dumps(cases),
    )
    if json.loads(actual) != [{k: case[k] for k in ("identity", "fingerprint")} for case in cases]:
        raise ValueError("BROKER_PYTHON_NATIVE_IDENTITY_CONFLICT")

    subprocess.run(
        [
            "cargo",
            "build",
            "-p",
            "onlyalpha-broker",
            "--example",
            "restart",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
        ],
        cwd=root,
        env=env,
        check=True,
    )
    executable = Path(env["CARGO_TARGET_DIR"]) / target / "debug/examples/restart"
    with tempfile.TemporaryDirectory(prefix="broker-restart-", dir=root / "test-results") as area:
        for cut, expected_calls in ((1, 1), (2, 0), (3, 1), (4, 1)):
            directory = Path(area) / str(cut)
            fixture = root / "test-data/broker/domain-inputs.json"
            interrupted = subprocess.run([str(executable), str(directory), str(cut), str(fixture)], cwd=root, env=env)
            if interrupted.returncode != 77:
                raise ValueError("BROKER_CRASH_CUT_NOT_REACHED")
            subprocess.run([str(executable), str(directory), "0", str(fixture)], cwd=root, env=env, check=True)
            calls = directory / "external-calls"
            observed = len(calls.read_text().splitlines()) if calls.exists() else 0
            if observed != expected_calls:
                raise ValueError("BROKER_CRASH_REPEATED_EXTERNAL_CALL")


def check_fee_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.fee_reference_check import compare_native

    for profile in ([], ["--release"]):
        subprocess.run(
            [
                "cargo",
                "build",
                "-p",
                "onlyalpha-fee",
                "--example",
                "reference",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *profile,
            ],
            cwd=root,
            env=env,
            check=True,
        )
        executable = Path(env["CARGO_TARGET_DIR"]) / target / ("release" if profile else "debug") / "examples/reference"
        compare_native(root, executable)


def check_settlement_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.settlement_reference_check import compare_native

    for profile in ([], ["--release"]):
        subprocess.run(
            [
                "cargo",
                "build",
                "-p",
                "onlyalpha-settlement",
                "--example",
                "reference",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *profile,
            ],
            cwd=root,
            env=env,
            check=True,
        )
        executable = Path(env["CARGO_TARGET_DIR"]) / target / ("release" if profile else "debug") / "examples/reference"
        compare_native(root, executable)


def check_performance_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.performance_reference_check import compare_native

    for profile in ([], ["--release"]):
        result = subprocess.run(
            [
                "cargo",
                "test",
                "-p",
                "onlyalpha-account",
                "--test",
                "performance",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *profile,
                "--",
                "--exact",
                "common_vector_outputs",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            print(result.stdout, result.stderr, flush=True)
            result.check_returncode()
        marker = "PERFORMANCE_VECTOR_OUTPUT "
        rows = [line.split(marker, 1)[1] for line in result.stdout.splitlines() if marker in line]
        if len(rows) != 1:
            raise ValueError("PERFORMANCE_REFERENCE_OUTPUT")
        compare_native(root, json.loads(rows[0]))
    print("PERFORMANCE_PYTHON_NATIVE_COMMON_AND_LITERAL_VECTORS: PASS", flush=True)


def check_backtest_result_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.backtest_result_reference_check import compare_native

    for profile in ([], ["--release"]):
        result = subprocess.run(
            [
                "cargo",
                "test",
                "-p",
                "onlyalpha-execution",
                "--test",
                "backtest_result",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *profile,
                "--",
                "--exact",
                "common_vector_outputs",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            print(result.stdout, result.stderr, flush=True)
            result.check_returncode()
        marker = "BACKTEST_RESULT_VECTOR_OUTPUT "
        rows = [line.split(marker, 1)[1] for line in result.stdout.splitlines() if marker in line]
        if len(rows) != 1:
            raise ValueError("BACKTEST_RESULT_REFERENCE_OUTPUT")
        compare_native(root, json.loads(rows[0]))
    print("BACKTEST_RESULT_PYTHON_COMMON_AND_NATIVE_LITERALS: PASS", flush=True)


def check_reconciliation_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.reconciliation_reference_check import compare_native

    for profile in ([], ["--release"]):
        result = subprocess.run(
            [
                "cargo",
                "test",
                "-p",
                "onlyalpha-execution",
                "--test",
                "reconciliation",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *profile,
                "--",
                "--exact",
                "common_vector_outputs",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            print(result.stdout, result.stderr, flush=True)
            result.check_returncode()
        marker = "RECONCILIATION_VECTOR_OUTPUT "
        rows = [line.split(marker, 1)[1] for line in result.stdout.splitlines() if marker in line]
        if len(rows) != 1:
            raise ValueError("RECONCILIATION_REFERENCE_OUTPUT")
        compare_native(root, json.loads(rows[0]))
    print("RECONCILIATION_PYTHON_NATIVE_COMMON_AND_LITERAL_VECTORS: PASS", flush=True)


def check_valuation_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.valuation_reference_check import compare_native

    data = (root / "test-data/position/valuation-v1.jsonl").read_text()
    for profile in ([], ["--release"]):
        subprocess.run(
            [
                "cargo",
                "build",
                "-p",
                "onlyalpha-position",
                "--example",
                "valuation",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *profile,
            ],
            cwd=root,
            env=env,
            check=True,
        )
        executable = Path(env["CARGO_TARGET_DIR"]) / target / ("release" if profile else "debug") / "examples/valuation"
        result = subprocess.run(
            [str(executable)], input=data, capture_output=True, text=True, cwd=root, env=env, check=True
        )
        compare_native(root, json.loads(result.stdout))
    print("VALUATION_REFERENCE_AND_REPLAY: PASS", flush=True)


def check_margin_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.margin_reference_check import compare_native

    for profile in ([], ["--release"]):
        subprocess.run(
            [
                "cargo",
                "build",
                "-p",
                "onlyalpha-margin",
                "--example",
                "margin_reference",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *profile,
            ],
            cwd=root,
            env=env,
            check=True,
        )
        executable = (
            Path(env["CARGO_TARGET_DIR"]) / target / ("release" if profile else "debug") / "examples/margin_reference"
        )
        compare_native(root, executable)


def check_execution_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.execution_reference_check import check_fixture, compare_native_outputs

    check_fixture()
    for profile in ([], ["--release"]):
        result = subprocess.run(
            [
                "cargo",
                "test",
                "-p",
                "onlyalpha-execution",
                "--test",
                "lifecycle",
                "--frozen",
                "--offline",
                "--target",
                target,
                "-j1",
                *profile,
                "common_reference_outputs",
                "--",
                "--nocapture",
                "--test-threads=1",
            ],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        lines = [
            line.split("EXECUTION_COMMON_JSON ", 1)[1]
            for line in result.stdout.splitlines()
            if "EXECUTION_COMMON_JSON " in line
        ]
        if len(lines) != 1:
            raise ValueError("EXECUTION_NATIVE_REFERENCE_OUTPUT_MISSING")
        compare_native_outputs(json.loads(lines[0]))
        print("EXECUTION_ACTUAL_PYTHON_RUST_COMMON_PASS", profile, flush=True)


def check_risk_reference(root: Path, env: dict[str, str], target: str) -> None:
    from scripts.risk_reference_check import compare_native_outputs

    _check_component_reference(root, env, target, "risk", compare_native_outputs)


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
    validate_construction_sources(ROOT)
    validate_delivery_sources(ROOT)
    validate_calculation_sources(ROOT)
    validate_pipeline_sources(ROOT)
    validate_strategy_sources(ROOT)
    validate_order_sources(ROOT)
    validate_position_sources(ROOT)
    validate_account_sources(ROOT)
    validate_strategy_ledger_sources(ROOT)
    validate_risk_sources(ROOT)
    validate_execution_sources(ROOT)
    validate_broker_sources(ROOT)
    validate_fee_sources(ROOT)
    validate_settlement_sources(ROOT)
    validate_margin_sources(ROOT)
    validate_infrastructure_sources(ROOT)
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    from scripts.backtest_replay_check import replay_environment

    env.update(replay_environment(ROOT, artifacts / "backtest-replay"))
    before = source_inputs(ROOT)
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/gateway_protocol.py"), "check-rust"], cwd=ROOT, env=env, check=True
    )
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
        ("account", isolated_account),
        ("strategy-ledger", isolated_strategy_ledger),
        ("risk", isolated_risk),
        ("execution", isolated_execution),
        ("runtime-persistence", isolated_runtime_persistence),
        ("backtest-driver", isolated_backtest_driver),
        ("metadata-json", isolated_metadata_json),
        ("integration-contract", isolated_integration_contract),
        ("plugin-binance", isolated_plugin_binance),
        ("plugin-tushare", isolated_plugin_tushare),
        ("product-runtime", isolated_product_runtime),
        ("http-server", isolated_http_server),
        ("broker", isolated_broker),
        ("fee", isolated_fee),
        ("settlement", isolated_settlement),
        ("margin", isolated_margin),
        ("position", isolated_position),
        ("order", isolated_order),
        ("strategy", isolated_strategy),
        ("calculation", isolated_calculation),
        ("gateway-protocol", isolated_gateway_protocol),
        ("calculation-worker", isolated_calculation_worker),
        ("market-data-pipeline", isolated_pipeline),
        ("domain", isolated_domain),
        ("clock", isolated_clock),
        ("event", isolated_event),
        ("market-data-state", isolated_market_data_state),
        ("market-data-construction", isolated_construction),
        ("market-data-delivery", isolated_delivery),
    ):
        with tempfile.TemporaryDirectory(prefix=f"{name}-isolated-", dir=artifacts) as directory:
            manifest = materialize(ROOT, Path(directory) / "source")
            isolated_env = dict(env, CARGO_TARGET_DIR=str(Path(directory) / "target"))
            prepare_isolated_lock(manifest, isolated_env)
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
    from scripts.backtest_replay_check import check_replay

    check_replay(ROOT, env, target, artifacts / "backtest-replay")
    check_position_reference(ROOT, env, target)
    check_account_reference(ROOT, env, target)
    check_strategy_ledger_reference(ROOT, env, target)
    check_risk_reference(ROOT, env, target)
    check_execution_reference(ROOT, env, target)
    check_broker_reference(ROOT, env, target)
    check_fee_reference(ROOT, env, target)
    check_settlement_reference(ROOT, env, target)
    check_margin_reference(ROOT, env, target)
    check_valuation_reference(ROOT, env, target)
    check_reconciliation_reference(ROOT, env, target)
    check_performance_reference(ROOT, env, target)
    check_backtest_result_reference(ROOT, env, target)
    check_order_reference(ROOT, env, target)
    subprocess.run([sys.executable, str(ROOT / "scripts/calculation_worker_check.py")], cwd=ROOT, env=env, check=True)
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
    binaries.update(
        {
            f"{profile}_runtime_persistence": digest(
                artifacts / "target" / target / profile / "libonlyalpha_runtime_persistence.rlib"
            )
            for profile in ("debug", "release")
        }
    )
    binaries.update(
        {
            f"{profile}_backtest_driver": digest(
                artifacts / "target" / target / profile / "libonlyalpha_backtest_driver.rlib"
            )
            for profile in ("debug", "release")
        }
    )
    receipt.write_text(
        json.dumps(
            {
                "compiler": compiler,
                "native_build_tools": {
                    tool: {
                        "version": subprocess.check_output(
                            [env[tool], "--version"], cwd=ROOT, env=env, text=True
                        ).strip(),
                        "sha256": digest(Path(env[tool])),
                    }
                    for tool in ("CC", "AR")
                },
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
