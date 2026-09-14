from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS_DIR = ROOT / "test-results" / "metrics"
DEFAULT_JSON_OUTPUT = ROOT / "test-results" / "topology" / "test-topology.json"
DEFAULT_MARKDOWN_OUTPUT = ROOT / "test-results" / "topology" / "test-topology.md"


@dataclass(frozen=True, slots=True)
class LaneMetrics:
    lane: str
    collected: int
    total_seconds: float
    worker_count: int
    distribution_mode: str
    commit: str
    platform: str
    tests: dict[str, float]


def _number(value: Any, *, field: str, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{path}: {field} must be a non-negative number")
    return float(value)


def _load_metric(path: Path) -> LaneMetrics:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read metrics file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: metrics payload must be an object")
    lane = payload.get("lane")
    if not isinstance(lane, str) or not lane:
        raise ValueError(f"{path}: lane must be a non-empty string")
    raw_tests = payload.get("tests")
    if not isinstance(raw_tests, dict):
        raise ValueError(f"{path}: tests must be an object")
    tests: dict[str, float] = {}
    for nodeid, seconds in raw_tests.items():
        if not isinstance(nodeid, str) or not nodeid:
            raise ValueError(f"{path}: test node ids must be non-empty strings")
        tests[nodeid] = _number(seconds, field=f"tests[{nodeid!r}]", path=path)
    collected = payload.get("collected")
    if isinstance(collected, bool) or not isinstance(collected, int) or collected < 0:
        raise ValueError(f"{path}: collected must be a non-negative integer")
    worker_count = payload.get("worker_count")
    if isinstance(worker_count, bool) or not isinstance(worker_count, int) or worker_count < 0:
        raise ValueError(f"{path}: worker_count must be a non-negative integer")
    distribution_mode = payload.get("distribution_mode")
    if not isinstance(distribution_mode, str) or not distribution_mode:
        raise ValueError(f"{path}: distribution_mode must be a non-empty string")
    return LaneMetrics(
        lane=lane,
        collected=collected,
        total_seconds=_number(payload.get("total_seconds"), field="total_seconds", path=path),
        worker_count=worker_count,
        distribution_mode=distribution_mode,
        commit=str(payload.get("commit", "unknown")),
        platform=str(payload.get("platform", "unknown")),
        tests=dict(sorted(tests.items())),
    )


def load_metric_files(files: tuple[Path, ...], *, allow_duplicate_lanes: bool = False) -> tuple[LaneMetrics, ...]:
    if not files:
        raise ValueError("no metrics JSON files supplied")
    lanes: list[LaneMetrics] = []
    seen: set[str] = set()
    for path in files:
        metric = _load_metric(path)
        if metric.lane in seen and not allow_duplicate_lanes:
            raise ValueError(f"duplicate lane metrics: {metric.lane}")
        seen.add(metric.lane)
        lanes.append(metric)
    return tuple(sorted(lanes, key=lambda item: item.lane))


def load_metrics(metrics_dir: Path) -> tuple[LaneMetrics, ...]:
    files = tuple(sorted(metrics_dir.glob("*.json")))
    if not files:
        raise ValueError(f"no metrics JSON files found in {metrics_dir}")
    return load_metric_files(files)


def validate_shards(metrics: tuple[LaneMetrics, ...], expected_nodes: set[str]) -> dict[str, Any]:
    node_sets = [set(item.tests) for item in metrics]
    union = set().union(*node_sets) if node_sets else set()
    duplicate = sorted(
        {node for index, nodes in enumerate(node_sets) for later in node_sets[index + 1 :] for node in nodes & later}
    )
    return {
        "shard_count": len(metrics),
        "expected_test_count": len(expected_nodes),
        "union_test_count": len(union),
        "duplicate_test_count": len(duplicate),
        "duplicate_tests": duplicate,
        "missing_test_count": len(expected_nodes - union),
        "missing_tests": sorted(expected_nodes - union),
        "unexpected_test_count": len(union - expected_nodes),
        "unexpected_tests": sorted(union - expected_nodes),
        "complete": union == expected_nodes and not duplicate,
    }


def _git_head() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=False, text=True)
    except OSError:
        return "unknown"
    return result.stdout.strip() or "unknown"


def build_topology(metrics: tuple[LaneMetrics, ...], *, metrics_dir: Path) -> dict[str, Any]:
    lane_nodes = {item.lane: sorted(item.tests) for item in metrics}
    node_lanes: dict[str, list[str]] = defaultdict(list)
    node_durations: dict[str, dict[str, float]] = defaultdict(dict)
    for item in metrics:
        for nodeid, seconds in item.tests.items():
            node_lanes[nodeid].append(item.lane)
            node_durations[nodeid][item.lane] = seconds

    overlaps: list[dict[str, Any]] = []
    for index, left in enumerate(metrics):
        left_nodes = set(left.tests)
        for right in metrics[index + 1 :]:
            shared = sorted(left_nodes & set(right.tests))
            if not shared:
                continue
            shared_duration = sum(min(left.tests[node], right.tests[node]) for node in shared)
            left_duration = sum(left.tests[node] for node in shared)
            right_duration = sum(right.tests[node] for node in shared)
            overlaps.append(
                {
                    "lane_a": left.lane,
                    "lane_b": right.lane,
                    "shared_tests": len(shared),
                    "shared_duration_seconds": round(shared_duration, 6),
                    "overlap_percent_of_a": round(100 * shared_duration / left_duration, 3) if left_duration else 0.0,
                    "overlap_percent_of_b": round(100 * shared_duration / right_duration, 3) if right_duration else 0.0,
                    "shared_nodeids": shared,
                }
            )
    overlaps.sort(key=lambda item: (-item["shared_duration_seconds"], item["lane_a"], item["lane_b"]))

    duplicate_nodes = {node: sorted(lanes) for node, lanes in node_lanes.items() if len(lanes) > 1}
    duplicate_execution_seconds = sum(
        sum(durations.values()) - min(durations.values()) for durations in node_durations.values() if len(durations) > 1
    )
    all_nodes = set(node_lanes)
    lane_durations = [
        {
            "lane": item.lane,
            "collected": item.collected,
            "observed_node_count": len(item.tests),
            "node_observation_complete": item.collected == len(item.tests),
            "total_seconds": item.total_seconds,
            "worker_count": item.worker_count,
            "distribution_mode": item.distribution_mode,
            "commit": item.commit,
            "platform": item.platform,
        }
        for item in metrics
    ]
    lane_durations.sort(key=lambda item: (-cast(float, item["total_seconds"]), cast(str, item["lane"])))
    slowest_nodes = [
        {
            "nodeid": node,
            "max_seconds": max(durations.values()),
            "observed_seconds_by_lane": dict(sorted(durations.items())),
            "lanes": sorted(node_lanes[node]),
        }
        for node, durations in node_durations.items()
    ]
    slowest_nodes.sort(key=lambda item: (-cast(float, item["max_seconds"]), cast(str, item["nodeid"])))
    source_commits = sorted({item.commit for item in metrics})
    source_platforms = sorted({item.platform for item in metrics})
    incomplete_lanes = sorted(item.lane for item in metrics if item.collected != len(item.tests))
    return {
        "schema_version": 1,
        "authority": "scripts/test_suite.py metrics; analyzer is reporting-only",
        "metrics_directory": str(metrics_dir),
        "current_head": _git_head(),
        "source_commits": source_commits,
        "source_platforms": source_platforms,
        "source_is_single_commit": len(source_commits) == 1,
        "source_is_single_platform": len(source_platforms) == 1,
        "node_observation_complete": not incomplete_lanes,
        "integrity_warnings": [
            f"{lane}: collected count does not match observed tests map; duplicate metrics are a lower bound"
            for lane in incomplete_lanes
        ],
        "lane_to_nodes": lane_nodes,
        "node_to_lanes": dict(sorted((node, sorted(lanes)) for node, lanes in node_lanes.items())),
        "lane_overlaps": overlaps,
        "lane_durations": lane_durations,
        "slowest_nodes": slowest_nodes[:20],
        "summary": {
            "lane_count": len(metrics),
            "total_unique_test_nodes": len(all_nodes),
            "total_executed_test_nodes": sum(item.collected for item in metrics),
            "total_observed_test_nodes": sum(len(item.tests) for item in metrics),
            "duplicate_test_executions": sum(len(lanes) - 1 for lanes in duplicate_nodes.values()),
            "duplicate_execution_ratio": round(
                sum(len(lanes) - 1 for lanes in duplicate_nodes.values()) / sum(item.collected for item in metrics), 6
            )
            if sum(item.collected for item in metrics)
            else 0.0,
            "estimated_duplicate_execution_seconds": round(duplicate_execution_seconds, 6),
            "total_observed_seconds": round(sum(item.total_seconds for item in metrics), 6),
            "estimated_parallel_critical_path_seconds": round(max(item.total_seconds for item in metrics), 6),
            "slowest_lane": lane_durations[0]["lane"],
            "slowest_lane_seconds": lane_durations[0]["total_seconds"],
            "slowest_node": slowest_nodes[0]["nodeid"] if slowest_nodes else None,
            "slowest_node_seconds": slowest_nodes[0]["max_seconds"] if slowest_nodes else 0.0,
        },
        "duplicate_nodes": duplicate_nodes,
    }


def _seconds(value: float) -> str:
    return f"{value:.2f}s"


def render_markdown(topology: dict[str, Any]) -> str:
    summary = topology["summary"]
    lines = [
        "# Test execution topology",
        "",
        "> Reporting-only evidence generated from `test-results/metrics/*.json`; canonical lane semantics remain in `scripts/test_suite.py`.",
        "",
        f"- Source commits: {', '.join(topology['source_commits'])}",
        f"- Source platforms: {', '.join(topology['source_platforms'])}",
        f"- Current HEAD: `{topology['current_head']}`",
        f"- Single-commit source: `{topology['source_is_single_commit']}`",
        f"- Complete node-level observation: `{topology['node_observation_complete']}`",
        *[f"- Warning: {warning}" for warning in topology["integrity_warnings"]],
        "",
        "## Task 1 gate",
        "",
        f"- Total unique test nodes: {summary['total_unique_test_nodes']}",
        f"- Total executed test nodes: {summary['total_executed_test_nodes']}",
        f"- Total observed test nodes: {summary['total_observed_test_nodes']}",
        f"- Duplicate executions: {summary['duplicate_test_executions']}",
        f"- Duplicate execution ratio: {summary['duplicate_execution_ratio']:.2%}",
        f"- Estimated duplicate runtime: {_seconds(summary['estimated_duplicate_execution_seconds'])}",
        f"- Slowest lane: `{summary['slowest_lane']}` ({_seconds(summary['slowest_lane_seconds'])})",
        f"- Estimated critical path: {_seconds(summary['estimated_parallel_critical_path_seconds'])}",
        "",
        "## Lane durations",
        "",
        "| Lane | Collected | Duration | Workers | Distribution | Commit |",
        "|---|---:|---:|---:|---|---|",
    ]
    for lane in topology["lane_durations"]:
        lines.append(
            f"| `{lane['lane']}` | {lane['collected']} | {_seconds(lane['total_seconds'])} | "
            f"{lane['worker_count']} | `{lane['distribution_mode']}` | `{lane['commit']}` |"
        )
    lines.extend(
        [
            "",
            "## Top 10 lane overlaps",
            "",
            "| Lane A | Lane B | Shared Tests | Shared Duration | Overlap % of A | Overlap % of B |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for overlap in topology["lane_overlaps"][:10]:
        lines.append(
            f"| `{overlap['lane_a']}` | `{overlap['lane_b']}` | {overlap['shared_tests']} | "
            f"{_seconds(overlap['shared_duration_seconds'])} | {overlap['overlap_percent_of_a']:.2f}% | "
            f"{overlap['overlap_percent_of_b']:.2f}% |"
        )
    lines.extend(["", "## Slowest 20 test nodes", "", "| Node | Max observed duration | Lanes |", "|---|---:|---|"])
    for node in topology["slowest_nodes"]:
        lines.append(
            f"| `{node['nodeid']}` | {_seconds(node['max_seconds'])} | "
            f"{', '.join(f'`{lane}`' for lane in node['lanes'])} |"
        )
    return "\n".join(lines) + "\n"


def write_outputs(topology: dict[str, Any], *, json_output: Path, markdown_output: Path) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(topology, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_output.write_text(render_markdown(topology), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report duplicate test execution and lane topology from canonical metrics"
    )
    parser.add_argument("--metrics-dir", type=Path, default=DEFAULT_METRICS_DIR)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--validate-shards", nargs="+", type=Path)
    parser.add_argument("--expected-duration-path", type=Path)
    args = parser.parse_args()
    try:
        if args.validate_shards is not None:
            if args.expected_duration_path is None:
                parser.error("--expected-duration-path is required with --validate-shards")
            shard_metrics = load_metric_files(tuple(args.validate_shards), allow_duplicate_lanes=True)
            expected_payload = json.loads(args.expected_duration_path.read_text(encoding="utf-8"))
            if not isinstance(expected_payload, dict) or not all(isinstance(node, str) for node in expected_payload):
                parser.error("expected duration data must be a JSON object keyed by node id")
            proof = validate_shards(shard_metrics, set(expected_payload))
            print(json.dumps(proof, indent=2, sort_keys=True))
            return 0 if proof["complete"] else 1
        metrics = load_metrics(args.metrics_dir)
        topology = build_topology(metrics, metrics_dir=args.metrics_dir)
        write_outputs(topology, json_output=args.json_output, markdown_output=args.markdown_output)
    except ValueError as exc:
        parser.error(str(exc))
    summary = topology["summary"]
    print(
        "Total unique test nodes: {total_unique_test_nodes}\n"
        "Total executed test nodes: {total_executed_test_nodes}\n"
        "Duplicate executions: {duplicate_test_executions}\n"
        "Duplicate execution ratio: {duplicate_execution_ratio:.2%}\n"
        "Estimated duplicate runtime: {estimated_duplicate_execution_seconds:.2f}s\n"
        "Slowest lane: {slowest_lane} ({slowest_lane_seconds:.2f}s)\n"
        "Slowest node: {slowest_node} ({slowest_node_seconds:.2f}s)\n"
        "Estimated critical path: {estimated_parallel_critical_path_seconds:.2f}s".format(**summary)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
