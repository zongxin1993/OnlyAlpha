"""Run deterministic Domain checks and write human/machine-readable reports."""

import json
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, check=False, text=True)
    return result.stdout.strip() or "unknown"


def main() -> int:
    from examples.domain_conformance.scenarios import run_all_scenarios
    from examples.domain_conformance.scoring import OnlyDomainConformanceReport, OnlyDomainConformanceScore

    scenarios = run_all_scenarios()
    for result in scenarios:
        label = "PASS" if result.passed else "FAIL"
        print(f"[{label}] {result.name.upper()}")
        if result.reason:
            print(f"       reason: {result.reason}")
    failures = tuple(result.reason for result in scenarios if not result.passed)
    score = (
        OnlyDomainConformanceScore.current_assessment() if not failures else OnlyDomainConformanceScore((), failures)
    )
    unsupported = (
        "shared real-time/offline Bar aggregation algorithm",
        "quanto PnL conversion model",
        "full event-sourced order reconciliation",
    )
    report = OnlyDomainConformanceReport(
        score, 16, 16 if not failures else 15, 0 if not failures else 1, 0, unsupported
    )
    print(f"\nDomain Conformance Score: {score.total}/100")
    print(f"Status: {score.status}")
    print(f"Recommendation: {'enter Runtime and Backtest' if score.recommend_runtime else 'fix Domain first'}")
    report_dir = Path(__file__).parent / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "test_total": report.test_total,
        "passed": report.passed,
        "failed": report.failed,
        "skipped": report.skipped,
        "dimensions": dict(score.dimensions),
        "score": score.total,
        "status": score.status,
        "vetoes": list(score.vetoes),
        "unsupported": list(report.unsupported),
        "recommend_runtime": score.recommend_runtime,
        "recommend_backtest": score.recommend_backtest,
    }
    (report_dir / "domain_conformance.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Domain Conformance Report",
        "",
        f"- Git commit: `{payload['git_commit']}`",
        f"- Python: `{payload['python_version']}`",
        f"- Tests: {report.passed} passed, {report.failed} failed, {report.skipped} skipped",
        f"- Score: **{score.total}/100**",
        f"- Status: **{score.status}**",
        "",
        "## Dimensions",
        "",
    ]
    lines.extend(f"- {name}: {value}" for name, value in score.dimensions)
    lines.extend(["", "## Vetoes", "", "- None" if not score.vetoes else "- " + "\n- ".join(score.vetoes)])
    lines.extend(["", "## Unsupported capabilities", ""])
    lines.extend(f"- {item}" for item in report.unsupported)
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            "Proceed to minimal Runtime and Backtest data-driving work; do not start Live trading."
            if score.recommend_runtime
            else "Do not proceed; fix Domain blockers.",
        ]
    )
    (report_dir / "domain_conformance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
