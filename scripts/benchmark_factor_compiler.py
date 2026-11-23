"""Measure the installed source-to-data frontend using the public Factor example.

This is timing evidence, not certification or a product execution entry point.
Run via dev_verification; real confined construction is measured by the PG matrix.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import platform
import resource
import statistics
import time
from pathlib import Path
from unittest.mock import patch

from onlyalpha.algorithm.factor_program import compile_factor_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 3 <= args.samples <= 1000 or args.output.exists():
        raise ValueError("FACTOR_COMPILER_BENCH_INPUT")
    example = Path(__file__).resolve().parents[1] / "examples/private-assets/factor/simple_momentum"
    spec = json.loads((example / "asset.json").read_text())["factor"]
    source = (example / "source.py").read_text()
    original = ast.parse
    observations = []
    programs = set()
    for _ in range(args.samples):
        parse_ns = 0
        calls = 0

        def observed_parse(*values, **keywords):
            nonlocal parse_ns, calls
            start = time.perf_counter_ns()
            try:
                return original(*values, **keywords)
            finally:
                parse_ns += time.perf_counter_ns() - start
                calls += 1

        with patch.object(ast, "parse", observed_parse):
            start = time.perf_counter_ns()
            program = compile_factor_source(
                source,
                1,
                input_contract=spec["input_contract"],
                parameter_contract=spec["parameter_contract"],
                output_contract=spec["output_contract"],
            )
            total = time.perf_counter_ns() - start
        assert calls == 1 and total >= parse_ns
        programs.add(hashlib.sha256(json.dumps(program, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        observations.append(
            {"parse_ns": parse_ns, "validate_lower_ns": total - parse_ns, "total_ns": total, "parse_calls": calls}
        )
    assert len(programs) == 1
    result = {
        "scope": "INSTALLED_PURE_FRONTEND_NOT_CERTIFICATION",
        "platform": platform.platform(),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "source_bytes": len(source.encode()),
        "program_fingerprint": next(iter(programs)),
        "samples": observations,
        "median_ns": {
            key: statistics.median(row[key] for row in observations)
            for key in ("parse_ns", "validate_lower_ns", "total_ns")
        },
        "process_peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "rss_unit": "KiB" if platform.system() == "Linux" else "native",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "scope",
                    "source_sha256",
                    "program_fingerprint",
                    "median_ns",
                    "process_peak_rss",
                    "rss_unit",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
