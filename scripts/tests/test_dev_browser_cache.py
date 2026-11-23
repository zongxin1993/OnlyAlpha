"""复用浏览器缓存必须同时匹配锁定工具版本、完成标记和文件字节。"""

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import dev_verification as verification
from scripts.dev_browser_cache import inspect_cache, validate_reuse, verify_cache
from scripts.dev_verification import IMAGE, browser_cache_build_arguments


class BrowserCache(unittest.TestCase):
    def fixture(self, root):
        package = root / "package"
        package.mkdir()
        (package / "package.json").write_text(json.dumps({"version": "1.62.1"}))
        entries = []
        for name, revision, prefix, exe in [
            ("chromium", "1234", "chromium", "chrome-linux/chrome"),
            ("chromium-headless-shell", "1234", "chromium_headless_shell", "chrome-linux/headless_shell"),
            ("ffmpeg", "1011", "ffmpeg", "ffmpeg-linux"),
        ]:
            entries.append(dict(name=name, revision=revision, browserVersion="151.0.7922.34"))
            folder = root / "cache" / f"{prefix}-{revision}"
            folder.mkdir(parents=True)
            (folder / "INSTALLATION_COMPLETE").touch()
            binary = folder / exe
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(b"controlled binary")
            binary.chmod(0o755)
        (package / "browsers.json").write_text(json.dumps({"browsers": entries}))
        front = root / "packages/frontend"
        front.mkdir(parents=True)
        (front / "package.json").write_text("{}")
        (front / "package-lock.json").write_text(
            json.dumps({"packages": {"node_modules/playwright-core": {"version": "1.62.1"}}})
        )
        env = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in front.iterdir()}
        return package, env

    def test_matching_cache_and_lock_are_accepted_but_changed_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            package, env = self.fixture(root)
            data = inspect_cache(root / "cache", package)
            validate_reuse(root, env, data)
            verify_cache(root / "cache", package, data["tree_sha256"], "1.62.1")
            (root / "cache/chromium-1234/chrome-linux/chrome").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "IDENTITY"):
                verify_cache(root / "cache", package, data["tree_sha256"], "1.62.1")

    def test_different_lock_or_incomplete_installation_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            package, env = self.fixture(root)
            data = inspect_cache(root / "cache", package)
            with self.assertRaises(ValueError):
                validate_reuse(root, {}, data)
            with self.assertRaises(ValueError):
                validate_reuse(root, env, dict(data, playwright_version="wrong"))
            (root / "cache/chromium-1234/INSTALLATION_COMPLETE").unlink()
            with self.assertRaisesRegex(ValueError, "INCOMPLETE"):
                inspect_cache(root / "cache", package)

    def test_prepare_pins_verified_image_and_refuses_wrong_owner(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            package, env = self.fixture(root)
            data = inspect_cache(root / "cache", package)
            (root / "scripts").mkdir()
            (root / "scripts/dev_browser_cache.py").write_text("# controlled input")
            image = "sha256:" + "a" * 64
            calls = []

            def output(command, **kwargs):
                calls.append(command)
                if command[:3] == ["docker", "image", "inspect"]:
                    if command[-1] == IMAGE:
                        return json.dumps([{"Id": image}])
                    raise subprocess.CalledProcessError(1, command)
                if command[:2] == ["docker", "run"]:
                    return json.dumps(dict(data, admitted_environment=env))
                raise AssertionError(command)

            with (
                patch("scripts.dev_verification.subprocess.check_output", output),
                patch("scripts.dev_verification.subprocess.run") as run,
            ):
                args = browser_cache_build_arguments(root, {"Image": image}, "operation")
                self.assertIn("ONLYALPHA_DEV_BROWSER_SOURCE=playwright-cached", args)
                self.assertIn("ONLYALPHA_DEV_BROWSER_CACHE_SHA256=" + data["tree_sha256"], args)
                self.assertEqual(run.call_args.args[0][:3], ["docker", "tag", image])
                self.assertIn("--read-only", next(c for c in calls if c[:2] == ["docker", "run"]))
                with self.assertRaisesRegex(ValueError, "IMAGE_IDENTITY"):
                    browser_cache_build_arguments(root, {"Image": "foreign"}, "other")

    def test_interrupted_cache_inspection_preserves_lifecycle_fence(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            reservation = {"operation_id": "operation"}

            def output(command, **kwargs):
                if command[:2] == ["docker", "ps"]:
                    return "container\n"
                return json.dumps([{"Id": "container", "Image": "image", "State": {"Running": True}}])

            def cache(*args):
                self.assertFalse(reservation["completed"])
                raise subprocess.TimeoutExpired("cache inspection", 120)

            with (
                patch.object(verification, "ROOT", root),
                patch.object(verification, "freeze_source", return_value={}),
                patch.object(verification, "validate_container"),
                patch.object(verification.subprocess, "check_output", output),
                patch.object(verification.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
                patch.object(verification, "browser_cache_build_arguments", cache),
            ):
                with self.assertRaises(subprocess.TimeoutExpired):
                    verification.run_host(
                        "prepare", [], web=False, rebuild=True, reservation=reservation, reuse_browser_cache=True
                    )
                self.assertFalse(reservation["completed"])

    def test_external_symlink_in_cache_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            package, _ = self.fixture(root)
            (root / "cache/escape").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(ValueError, "SYMLINK"):
                inspect_cache(root / "cache", package)


if __name__ == "__main__":
    unittest.main()
