from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from onlyalpha.market.product import OnlyCompiledMarketPolicy

PRODUCT_ROOT = Path("src/onlyalpha/market/product")
CORE_ROOT = Path("src/onlyalpha")
GENERIC_ROOT = Path("packages/market/onlyalpha-market-generic-t0-cash/src/onlyalpha_market_generic_t0_cash")
CN_ASHARE_ROOT = Path("packages/market/onlyalpha-market-cn-ashare/src/onlyalpha_market_cn_ashare")
BINANCE_SPOT_ROOT = Path("packages/market/onlyalpha-market-binance-spot/src/onlyalpha_market_binance_spot")
BINANCE_PROVIDER_ROOT = Path("packages/provider/onlyalpha-plugin-binance/src/onlyalpha_plugin_binance")
FORMAL_IDENTITY = Path("src/onlyalpha/identity.py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


def test_market_product_core_contract_has_no_concrete_market_or_runtime_dependency() -> None:
    forbidden_imports = (
        "onlyalpha.market.ashare_rules",
        "onlyalpha.market.profiles",
        "onlyalpha.reference.ashare",
        "onlyalpha.runtime",
        "onlyalpha_plugin_",
    )
    forbidden_tokens = (
        "Ashare",
        "CN_A_SHARE",
        "GENERIC_T0",
        "XSHG",
        "XSHE",
        "OnlyRuntimeMode",
        "OrderManager",
        "PositionManager",
        "AccountManager",
        "RiskManager",
        "ExecutionProcessor",
    )
    violations: list[str] = []
    for path in sorted(PRODUCT_ROOT.glob("*.py")):
        for imported in _imports(path):
            if any(imported == value or imported.startswith(f"{value}.") for value in forbidden_imports):
                violations.append(f"{path}: import {imported}")
        source = path.read_text(encoding="utf-8")
        violations.extend(f"{path}: token {token}" for token in forbidden_tokens if token in source)
    assert not violations


def test_research_does_not_depend_on_trading_market_product_contract() -> None:
    research_root = CORE_ROOT / "runtime" / "research"
    assert all(
        "onlyalpha.market.product" not in path.read_text(encoding="utf-8")
        for path in sorted(research_root.rglob("*.py"))
    )


def test_product_identity_is_not_a_core_behavior_selector() -> None:
    violations: list[str] = []
    for path in sorted(CORE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.Match)):
                continue
            subject = node.test if isinstance(node, ast.If) else node.subject
            if any(
                isinstance(item, ast.Attribute) and item.attr in {"product_id", "product_version"}
                for item in ast.walk(subject)
            ):
                violations.append(f"{path}:{node.lineno}")
    assert not violations


def test_binding_is_an_authority_bundle_not_a_trading_service() -> None:
    tree = ast.parse((PRODUCT_ROOT / "binding.py").read_text(encoding="utf-8"))
    methods = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not methods & {"submit_order", "apply_trade", "update_position", "on_bar", "calculate_pnl"}


def test_canonical_market_ir_excludes_execution_simulation_authorities() -> None:
    names = {field.name for field in fields(OnlyCompiledMarketPolicy)}
    assert not names & {"matching_policy", "slippage_policy", "liquidity_policy"}
    imports = set().union(*(_imports(path) for path in PRODUCT_ROOT.glob("*.py")))
    assert not imports & {
        "onlyalpha.market.models.OnlyMatchingModel",
        "onlyalpha.market.models.OnlySlippageModel",
        "onlyalpha.market.models.OnlyLiquidityModel",
    }


def test_core_does_not_import_concrete_market_product_plugins() -> None:
    violations = [
        f"{path}: import {imported}"
        for path in sorted(CORE_ROOT.rglob("*.py"))
        for imported in _imports(path)
        if any(
            imported == package or imported.startswith(f"{package}.")
            for package in (
                "onlyalpha_market_generic_t0_cash",
                "onlyalpha_market_cn_ashare",
                "onlyalpha_market_binance_spot",
                "onlyalpha_plugin_binance",
            )
        )
    ]
    assert not violations


def test_generic_market_product_has_no_runtime_broker_or_concrete_market_dependency() -> None:
    forbidden_imports = (
        "onlyalpha.runtime",
        "onlyalpha.broker",
        "onlyalpha.risk",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.account",
        "onlyalpha.execution",
        "onlyalpha.transaction",
        "onlyalpha.reference",
        "onlyalpha.market.ashare_rules",
        "onlyalpha.market.profiles",
        "onlyalpha.market.runtime_rules",
    )
    forbidden_tokens = (
        "OnlyRuntimeMode",
        "BACKTEST",
        "RESEARCH",
        "SIM",
        "LIVE",
        "Ashare",
        "CN_A_SHARE",
        "XSHG",
        "XSHE",
        "NEXT_BAR_OPEN",
        "BAR_TOUCH",
        "slippage",
        "fill_schedule",
        "latency",
        "volume_participation",
    )
    violations: list[str] = []
    for path in sorted(GENERIC_ROOT.glob("*.py")):
        imports = _imports(path)
        violations.extend(
            f"{path}: import {imported}"
            for imported in imports
            if any(imported == value or imported.startswith(f"{value}.") for value in forbidden_imports)
        )
        source = path.read_text(encoding="utf-8")
        violations.extend(f"{path}: token {token}" for token in forbidden_tokens if token in source)
    assert not violations


def test_cn_ashare_product_has_no_runtime_or_mutable_trading_authority_dependency() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.broker",
        "onlyalpha.data",
        "onlyalpha.risk",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.account",
        "onlyalpha.execution",
        "onlyalpha.transaction",
        "onlyalpha.reference",
        "onlyalpha.market.runtime_rules",
    )
    violations = [
        f"{path}: import {imported}"
        for path in sorted(CN_ASHARE_ROOT.glob("*.py"))
        for imported in _imports(path)
        if any(imported == item or imported.startswith(f"{item}.") for item in forbidden)
    ]
    assert not violations


def test_binance_packages_do_not_reverse_core_or_cross_trading_boundaries() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.broker",
        "onlyalpha.risk",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.account",
        "onlyalpha.execution",
        "onlyalpha.transaction",
        "onlyalpha.market.runtime_rules",
    )
    violations = [
        f"{path}: import {imported}"
        for root in (BINANCE_SPOT_ROOT, BINANCE_PROVIDER_ROOT)
        for path in sorted(root.rglob("*.py"))
        for imported in _imports(path)
        if any(imported == item or imported.startswith(f"{item}.") for item in forbidden)
    ]
    assert not violations


def test_retired_core_market_authorities_have_zero_active_implementation() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in CORE_ROOT.rglob("*.py"))
    assert "OnlyAshare" not in text
    assert "ashare_rules" not in text
    assert "OnlyMarketProfile" not in text


def test_formal_authority_identity_has_no_magic_serialization_fallback() -> None:
    tree = ast.parse(FORMAL_IDENTITY.read_text(encoding="utf-8"), filename=str(FORMAL_IDENTITY))
    violations = tuple(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "is_dataclass", "str", "Path", "frozenset"}
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in {"to_dict", "__str__"}
        )
    )
    assert not violations


def test_market_product_formal_identities_use_only_the_strict_identity_entrypoint() -> None:
    source = (PRODUCT_ROOT / "identity.py").read_text(encoding="utf-8")
    assert "only_identity_fingerprint" in source
    assert "only_canonical_fingerprint" not in source


def test_market_product_durable_surfaces_have_no_profile_era_spelling() -> None:
    roots = (
        CORE_ROOT / "artifact",
        CORE_ROOT / "collector",
        CORE_ROOT / "execution",
        CORE_ROOT / "fee",
        CORE_ROOT / "result",
        CORE_ROOT / "settlement",
    )
    paths = [path for root in roots for path in root.rglob("*.py")]
    paths.append(CORE_ROOT / "market" / "runtime_rules.py")
    violations = [
        str(path)
        for path in sorted(paths)
        if any(
            token in path.read_text(encoding="utf-8").lower()
            for token in ("market_profile", "profile_timeline", "effective_profile_resolution")
        )
    ]
    assert not violations


def test_market_economic_identity_sources_have_no_runtime_mode_vocabulary() -> None:
    paths = list(PRODUCT_ROOT.glob("*.py"))
    paths.extend(GENERIC_ROOT.glob("*.py"))
    paths.extend(CN_ASHARE_ROOT.glob("*.py"))
    paths.extend(BINANCE_SPOT_ROOT.glob("*.py"))
    violations = [
        f"{path}: {token}"
        for path in sorted(paths)
        for token in ("OnlyRuntimeMode", "runtime_type", "RESEARCH", "BACKTEST", "SIM", "LIVE")
        if token in path.read_text(encoding="utf-8")
    ]
    assert not violations


def test_composition_identity_is_created_only_by_resolved_binding() -> None:
    call_sites = [
        str(path)
        for path in sorted(CORE_ROOT.rglob("*.py"))
        if "OnlyMarketProductCompositionIdentity.create(" in path.read_text(encoding="utf-8")
    ]
    assert call_sites == [str(PRODUCT_ROOT / "binding.py")]
