"""运行 crates/ 下 Rust 库的 Cargo 单元测试。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        metadata = json.loads(
            subprocess.check_output(["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"], cwd=ROOT)
        )
        members = set(metadata["workspace_members"])
        packages = sorted(
            package["name"]
            for package in metadata["packages"]
            if package["id"] in members and Path(package["manifest_path"]).is_relative_to(ROOT / "crates")
        )
        if not packages:
            parser.error("Cargo 工作区的 crates/ 下没有可运行的包")
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
