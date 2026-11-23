import json
import zipfile

import pytest

from scripts.backtest_benchmark import compare, profile, requests


def event(**row):
    return "BACKTEST_PROFILE " + json.dumps({"pid": 12, **row})


def test_nested_costs_errors_and_incomplete_calls_stay_distinct():
    report = profile(
        [
            event(event="begin", id=1, parent=None, run="run", stage="commit"),
            event(event="begin", id=2, parent=1, run="run", stage="read"),
            event(event="end", id=2, elapsed_ns="30", ok=False),
            event(event="end", id=1, elapsed_ns="100", ok=False),
            event(event="begin", id=3, parent=None, run="run", stage="read"),
        ]
    )
    assert report["stages"][0]["inclusive"]["total_ns"] == 100
    assert report["stages"][0]["exclusive"]["total_ns"] == 70
    assert report["stages"][1]["ok"] is False
    assert report["stages"][1]["inclusive"]["calls"] == 1
    assert report["incomplete"][0]["id"] == 3


def test_invalid_or_combined_duplicate_process_logs_are_rejected():
    with pytest.raises(ValueError, match="unmatched"):
        profile([event(event="end", id=2, elapsed_ns="1", ok=True)])
    with pytest.raises(ValueError, match="duplicate"):
        profile([event(event="begin", id=1, parent=None, run="r", stage="s")] * 2)


def test_comparison_refuses_storage_or_input_changes():
    metadata = dict(
        profile="release",
        scope="test",
        storage="overlay",
        trace_sha256="a",
        configuration_sha256="b",
        input_pin="c",
        bars=740,
        cache="retained",
        rounds=1,
        stage_count=2,
        benchmark_binary_sha256="exe",
        compiler="rustc test",
        os="linux",
        arch="aarch64",
    )
    baseline = {
        "metadata": [dict(metadata)],
        "samples": [{"round": 1, "stage": "chain.total", "result_sha256": "result"}, {"round": 1, "stage": "read"}],
        "benchmarks": {"read": {"median_ns": 100}},
    }
    current = {
        "metadata": [dict(metadata)],
        "samples": [{"round": 1, "stage": "chain.total", "result_sha256": "result"}, {"round": 1, "stage": "read"}],
        "benchmarks": {"read": {"median_ns": 120}},
    }
    assert compare(current, baseline)["read"]["ratio"] == 1.2
    current["metadata"][0]["storage"] = "bind"
    with pytest.raises(ValueError, match="storage"):
        compare(current, baseline)


def test_trace_preserves_blocked_error_and_omits_secrets(tmp_path):
    path = tmp_path / "trace.zip"
    snapshot = {
        "request": {
            "url": "https://host/api/v2/backtest/preparations/commands/id?secret=hidden",
            "method": "GET",
            "headers": [{"name": "Authorization", "value": "hidden"}],
        },
        "response": {"status": 200, "content": {"_sha1": "body.json"}},
        "time": 30,
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("0.network", json.dumps({"snapshot": snapshot}))
        archive.writestr(
            "resources/body.json",
            json.dumps(
                {
                    "state": "BLOCKED",
                    "phase": "STOPPED",
                    "detail": {"code": "RESEARCH_RUNTIME_UNAVAILABLE"},
                    "secret": "hidden",
                }
            ),
        )
    result = requests(path)
    assert result[0]["code"] == "RESEARCH_RUNTIME_UNAVAILABLE"
    assert result[0]["state"] == "BLOCKED"
    assert "hidden" not in json.dumps(result)


def test_comparison_refuses_missing_metadata_and_changed_result():
    metadata = dict(
        profile="release",
        scope="test",
        storage="overlay",
        trace_sha256="a",
        configuration_sha256="b",
        input_pin="c",
        bars=740,
        cache="retained",
        rounds=1,
        stage_count=2,
        benchmark_binary_sha256="exe",
        compiler="rustc test",
        os="linux",
        arch="aarch64",
    )
    baseline = {
        "metadata": [metadata],
        "benchmarks": {},
        "samples": [{"round": 1, "stage": "chain.total", "result_sha256": "original"}, {"round": 1, "stage": "read"}],
    }
    current = json.loads(json.dumps(baseline))
    current["samples"][0]["result_sha256"] = "changed"
    with pytest.raises(ValueError, match="result identity"):
        compare(current, baseline)
    del current["metadata"][0]["profile"]
    with pytest.raises(ValueError, match="missing benchmark metadata"):
        compare(current, baseline)


def test_comparison_refuses_partial_rounds():
    baseline = {
        "metadata": [
            {
                "rounds": 2,
                "stage_count": 2,
                "benchmark_binary_sha256": "exe",
                "compiler": "rustc test",
                "os": "linux",
                "arch": "aarch64",
            }
        ],
        "samples": [{"round": 1, "stage": "chain.total", "result_sha256": "same"}, {"round": 1, "stage": "read"}],
    }
    with pytest.raises(ValueError, match="incomplete benchmark rounds"):
        compare(baseline, baseline)


def test_complete_parent_with_missing_child_end_is_not_trusted():
    report = profile(
        [
            event(event="begin", id=1, parent=None, run="run", stage="commit"),
            event(event="begin", id=2, parent=1, run="run", stage="read"),
            event(event="end", id=1, elapsed_ns="100", ok=True),
        ]
    )
    assert not report["stages"]
    assert {row["id"] for row in report["incomplete"]} == {1, 2}
