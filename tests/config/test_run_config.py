import json

from onlyalpha.config import OnlyRunConfig


def test_yaml_and_json_normalize_to_the_same_run_config() -> None:
    yaml_config = OnlyRunConfig.load("examples/configs/backtest/macd/run.yaml")
    json_config = OnlyRunConfig.load("examples/configs/backtest/macd/run.json")
    assert yaml_config.runtime == json_config.runtime
    assert yaml_config.reference_data == json_config.reference_data
    assert yaml_config.universes == json_config.universes
    assert yaml_config.data_sources == json_config.data_sources
    assert yaml_config.accounts == json_config.accounts
    assert yaml_config.brokers == json_config.brokers
    assert yaml_config.clusters == json_config.clusters


def test_common_parser_accepts_every_runtime_type_without_reading_extensions() -> None:
    baseline = OnlyRunConfig.load("examples/configs/backtest/macd/run.json")
    for runtime_type in ("BACKTEST", "PAPER", "LIVE", "SHADOW", "RESEARCH"):
        payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
        payload["runtime"]["type"] = runtime_type
        payload["runtime"]["start_time"] = None
        payload["runtime"]["end_time"] = None
        payload["runtime"]["extensions"] = {"unknown_future_extension": {"kept": True}}
        parsed = OnlyRunConfig.from_mapping(payload)
        assert parsed.runtime.runtime_type == runtime_type
        assert parsed.runtime.extensions["unknown_future_extension"] == {"kept": True}
