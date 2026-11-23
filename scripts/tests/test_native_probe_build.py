"""探针预构建与 fixture 共用成功工件，不信任跨验证的 Cargo 缓存。"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.backend.tests.application.support import native_probe as owner
from scripts import rust_kernel_check


class NativeProbeBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "Cargo.lock").write_text("controlled lock")
        (self.root / "rust-toolchain.toml").write_text('[toolchain]\nchannel="1.99.1"\n')
        self.operation = "00000000-0000-4000-8000-000000000981"
        self.cut()
        self.toolchain = "1.99.1"
        self.seeds = []
        self.builds = []
        self.patchers = [
            patch.object(owner, "ROOT", self.root, create=True),
            patch.object(owner.platform, "machine", return_value="aarch64"),
            patch.dict(os.environ, {"ONLYALPHA_DEV_VERIFICATION_OPERATION_ID": self.operation}),
            patch.object(rust_kernel_check, "prepare_cargo_home", self.seed),
            patch.object(subprocess, "run", self.cargo),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def cut(self, **extra):
        inputs = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                  for name in ("Cargo.lock", "rust-toolchain.toml")}
        (self.root / ".onlyalpha-dev-source-cut.json").write_text(json.dumps({
            "operation_id": self.operation, "inputs": inputs, **extra,
        }))

    def seed(self, registry, home):
        self.assertEqual(registry, Path("/usr/local/cargo/registry"))
        self.seeds.append(home)

    def cargo(self, command, *, cwd, env, check):
        self.assertTrue(check)
        self.assertEqual(cwd, self.root)
        self.assertIn("--frozen", command)
        self.assertIn("--offline", command)
        self.assertEqual(env["RUSTUP_TOOLCHAIN"], self.toolchain)
        self.assertEqual(env["CARGO_NET_OFFLINE"], "true")
        self.builds.append(command)
        target = command[command.index("--target") + 1]
        profile = "release" if "--release" in command else "debug"
        executable = Path(env["CARGO_TARGET_DIR"]) / target / profile / "examples/command-postgres-probe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.unlink(missing_ok=True)
        executable.write_bytes(b"controlled tool result, not a real native execution")
        executable.chmod(0o500)
        return subprocess.CompletedProcess(command, 0)

    def build(self, release=True):
        return owner.build_native_probe(release=release)

    def test_prewarm_and_fixture_reuse_only_one_successful_build(self):
        first = self.build()
        self.assertEqual(first, self.build())
        self.assertEqual((len(self.seeds), len(self.builds)), (1, 1))

    def test_failed_build_cannot_reuse_an_existing_output(self):
        stale = self.root / "test-results/rust-kernel/target/aarch64-unknown-linux-gnu/release/examples/command-postgres-probe"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"an old output is not proof of this build")
        stale.chmod(0o500)
        with patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(1, "cargo")):
            with self.assertRaises(subprocess.CalledProcessError):
                self.build()
        self.build()
        self.assertEqual(len(self.seeds), 2)
        self.assertEqual(len(self.builds), 1)

    def test_failed_registry_seed_does_not_build_or_create_a_receipt(self):
        with patch.object(rust_kernel_check, "prepare_cargo_home", side_effect=OSError("seed failed")):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual(self.builds, [])
        self.build()
        self.assertEqual(len(self.builds), 1)

    def test_missing_or_symlink_source_cut_cannot_authorize_reuse(self):
        executable = self.build()
        marker = self.root / ".onlyalpha-dev-source-cut.json"
        retained = marker.with_suffix(".retained")
        marker.rename(retained)
        with self.subTest(fault="missing"):
            with self.assertRaises(ValueError):
                self.build()
        marker.symlink_to(retained)
        with self.subTest(fault="symlink"):
            with self.assertRaises(ValueError):
                self.build()
        self.assertTrue(executable.exists())
        self.assertEqual(len(self.builds), 1)

    def test_target_and_toolchain_require_separate_successful_builds(self):
        self.build()
        with patch.object(owner.platform, "machine", return_value="x86_64"):
            self.build()
        (self.root / "rust-toolchain.toml").write_text('[toolchain]\nchannel="controlled-other-toolchain"\n')
        self.cut()
        self.toolchain = "controlled-other-toolchain"
        self.build()
        self.assertEqual(len(self.builds), 3)

    def test_tampered_or_missing_or_symlink_output_is_rejected_without_rebuilding(self):
        for fault in ("changed", "missing", "symlink"):
            with self.subTest(fault=fault):
                self.cut(fault=fault)
                executable = self.build()
                if fault == "changed":
                    executable.chmod(0o700)
                    executable.write_bytes(b"different bytes")
                elif fault == "missing":
                    executable.unlink()
                else:
                    other = executable.with_suffix(".other")
                    executable.rename(other)
                    executable.symlink_to(other)
                before = len(self.builds)
                with self.assertRaises(ValueError):
                    self.build()
                self.assertEqual(len(self.builds), before)
                if executable.is_symlink():
                    executable.unlink()

    def test_profile_and_frozen_cut_and_operation_do_not_share_a_receipt(self):
        self.build()
        self.build(release=False)
        self.cut(changed_source=True)
        self.build()
        self.operation = "00000000-0000-4000-8000-000000000982"
        os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"] = self.operation
        self.cut()
        self.build()
        self.assertEqual((len(self.seeds), len(self.builds)), (4, 4))

    def test_missing_freeze_proof_never_reuses_previous_process_output(self):
        os.environ.pop("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID")
        self.build()
        self.build()
        self.assertEqual(len(self.seeds), 2)

    def test_mismatched_freeze_or_lock_is_rejected_before_cargo(self):
        for fault in ("operation", "lock"):
            self.cut()
            if fault == "operation":
                self.cut(operation_id="different")
            else:
                (self.root / "Cargo.lock").write_text("changed after freeze")
            with self.assertRaises(ValueError):
                self.build()
        self.assertEqual(self.builds, [])

    def test_source_cut_changed_during_build_cannot_mint_a_receipt(self):
        def changing(*args, **kwargs):
            result = self.cargo(*args, **kwargs)
            self.cut(changed_while_building=True)
            return result
        with patch.object(subprocess, "run", changing):
            with self.assertRaises(ValueError):
                self.build()
        self.assertEqual(len(self.builds), 1)

    def test_all_three_entry_points_import_the_same_build_owner(self):
        root = Path(__file__).resolve().parents[2]
        module = "packages.backend.tests.application.support.native_probe"
        for file, name in [
            ("conftest.py", "build_native_probe"),
            ("support/native_research_market_fixture.py", "_build_market_probe"),
            ("test_market_storage_postgres_clickhouse.py", "_build_market_probe"),
        ]:
            tree = ast.parse((root / "packages/backend/tests/application" / file).read_text())
            self.assertFalse(any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body), file)
            self.assertTrue(any(isinstance(n, ast.ImportFrom) and n.module == module
                                and any(a.name == "build_native_probe" and (a.asname or a.name) == name
                                        for a in n.names) for n in tree.body), file)


class RuntimeDiagnosticOutputTests(unittest.TestCase):
    def test_stage_events_survive_timeout_without_arbitrary_payload(self):
        row={"event_kind":"operation_start","module":"backend","operation":"runtime.prepare.native_inventory",
             "process_instance_id":"runtime-preparation-probe-123","span_id":"2","mono_ns":100,
             "source":"PRIVATE_SOURCE","password":"DO_NOT_PRINT","error":"arbitrary text"}
        lines=owner.runtime_diagnostic_lines(json.dumps(row))
        self.assertEqual(len(lines),1)
        saved=json.loads(lines[0])
        self.assertEqual(saved["operation"],row["operation"])
        self.assertEqual(saved["span_id"],"2")
        self.assertNotIn("PRIVATE_SOURCE",lines[0])
        self.assertNotIn("DO_NOT_PRINT",lines[0])
        self.assertNotIn("arbitrary text",lines[0])

    def test_startup_and_existing_stage_markers_have_no_result_payload(self):
        lines=owner.runtime_diagnostic_lines(b"[probe-startup] phase=process_entry elapsed_us=0\n[runtime-environment] phase=prepare_begin elapsed_ms=7\nraw secret\n")
        self.assertEqual(len(lines),2)
        self.assertEqual(owner.runtime_diagnostic_lines(None),[])

    def test_other_operations_and_untrusted_rows_are_omitted(self):
        for row in [{"event_kind":"operation_start","module":"backend","operation":"other.operation"},
                    {"event_kind":"operation_start","module":"backend","operation":"runtime.prepare.source","process_instance_id":"PRIVATE"},
                    [],{"error":"PRIVATE"}]:
            self.assertEqual(owner.runtime_diagnostic_lines(json.dumps(row)),[])

    def test_malformed_diagnostic_types_do_not_replace_original_failure(self):
        base={"event_kind":"operation_start","module":"backend","operation":"runtime.prepare.all",
              "process_instance_id":"runtime-preparation-probe-123"}
        self.assertEqual(owner.runtime_diagnostic_lines(json.dumps({**base,"event_kind":[]})),[])
        result=owner.runtime_diagnostic_lines(json.dumps({**base,"outcome":{}}))
        self.assertEqual(len(result),1)
        self.assertNotIn("outcome",json.loads(result[0]))

    def test_json_parser_limits_preserve_the_original_timeout_object(self):
        for payload in ['{"n":'+'1'*5000+'}', '['*2000+'0'+']'*2000]:
            with self.subTest(kind=payload[:5]):
                original=subprocess.TimeoutExpired(["controlled-producer"],30,stderr=payload.encode())
                try:
                    try:
                        raise original
                    except subprocess.TimeoutExpired as error:
                        owner.runtime_diagnostic_lines(error.stderr)
                        raise
                except BaseException as actual:
                    self.assertIs(actual,original)

    def test_actual_string_span_ids_keep_parent_and_pairing(self):
        base={"module":"backend","operation":"runtime.resolver.spawn",
              "process_instance_id":"runtime-preparation-probe-123","span_id":"4","parent_span_id":"3"}
        raw='\n'.join(json.dumps({**base,"event_kind":kind}) for kind in ["operation_start","operation_end"])
        rows=[json.loads(line) for line in owner.runtime_diagnostic_lines(raw)]
        self.assertEqual([(r["span_id"],r["parent_span_id"]) for r in rows],[("4","3"),("4","3")])


if __name__ == "__main__":
    unittest.main()
