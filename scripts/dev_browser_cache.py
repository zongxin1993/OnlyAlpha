"""固定工具镜像的浏览器缓存校验；不下载、安装或修改缓存。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


def inspect_cache(root: Path, package: Path) -> dict:
    version = json.loads((package / "package.json").read_text())["version"]
    browsers = {r["name"]: r for r in json.loads((package / "browsers.json").read_text())["browsers"]}
    required = []
    for name, prefix, executable in [
        ("chromium", "chromium", "chrome-linux/chrome"),
        ("chromium-headless-shell", "chromium_headless_shell", "chrome-linux/headless_shell"),
        ("ffmpeg", "ffmpeg", "ffmpeg-linux"),
    ]:
        row = browsers[name]
        folder = root / (prefix + "-" + row["revision"])
        binary = folder / executable
        if (
            not (folder / "INSTALLATION_COMPLETE").is_file()
            or not binary.is_file()
            or not binary.stat().st_mode & 0o111
        ):
            raise ValueError("DEV_BROWSER_CACHE_INCOMPLETE")
        required.append({key: row.get(key) for key in ("name", "revision", "browserVersion")})
    files = []
    size = 0
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        row = {"path": path.relative_to(root).as_posix(), "mode": stat.S_IMODE(metadata.st_mode)}
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("DEV_BROWSER_CACHE_EXTERNAL_SYMLINK")
            row.update(kind="link", target=os.readlink(path))
        elif path.is_file():
            h = hashlib.sha256()
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    h.update(block)
            row.update(kind="file", sha256=h.hexdigest(), bytes=metadata.st_size)
            size += metadata.st_size
        elif path.is_dir():
            row.update(kind="directory")
        else:
            raise ValueError("DEV_BROWSER_CACHE_SPECIAL_FILE")
        files.append(row)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return dict(
        schema_version=1,
        playwright_version=version,
        browsers=required,
        tree_sha256=digest,
        entries=len(files),
        bytes=size,
    )


def validate_reuse(root: Path, admitted_environment: dict, inspection: dict) -> None:
    for name in ("package.json", "package-lock.json"):
        key = "packages/frontend/" + name
        if admitted_environment.get(key) != hashlib.sha256((root / key).read_bytes()).hexdigest():
            raise ValueError("DEV_BROWSER_CACHE_TOOL_INPUT_MISMATCH")
    locked = json.loads((root / "packages/frontend/package-lock.json").read_text())["packages"][
        "node_modules/playwright-core"
    ]["version"]
    if inspection.get("schema_version") != 1 or inspection.get("playwright_version") != locked:
        raise ValueError("DEV_BROWSER_CACHE_VERSION_MISMATCH")


def verify_cache(root: Path, package: Path, expected_tree: str, expected_version: str) -> None:
    actual = inspect_cache(root, package)
    if actual["tree_sha256"] != expected_tree or actual["playwright_version"] != expected_version:
        raise ValueError("DEV_BROWSER_CACHE_IDENTITY_MISMATCH")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/ms-playwright"))
    parser.add_argument(
        "--package", type=Path, default=Path("/workspace/packages/frontend/node_modules/playwright-core")
    )
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--expect-tree")
    parser.add_argument("--expect-version")
    args = parser.parse_args()
    if args.expect_tree or args.expect_version:
        if not args.expect_tree or not args.expect_version:
            parser.error("both expected identities required")
        verify_cache(args.root, args.package, args.expect_tree, args.expect_version)
    data = inspect_cache(args.root, args.package)
    if args.environment:
        data["admitted_environment"] = json.loads(args.environment.read_text())
    print(json.dumps(data, sort_keys=True))


if __name__ == "__main__":
    main()
