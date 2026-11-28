"""运行 crates/ 下 Rust 库的 Cargo 单元测试。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def under_directory(directory: Path, root: Path) -> bool:
    return any(root.samefile(parent) for parent in (directory, *directory.parents))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        metadata = json.loads(
            subprocess.check_output(["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"], cwd=ROOT)
        )
        members = set(metadata["workspace_members"])
        workspace = {p["name"]: p for p in metadata["packages"] if p["id"] in members}
        crates = ROOT / "crates"
        libraries = {}
        for name, package in workspace.items():
            manifest = Path(package["manifest_path"])
            directory = manifest.parent.resolve()
            internal = under_directory(directory, crates)
            if manifest.is_symlink() and under_directory(manifest.resolve().parent, crates) != internal:
                parser.error(f"{name} 的 Cargo.toml 与包目录分处 crates/ 边界两侧：{manifest}")
            if internal:
                libraries[name] = directory
            elif under_directory(manifest.parent, crates):
                parser.error(f"{name} 的实际目录越过 crates/ 边界：{directory}")
        if not libraries:
            parser.error("Cargo 工作区的 crates/ 下没有可运行的包")
        approvals = (metadata["metadata"] or {}).get("approved-third-party-paths", {})
        if not isinstance(approvals, dict):
            parser.error("approved-third-party-paths 必须是实际包名到目录的映射")
        allowed_paths = libraries.copy()
        reserved = [base for base in (ROOT / "crates", ROOT / "packages", ROOT / "plugs") if base.is_dir()]
        for name, relative in approvals.items():
            if not isinstance(relative, str):
                parser.error(f"第三方依赖 {name} 的目录必须是字符串")
            directory = (ROOT / relative).resolve()
            manifest = directory / "Cargo.toml"
            if not manifest.is_file() or os.path.relpath(directory, ROOT) != relative or manifest.is_symlink():
                parser.error(f"第三方依赖 {name} 必须登记真实 Cargo 清单所在目录的规范相对路径：{relative}")
            if any(under_directory(directory, base) for base in reserved):
                parser.error(f"第三方依赖 {name} 的目录属于工程组件：{relative}")
            if name in workspace and not Path(workspace[name]["manifest_path"]).parent.samefile(directory):
                parser.error(f"第三方依赖 {name} 与其他 workspace 成员同名：{relative}")
            allowed_paths[name] = directory
        for name in libraries:
            for dep in workspace[name]["dependencies"]:
                target = dep["name"]
                path = dep.get("path")
                if path is None and (target not in workspace or target in approvals):
                    continue
                if path is None or target not in allowed_paths or not allowed_paths[target].samefile(path):
                    kind = dep["kind"] or "normal"
                    parser.error(f"{name} 的 {kind} 依赖 {target} 未匹配 crates/ 成员或已批准的第三方路径：{path or dep['source']}")
        packages = sorted(libraries)
        return subprocess.run(
            ["cargo", "test", "--locked", "--lib", *(arg for name in packages for arg in ("-p", name))],
            cwd=ROOT,
            check=False,
        ).returncode
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except OSError as exc:
        print(f"无法运行 Cargo：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
