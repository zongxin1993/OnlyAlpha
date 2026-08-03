from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare(baseline: dict[str, object], current: dict[str, object]) -> str:
    base_time = float(baseline["total_seconds"])
    current_time = float(current["total_seconds"])
    time_change = _change(base_time, current_time)
    base_count = int(baseline["collected"])
    current_count = int(current["collected"])
    has_test_baseline = isinstance(baseline.get("tests"), dict)
    base_tests = _tests(baseline)
    current_tests = _tests(current)
    added = sorted(current_tests.keys() - base_tests.keys())
    disappeared = sorted(base_tests.keys() - current_tests.keys())
    has_marker_baseline = isinstance(baseline.get("marker_counts"), dict)
    base_markers = _counts(baseline, "marker_counts")
    current_markers = _counts(current, "marker_counts")
    marker_changes = sorted(
        (name, base_markers.get(name, 0), current_markers.get(name, 0))
        for name in base_markers.keys() | current_markers.keys()
        if base_markers.get(name, 0) != current_markers.get(name, 0)
    )
    changed = sorted(
        (
            (name, base_tests[name], current_tests[name], _change(base_tests[name], current_tests[name]))
            for name in base_tests.keys() & current_tests.keys()
            if base_tests[name] > 0 and current_tests[name] > base_tests[name] * 1.2
        ),
        key=lambda item: item[3],
        reverse=True,
    )
    warnings = []
    if time_change > 10:
        warnings.append(f"total duration increased {time_change:.1f}% (>10%)")
    lines = [
        f"lane: {current.get('lane', baseline.get('lane', 'unknown'))}",
        f"duration: {base_time:.2f}s -> {current_time:.2f}s ({time_change:+.1f}%)",
        f"collected: {base_count} -> {current_count} ({current_count - base_count:+d})",
        f"added tests: {len(added) if has_test_baseline else 'unavailable'}",
        f"disappeared tests: {len(disappeared) if has_test_baseline else 'unavailable'}",
        f"tests slower by >20%: {len(changed)}",
        f"marker distribution changes: {len(marker_changes) if has_marker_baseline else 'unavailable'}",
    ]
    if has_test_baseline:
        lines.extend(f"  + {item}" for item in added[:20])
        lines.extend(f"  - {item}" for item in disappeared[:20])
    lines.extend(
        f"  ! {name}: {before:.2f}s -> {after:.2f}s ({delta:+.1f}%)" for name, before, after, delta in changed[:20]
    )
    if has_marker_baseline:
        lines.extend(f"  # {name}: {before} -> {after} ({after - before:+d})" for name, before, after in marker_changes)
    lines.extend(f"WARNING: {item}" for item in warnings)
    return "\n".join(lines)


def _tests(payload: dict[str, object]) -> dict[str, float]:
    value = payload.get("tests", {})
    if not isinstance(value, dict):
        return {}
    return {str(key): float(item) for key, item in value.items()}


def _counts(payload: dict[str, object], field: str) -> dict[str, int]:
    value = payload.get(field, {})
    if not isinstance(value, dict):
        return {}
    return {str(key): int(item) for key, item in value.items()}


def _select_baseline(payload: dict[str, object], lane: str | None) -> dict[str, object]:
    lanes = payload.get("lanes")
    if not isinstance(lanes, dict):
        return payload
    if not lane or lane not in lanes or not isinstance(lanes[lane], dict):
        raise ValueError("a valid --lane is required for a multi-lane baseline")
    return lanes[lane]


def _change(before: float, after: float) -> float:
    return 0.0 if before == 0 else (after / before - 1.0) * 100.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two OnlyAlpha pytest metric files")
    parser.add_argument("baseline")
    parser.add_argument("current")
    parser.add_argument("--lane")
    args = parser.parse_args()
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    if not isinstance(baseline, dict) or not isinstance(current, dict):
        raise ValueError("metric files must contain objects")
    lane = args.lane or (str(current["lane"]) if "lane" in current else None)
    print(compare(_select_baseline(baseline, lane), current))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
