"""Rust 库目录规则必须接纳正常结构并拒绝缺失文档及非标准目录。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest

from scripts.rust_kernel_check import validate_crate_layout

pytestmark = pytest.mark.architecture


class CrateLayoutContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.crate = self.root / "crates/sample"
        (self.crate / "src").mkdir(parents=True)
        (self.crate / "Cargo.toml").write_text('[package]\nname = "onlyalpha-sample"\n')
        (self.crate / "src/lib.rs").write_text("")
        self.readme = self.crate / "README.md"
        self.readme.write_text(
            "\n".join(
                "## " + name + "\n说明。"
                for name in ("目的与职责", "边界与依赖", "公开接口", "状态与生命周期", "使用与验证")
            )
        )

    def test_cargo_directories_are_optional_and_supported(self):
        validate_crate_layout(self.root)
        for name in ("tests", "examples", "benches"):
            (self.crate / name).mkdir()
        validate_crate_layout(self.root)

    def test_nonstandard_directory_is_rejected(self):
        for name in ("test", "example", "benchmark", "resources"):
            with self.subTest(name=name):
                path = self.crate / name
                path.mkdir()
                with self.assertRaisesRegex(ValueError, "RUST_CRATE_LAYOUT_INVALID"):
                    validate_crate_layout(self.root)
                path.rmdir()

    def test_missing_or_empty_readme_section_is_rejected(self):
        original = self.readme.read_text()
        for text in ("", original.replace("## 公开接口\n说明。", "## 公开接口\n")):
            self.readme.write_text(text)
            with self.assertRaisesRegex(ValueError, "RUST_CRATE_README_INVALID"):
                validate_crate_layout(self.root)
        self.readme.unlink()
        with self.assertRaisesRegex(ValueError, "RUST_CRATE_README_INVALID"):
            validate_crate_layout(self.root)

    def test_missing_library_or_manifest_is_rejected(self):
        for path in (self.crate / "src/lib.rs", self.crate / "Cargo.toml"):
            content = path.read_text()
            path.unlink()
            with self.assertRaisesRegex(ValueError, "RUST_CRATE_LAYOUT_INVALID"):
                validate_crate_layout(self.root)
            path.write_text(content)

    def test_symlink_directory_cannot_escape_the_layout(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.crate / "tests").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "RUST_CRATE_LAYOUT_INVALID"):
            validate_crate_layout(self.root)

    def test_standalone_unit_tests_keep_the_owning_module(self):
        owner = self.crate / "src/component.rs"
        target = self.crate / "src/component_tests.rs"
        owner.write_text('#[cfg(test)]\n#[path = "component_tests.rs"]\nmod tests;\n')
        target.write_text("use super::*;\n")
        with self.assertRaisesRegex(ValueError, "RUST_CRATE_UNIT_TEST_LAYOUT_INVALID"):
            validate_crate_layout(self.root)
        destination = self.crate / "src/tests/component_tests.rs"
        destination.parent.mkdir(parents=True)
        target.rename(destination)
        owner.write_text('#[cfg(test)]\n#[path = "tests/component_tests.rs"]\nmod tests;\n')
        validate_crate_layout(self.root)
        owner.write_text("#[cfg(test)]\nmod tests { #[test] fn inline_test() {} }\n")
        validate_crate_layout(self.root)

    def test_scattered_module_test_directory_is_rejected(self):
        owner = self.crate / "src/component.rs"
        target = self.crate / "src/component/tests/check.rs"
        target.parent.mkdir(parents=True)
        target.write_text("use super::*;\n")
        owner.write_text('#[cfg(test)]\n#[path = "component/tests/check.rs"]\nmod tests;\n')
        with self.assertRaisesRegex(ValueError, "RUST_CRATE_UNIT_TEST_LAYOUT_INVALID"):
            validate_crate_layout(self.root)

    def test_external_shared_helpers_cannot_hide_private_unit_tests(self):
        owner = self.crate / "src/component.rs"
        shared = self.crate / "tests/support/shared.rs"
        shared.parent.mkdir(parents=True)
        shared.write_text("pub fn helper() {}\n")
        owner.write_text('#[cfg(test)]\n#[path = "../tests/support/shared.rs"]\nmod support;\n')
        validate_crate_layout(self.root)
        shared.write_text("#[test]\nfn private_case() {}\n")
        with self.assertRaisesRegex(ValueError, "RUST_CRATE_UNIT_TEST_LAYOUT_INVALID"):
            validate_crate_layout(self.root)
