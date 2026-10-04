from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("exit_code", (0, 86))
def test_coverage_records_child_branches_even_after_hard_exit(tmp_path: Path, exit_code: int) -> None:
    """Use the repository's real patch policy, without measuring test fixture bytes as Core."""
    policy = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["coverage"]["run"]
    assert policy["source"] == ["src/onlyalpha"]
    assert policy.get("relative_files") is True
    source = tmp_path / "src" / "onlyalpha" / "probe.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import os, sys\n"
        "def choose(code):\n"
        "    if code == 86:\n"
        "        os._exit(code)\n"
        "    return 0\n"
        "choose(int(sys.argv[1]))\n"
    )
    config = tmp_path / ".coveragerc"
    config.write_text(
        "[run]\nbranch = true\nparallel = true\nsource = src/onlyalpha\nrelative_files = true\n"
        f"patch = {', '.join(policy.get('patch', []))}\n"
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys\n"
        f"child = subprocess.run([sys.executable, {str(source)!r}, {str(exit_code)!r}], check=False)\n"
        f"assert child.returncode == {exit_code}\n"
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith(("COVERAGE_", "COV_CORE_", "PYTEST_"))}
    env["COVERAGE_RCFILE"] = str(config)
    env["COVERAGE_FILE"] = str(tmp_path / ".coverage")
    for args in (("run", str(parent)), ("combine",), ("json", "-o", "report.json"), ("xml", "-o", "report.xml")):
        subprocess.run([sys.executable, "-m", "coverage", *args], cwd=tmp_path, env=env, check=True)
    report = json.loads((tmp_path / "report.json").read_text())
    child = report["files"]["src/onlyalpha/probe.py"]
    assert 1 in child["executed_lines"]
    assert [3, 4 if exit_code == 86 else 5] in child["executed_branches"]
    assert [3, 5 if exit_code == 86 else 4] in child["missing_branches"]
    xml = ET.parse(tmp_path / "report.xml").getroot()
    assert [item.text for item in xml.findall("sources/source")] == ["src/onlyalpha"]
    assert [item.attrib["filename"] for item in xml.findall(".//class")] == ["probe.py"]
