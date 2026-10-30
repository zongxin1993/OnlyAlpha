"""Build the native Shipping resources in the canonical frozen tool environment."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import release_inputs
from scripts.build_algorithm_sdk import install
from scripts.dev_verification import CUT_METADATA, source_inputs
from scripts.native_http_contract import native_executable
from scripts.runtime_artifacts import BUILD_ENVIRONMENT, seal
from scripts.runtime_artifacts import verify_artifacts as verify_artifacts

ROOT = Path(__file__).resolve().parents[1]


def web_environment(environment: dict[str, str]) -> dict[str, str]:
    return {**{key: value for key, value in environment.items() if not key.startswith("VITE_")}, **BUILD_ENVIRONMENT}


def build(
    directory: Path,
    *,
    release_input_path: Path | None = None,
    release_input_sha256: str | None = None,
    source_bundles_path: Path | None = None,
) -> dict[str, Any]:
    operation = os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    cut = json.loads((ROOT / CUT_METADATA).read_text())
    inputs = source_inputs(ROOT)
    if cut["operation_id"] != operation or cut["inputs"] != inputs or directory.exists() or not directory.is_absolute():
        raise ValueError("NATIVE_BUILD_FROZEN_INPUT_REQUIRED")
    if (release_input_path is None) != (release_input_sha256 is None) or (
        source_bundles_path is not None and release_input_path is None
    ):
        raise ValueError("RELEASE_INPUT_EXPLICIT_SELECTION_REQUIRED")
    selection = None
    if release_input_path is not None and release_input_sha256 is not None:
        selection = release_inputs.selected(ROOT, release_input_path, release_input_sha256, source_bundles_path)
    directory.mkdir(parents=True)
    (directory / "bin").mkdir()
    shutil.copy2(native_executable(), directory / "bin/onlyalpha-backend")
    from scripts.embed_build_provenance import resolve_build_provenance_bytes

    (directory / "source-provenance.json").write_bytes(resolve_build_provenance_bytes(ROOT))
    artifact = install(directory / "wheels", directory / "algorithms")
    from scripts.build_agent_service import install as install_agent

    install_agent(directory / "agent")
    (directory / "algorithm-artifact.sha256").write_text(artifact + "\n")
    with (directory / "web-build.log").open("w") as log:
        result = subprocess.run(
            ["npm", "run", "build", "--", "--outDir", str(directory / "web"), "--emptyOutDir"],
            cwd=ROOT / "packages/frontend",
            env=web_environment(dict(os.environ)),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    result.check_returncode()
    shutil.copytree(ROOT / "database/postgres/migrations", directory / "schema")
    if source_inputs(ROOT) != inputs:
        raise ValueError("NATIVE_BUILD_SOURCE_CHANGED")
    if release_input_path is not None and release_input_sha256 is not None:
        if (
            release_inputs.verify(ROOT, release_input_path, release_input_sha256, source_bundles=source_bundles_path)
            != selection
        ):
            raise ValueError("RELEASE_INPUT_CHANGED_DURING_BUILD")
    return seal(ROOT, directory, inputs, selection)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-inputs", type=Path)
    parser.add_argument("--release-inputs-sha256")
    parser.add_argument("--source-bundles", type=Path)
    args = parser.parse_args()
    directory = ROOT / "test-results/native-workstation" / os.environ["ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"]
    manifest = build(
        directory,
        release_input_path=args.release_inputs,
        release_input_sha256=args.release_inputs_sha256,
        source_bundles_path=args.source_bundles,
    )
    print(
        json.dumps(
            {
                "artifact_root": str(directory),
                "version": manifest["version"],
                "algorithm_artifact": manifest["algorithm_artifact"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
