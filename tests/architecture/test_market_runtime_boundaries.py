from pathlib import Path


def test_runtime_components_do_not_import_market_profiles_or_registry() -> None:
    roots = ("risk", "broker", "execution", "position", "account", "settlement", "margin", "collector")
    forbidden = ("onlyalpha.market.profiles", "onlyalpha.market.registry")
    violations: list[str] = []
    for root in roots:
        for path in sorted((Path("src/onlyalpha") / root).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if any(item in text for item in forbidden):
                violations.append(str(path))
    assert not violations


def test_legacy_market_rule_mapping_is_absent_from_production_source() -> None:
    source = Path("src/onlyalpha")
    text = "\n".join(path.read_text(encoding="utf-8") for path in source.rglob("*.py"))
    assert "OnlyMarketRuleRiskMappingView" not in text
    assert "OnlyMarketSimulationConfig" not in text
    # The parser keeps the removed spelling only to reject it explicitly.
    occurrences = [line for line in text.splitlines() if "market_simulation" in line]
    assert occurrences and all("UNKNOWN_FIELD" in line or 'if "market_simulation"' in line for line in occurrences)
    assert "market_rule: OnlyMarketRule" not in text
