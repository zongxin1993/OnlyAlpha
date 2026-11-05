from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.test_topology import (
    build_topology,
    load_metric_files,
    load_metrics,
    render_markdown,
    validate_shards,
    write_outputs,
)

pytestmark = pytest.mark.architecture


def _metric(path: Path, lane: str, tests: dict[str, float], *, total_seconds: float) -> None:
    path.write_text(
        json.dumps(
            {
                "lane": lane,
                "collected": len(tests),
                "total_seconds": total_seconds,
                "worker_count": 2,
                "distribution_mode": "worksteal",
                "commit": "abc",
                "platform": "test",
                "tests": tests,
            }
        ),
        encoding="utf-8",
    )


def test_topology_is_deterministic_and_reports_duplicate_seconds(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    _metric(metrics_dir / "b.json", "b", {"shared": 3.0, "b-only": 2.0}, total_seconds=5.0)
    _metric(metrics_dir / "a.json", "a", {"shared": 4.0, "a-only": 1.0}, total_seconds=5.0)

    metrics = load_metrics(metrics_dir)
    first = build_topology(metrics, metrics_dir=metrics_dir)
    second = build_topology(load_metrics(metrics_dir), metrics_dir=metrics_dir)

    assert first == second
    assert first["summary"] == {
        "lane_count": 2,
        "total_unique_test_nodes": 3,
        "total_executed_test_nodes": 4,
        "total_observed_test_nodes": 4,
        "duplicate_test_executions": 1,
        "duplicate_execution_ratio": 0.25,
        "estimated_duplicate_execution_seconds": 4.0,
        "total_observed_seconds": 10.0,
        "estimated_parallel_critical_path_seconds": 5.0,
        "slowest_lane": "a",
        "slowest_lane_seconds": 5.0,
        "slowest_node": "shared",
        "slowest_node_seconds": 4.0,
    }
    assert first["lane_overlaps"][0]["shared_tests"] == 1
    assert first["node_to_lanes"]["shared"] == ["a", "b"]


def test_topology_outputs_include_required_gate_sections(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    _metric(metrics_dir / "a.json", "a", {"test::one": 1.0}, total_seconds=2.0)
    topology = build_topology(load_metrics(metrics_dir), metrics_dir=metrics_dir)
    markdown = render_markdown(topology)
    assert "Total unique test nodes" in markdown
    assert "Duplicate execution ratio" in markdown
    assert "Top 10 lane overlaps" in markdown
    assert "Slowest 20 test nodes" in markdown

    json_output = tmp_path / "out" / "topology.json"
    markdown_output = tmp_path / "out" / "topology.md"
    write_outputs(topology, json_output=json_output, markdown_output=markdown_output)
    assert json.loads(json_output.read_text(encoding="utf-8")) == topology
    assert markdown_output.read_text(encoding="utf-8") == markdown


def test_topology_preserves_incomplete_node_level_evidence(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    payload = {
        "lane": "broken",
        "collected": 2,
        "total_seconds": 1.0,
        "worker_count": 0,
        "distribution_mode": "no",
        "tests": {"test::one": 1.0},
    }
    (metrics_dir / "broken.json").write_text(json.dumps(payload), encoding="utf-8")
    topology = build_topology(load_metrics(metrics_dir), metrics_dir=metrics_dir)
    assert topology["node_observation_complete"] is False
    assert topology["summary"]["total_executed_test_nodes"] == 2
    assert topology["summary"]["total_observed_test_nodes"] == 1
    assert "lower bound" in topology["integrity_warnings"][0]


def test_shard_completeness_requires_a_disjoint_complete_union(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    _metric(metrics_dir / "one.json", "research-evaluation", {"one": 1.0, "two": 1.0}, total_seconds=2.0)
    _metric(metrics_dir / "two.json", "research-evaluation", {"three": 1.0}, total_seconds=1.0)
    proof = validate_shards(
        load_metric_files(tuple(sorted(metrics_dir.glob("*.json"))), allow_duplicate_lanes=True),
        {"one", "two", "three"},
    )
    assert proof["complete"] is True
    assert proof["duplicate_test_count"] == 0
    assert proof["missing_test_count"] == 0
