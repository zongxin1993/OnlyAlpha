"""验证三个公开因子集功能测试的输入归属和隔离构建副本。"""

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from scripts.rust_kernel_check import (
    _isolated_modules, _validate_pure_sources, affected_packages, validate_calculation_sources,
)

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path("crates/calculation/tests")
ALPHA158 = Path("examples/factor/qlib/alpha158")
WORLDQUANT = Path("examples/factor/worldquant/alpha101")
GTJA = Path("examples/factor/gtja/alpha191")
CASES = (
    (TESTS / "alpha158.rs", TESTS / "fixtures/alpha158/expected.jsonl", ((ALPHA158, 158),)),
    (TESTS / "formula_alphas.rs", TESTS / "fixtures/formula_alphas/expected.jsonl", ((WORLDQUANT, 101), (GTJA, 191))),
)


class OperatorSourceBoundary(unittest.TestCase):
    def test_algebra_submodules_and_private_tests_require_their_registered_owner(self):
        _validate_pure_sources(ROOT, "operators", set())
        with tempfile.TemporaryDirectory() as tmp:
            cut = Path(tmp)
            src = cut / "crates/operators/src"
            (src / "tests").mkdir(parents=True)
            for owner, target in (
                ("algebra.rs", "unlisted.rs"), ("registry.rs", "power.rs"), ("registry.rs", "regression.rs"),
                ("power.rs", "tests/regression_tests.rs"), ("regression.rs", "tests/power_tests.rs"),
            ):
                with self.subTest(owner=owner, target=target):
                    (src / target).write_text("")
                    (src / owner).write_text(f'#[path = "{target}"]\nmod inner;\n')
                    with self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                        _validate_pure_sources(cut, "operators", set())
                    (src / owner).unlink()
                    (src / target).unlink()


class AlphaSourceBoundary(unittest.TestCase):
    def test_registered_resources_select_the_consuming_package(self):
        for source, golden, collections in CASES:
            expected = affected_packages(ROOT, (str(source),))
            self.assertIn("onlyalpha-calculation", expected)
            targets = [golden]
            for directory, _ in collections:
                targets.extend(path.relative_to(ROOT) for path in (ROOT / directory).glob("*.json"))
            for path in targets:
                with self.subTest(path=path):
                    self.assertEqual(affected_packages(ROOT, (str(path),)), expected)

    def test_unregistered_resources_still_require_impact_review(self):
        for path in (
            ALPHA158 / "ROC6.json", WORLDQUANT / "ALPHA102.json", GTJA / "Alpha192.json",
            *(golden.with_name("unlisted.jsonl") for _, golden, _ in CASES),
        ):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "RUST_IMPACT_REVIEW_REQUIRED"):
                affected_packages(ROOT, (str(path),))

    def test_isolated_calculation_contains_exact_compiler_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cut = Path(tmp) / "isolated"
            _isolated_modules(ROOT, cut, ("operators", "calculation"))
            validate_calculation_sources(cut)
            for source, golden, collections in CASES:
                targets = {golden}
                for directory, count in collections:
                    manifest = json.loads((cut / directory / "manifest.json").read_bytes())
                    declared = {row["file"] for row in manifest["features"]} | {"manifest.json"}
                    self.assertEqual(len(manifest["features"]), count)
                    self.assertEqual(len(declared), count + 1)
                    self.assertEqual(declared, {p.name for p in (ROOT / directory).glob("*.json")})
                    self.assertEqual(declared, {p.name for p in (cut / directory).iterdir()})
                    targets.update(directory / name for name in declared)
                    for row in manifest["features"]:
                        actual = hashlib.sha256((cut / directory / row["file"]).read_bytes()).hexdigest()
                        self.assertEqual(actual, row["sha256"], row["file"])
                literals = re.findall(r'include_str!\(\s*"([^"]+)"\s*\)', (cut / source).read_text())
                self.assertEqual({(cut / source.parent / arg).resolve() for arg in literals},
                                 {(cut / p).resolve() for p in targets})
                for target in targets:
                    self.assertEqual((cut / target).read_bytes(), (ROOT / target).read_bytes(), str(target))

    def test_resources_are_scoped_to_the_declared_test_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            cut = Path(tmp)
            (cut / TESTS).mkdir(parents=True)
            for source, golden, collections in CASES:
                (cut / golden.parent).mkdir(parents=True)
                (cut / golden).write_text("payload")
                golden_arg = golden.relative_to(TESTS)
                for owner, expression in (
                    (source, 'env!("CARGO_MANIFEST_DIR")'),
                    (source.with_name("other.rs"), f'include_str!("{golden_arg}")'),
                    *((source, f'include_str!("../../../{directory}/unlisted.json")') for directory, _ in collections),
                ):
                    with self.subTest(owner=owner, expression=expression):
                        (cut / owner).write_text(expression)
                        with self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                            validate_calculation_sources(cut)
                        (cut / owner).unlink()
                (cut / golden).unlink()
                for path in [golden, *(directory / "manifest.json" for directory, _ in collections)]:
                    (cut / path).parent.mkdir(parents=True, exist_ok=True)
                    argument = golden_arg if path == golden else f"../../../{path}"
                    (cut / source).write_text(f'include_str!("{argument}")')
                    with self.subTest(missing=path), self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                        validate_calculation_sources(cut)
                    (cut / path).symlink_to(ROOT / path)
                    with self.subTest(symlink=path), self.assertRaisesRegex(ValueError, "RUST_MODULE_BOUNDARY_INVALID"):
                        validate_calculation_sources(cut)
                    (cut / path).unlink()
                    (cut / source).unlink()
