"""Exercise the gate's actual CLI entry against controlled external-tool records."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

SCRIPT = Path(__file__).resolve().parents[1] / "domain_mutation.py"
OWNERS = {
    "value": ["validate_precision", "validate_quantity", "validate_multiplier", "validated_currency_code"],
    "numeric": ["from_str", "fractional_precision", "result", "is_negative", "is_zero"],
}


def tool_records():
    rows = []
    span = {"start": {"line": 1, "column": 1}, "end": {"line": 2, "column": 2}}
    for owner, names in OWNERS.items():
        for name in names:
            file = f"crates/domain/src/{owner}.rs"
            rows.append(
                {
                    "name": f"{file}:1:1: replace {owner}::{name} with Ok(())",
                    "package": "onlyalpha-domain",
                    "file": file,
                    "function": {"function_name": f"{owner}::{name}", "return_type": "-> bool", "span": span},
                    "span": span,
                    "replacement": "Ok(())",
                    "genre": "FnValue",
                    "diff": "a real tool diff",
                }
            )

    def phase(name, status):
        return {"phase": name, "duration": 1, "process_status": status, "argv": ["cargo", "test"]}

    baseline = {
        "scenario": "Baseline",
        "summary": "Success",
        "log_path": "baseline.log",
        "diff_path": None,
        "phase_results": [phase("Build", "Success"), phase("Test", "Success")],
    }
    outcomes = [baseline] + [
        {
            "scenario": {"Mutant": {key: value for key, value in row.items() if key != "diff"}},
            "summary": "CaughtMutant",
            "log_path": f"{index}.log",
            "diff_path": f"{index}.diff",
            "phase_results": [phase("Build", "Success"), phase("Test", {"Failure": 101})],
        }
        for index, row in enumerate(rows)
    ]
    return rows, {
        "outcomes": outcomes,
        "total_mutants": len(rows),
        "caught": len(rows),
        "missed": 0,
        "timeout": 0,
        "unviable": 0,
        "success": 0,
        "start_time": "2026-11-06T00:00:00Z",
        "end_time": "2026-11-06T00:01:00Z",
        "cargo_mutants_version": "27.1.0",
    }


FAKE_CARGO = """import json,os,pathlib,sys
root=pathlib.Path.cwd(); case=os.environ['OA_CASE']
assert os.environ['CARGO_NET_OFFLINE']=='true'
assert os.environ['CARGO_BUILD_JOBS']=='1'
assert os.environ['CARGO_PROFILE_DEV_DEBUG']=='0'
assert os.environ['CARGO_PROFILE_TEST_DEBUG']=='0'
assert 'RUSTFLAGS' not in os.environ
assert os.environ['RUSTUP_TOOLCHAIN']=='1.99.1'
home=pathlib.Path(os.environ['CARGO_HOME'])
assert (home/'registry/fixture-marker').read_text()=='immutable image registry'
assert home.parent==pathlib.Path(os.environ['CARGO_TARGET_DIR']).parent
assert home.parent.parent==root/'test-results/domain-mutation'

if '--version' in sys.argv:
 print('cargo-mutants '+('0.0.0' if case=='wrong-installed-tool' else '27.1.0'));sys.exit(0)
with (root/'invocations.jsonl').open('a') as log:log.write(json.dumps(sys.argv)+'\\n')
records=json.loads((root/'tool-records.json').read_text())
if '--list' in sys.argv:print(json.dumps(records['list']));sys.exit(0)
if case=='nonzero':sys.exit(3)
if case=='missing-output':sys.exit(0)
output=pathlib.Path(sys.argv[sys.argv.index('--output')+1])/'mutants.out';output.mkdir()
(output/'outcomes.json').write_text(json.dumps(records['result']))
if case=='source-changed':(root/'crates/domain/src/value.rs').write_text('changed')
"""


class DomainMutationEntryTests(unittest.TestCase):
    def invoke(self, case):
        with tempfile.TemporaryDirectory(prefix="domain-mutation-entry-") as temp:
            root = Path(temp)
            (root / "scripts").mkdir()
            shutil.copyfile(SCRIPT, root / "scripts/domain_mutation.py")
            for relative in (
                "crates/domain/src/value.rs",
                "crates/domain/src/numeric.rs",
                "crates/domain/src/lib.rs",
                "crates/domain/Cargo.toml",
                "Cargo.toml",
                "Cargo.lock",
                "rust-toolchain.toml",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("controlled source for " + relative)
            (root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.99.1"\n')
            registry = root / "image-registry"
            registry.mkdir()
            (registry / "fixture-marker").write_text("immutable image registry")
            if case == "missing-registry":
                shutil.rmtree(registry)
            elif case == "symlink-registry":
                registry.rename(root / "other-registry")
                registry.symlink_to(root / "other-registry", target_is_directory=True)
            rows, result = copy.deepcopy(tool_records())
            if case == "empty-list":
                rows.clear()
            elif case == "missing-owner":
                rows.pop()
            elif case == "duplicate-list":
                rows.append(copy.deepcopy(rows[0]))
            elif case == "partial":
                result["outcomes"].pop()
            elif case == "duplicate-result":
                result["outcomes"][-1] = copy.deepcopy(result["outcomes"][1])
            elif case == "wrong-association":
                result["outcomes"][-1]["scenario"]["Mutant"]["replacement"] = "unrelated"
            elif case == "bad-baseline":
                result["outcomes"][0]["phase_results"].pop()
            elif case == "duplicate-baseline":
                result["outcomes"].append(copy.deepcopy(result["outcomes"][0]))
            elif case == "unknown":
                result["outcomes"][1]["summary"] = "UNKNOWN"
            elif case == "wrong-result-tool":
                result["cargo_mutants_version"] = "0.0.0"
            elif case == "timeout":
                result["outcomes"][1]["summary"] = "Timeout"
            elif case == "survivor":
                result["outcomes"][1]["summary"] = "MissedMutant"
            elif case == "wrong-schema":
                del result["outcomes"][1]["scenario"]["Mutant"]["span"]
            elif case == "all-unviable":
                result["caught"], result["unviable"] = 0, len(rows)
                for row in result["outcomes"][1:]:
                    row["summary"] = "Unviable"
                    row["phase_results"] = [row["phase_results"][-1] | {"phase": "Build"}]
            (root / "tool-records.json").write_text(json.dumps({"list": rows, "result": result}))
            bindir = root / "bin"
            bindir.mkdir()
            cargo = bindir / "cargo"
            cargo.write_text(f"#!{sys.executable}\n" + FAKE_CARGO)
            cargo.chmod(0o700)
            # A fabricated successful previous run must never satisfy this invocation.
            stale = root / "test-results/domain-mutation/old/mutants.out"
            stale.mkdir(parents=True)
            (stale / "outcomes.json").write_text(json.dumps(result))
            run = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    # Use the real compiler and registry preparation helpers;
                    # only substitute the read-only image registry fixture path.
                    "import runpy,sys; from pathlib import Path; "
                    f"sys.path.insert(0, {str(SCRIPT.parents[1])!r}); "
                    "from scripts import rust_kernel_check as kernel; "
                    "original = kernel.prepare_cargo_home; "
                    "kernel.prepare_cargo_home = lambda registry, home: original(Path('image-registry'), home); "
                    "runpy.run_path('scripts/domain_mutation.py', run_name='__main__')",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": str(bindir) + os.pathsep + os.defpath,
                    "OA_CASE": case,
                    "CARGO_HOME": str(root / "unseeded-cargo-home"),
                    "CARGO_NET_OFFLINE": "false",
                    "CARGO_BUILD_JOBS": "99",
                    "RUSTFLAGS": "--cfg unadmitted",
                    "RUSTUP_TOOLCHAIN": "unadmitted",
                },
                capture_output=True,
                text=True,
                timeout=20,
            )
            verified = list(root.glob("test-results/domain-mutation/run-*/verified.json"))
            if case == "pass":
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(len(verified), 1)
                receipt = json.loads(verified[0].read_text())
                self.assertEqual(receipt["counts"]["caught"], len(rows))
                self.assertEqual(len(receipt["source_sha256"]), 7)
                commands = [json.loads(line) for line in (root / "invocations.jsonl").read_text().splitlines()]
                self.assertEqual(len(commands), 2)
                for command in commands:
                    for flag in ("--no-config", "--cargo-arg=--locked", "--test-package", "--baseline"):
                        self.assertIn(flag, command)
                    self.assertNotIn("--in-place", command)
            else:
                self.assertNotEqual(run.returncode, 0, case)
                self.assertEqual(verified, [], case)
                if case in {"missing-registry", "symlink-registry"}:
                    self.assertIn("RUST_KERNEL_CARGO_HOME_NOT_ADMITTED", run.stderr)
                    self.assertFalse((root / "invocations.jsonl").exists())

    def test_actual_entry_accepts_complete_run_and_rejects_false_proofs(self):
        for case in (
            "pass",
            "nonzero",
            "empty-list",
            "missing-owner",
            "duplicate-list",
            "all-unviable",
            "partial",
            "duplicate-result",
            "wrong-association",
            "bad-baseline",
            "duplicate-baseline",
            "unknown",
            "wrong-installed-tool",
            "wrong-result-tool",
            "timeout",
            "survivor",
            "wrong-schema",
            "missing-output",
            "source-changed",
            "missing-registry",
            "symlink-registry",
        ):
            with self.subTest(case=case):
                self.invoke(case)


if __name__ == "__main__":
    unittest.main()
