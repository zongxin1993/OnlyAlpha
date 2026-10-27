"""Runtime image preflight and assembly, using the shared native manifest."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import release_inputs
from scripts.dev_verification import source_inputs
from scripts.runtime_artifacts import encode, seal


def preflight(root: Path, output: Path, *, selection_dir: Path | None, digest: str) -> dict[str, Any]:
    if bool(selection_dir) != bool(digest):
        raise ValueError("RELEASE_INPUT_EXPLICIT_SELECTION_REQUIRED")
    inputs = release_inputs.candidate(root)["source_inputs"]
    selection = (
        None
        if selection_dir is None
        else release_inputs.selected(root, selection_dir / "inputs.json", digest, selection_dir / "sources.json")
    )
    receipt = {"source_inputs": inputs, "release_inputs": selection}
    with output.open("xb") as target:
        target.write(encode(receipt))
    return receipt


def finish(root: Path, artifact: Path, receipt: Path, *, selection_dir: Path | None, digest: str) -> dict[str, Any]:
    captured = json.loads(receipt.read_bytes())
    if set(captured) != {"source_inputs", "release_inputs"} or source_inputs(root) != captured["source_inputs"]:
        raise ValueError("RUNTIME_BUILD_SOURCE_CHANGED")
    selection = (
        None
        if selection_dir is None
        else release_inputs.selected(root, selection_dir / "inputs.json", digest, selection_dir / "sources.json")
    )
    if selection != captured["release_inputs"] or bool(selection_dir) != bool(digest):
        raise ValueError("RUNTIME_BUILD_SELECTION_CHANGED")
    return seal(root, artifact, captured["source_inputs"], selection)


def build_image(root: Path, command: list[str], reservation: dict[str, Any]) -> int:
    """Called only under dev_verification's host lock, source freeze and worker probe."""
    parser = argparse.ArgumentParser(description="Build the sole fixed runtime dev image, never start it")
    parser.add_argument("--release-inputs", type=Path, required=True)
    parser.add_argument("--release-inputs-sha256", required=True)
    parser.add_argument("--source-bundles", type=Path, required=True)
    args = parser.parse_args(command)
    selection = release_inputs.selected(root, args.release_inputs, args.release_inputs_sha256, args.source_bundles)
    inputs = source_inputs(root)
    cut = root / ".test-cache/dev-source-cut"
    if source_inputs(cut) != inputs:
        raise ValueError("RUNTIME_BUILD_FROZEN_SOURCE_REQUIRED")
    directory = cut / "test-results/runtime-build-inputs" / reservation["operation_id"]
    directory.mkdir(parents=True)
    shutil.copyfile(args.release_inputs, directory / "inputs.json")
    references = json.loads(args.source_bundles.read_text())
    copied = {}
    for unit, reference in sorted(references.items()):
        original = Path(reference["path"])
        if not original.is_absolute():
            original = args.source_bundles.parent / original
        target = directory / (unit + ".zip")
        shutil.copyfile(original, target)
        copied[unit] = {"path": target.name, "sha256": reference["sha256"]}
    (directory / "sources.json").write_bytes(encode(copied))
    if (
        release_inputs.selected(cut, directory / "inputs.json", args.release_inputs_sha256, directory / "sources.json")
        != selection
    ):
        raise ValueError("RUNTIME_BUILD_CAPTURE_CHANGED")
    output = root / "test-results/runtime-image" / reservation["operation_id"]
    output.mkdir(parents=True)
    image = "onlyalpha-runtime:dev"
    previous = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True, check=False)
    consumers = subprocess.check_output(
        ["docker", "ps", "-a", "--filter", "ancestor=" + image, "--format", "{{json .}}"], text=True
    )
    (output / "previous-image.json").write_text(previous.stdout or "[]")
    (output / "image-consumers.jsonl").write_text(consumers)
    reservation["completed"] = False
    with (output / "build.log").open("x") as log:
        subprocess.run(
            [
                "docker",
                "build",
                "--file",
                str(cut / "deploy/Dockerfile.dev"),
                "--target",
                "runtime",
                "--tag",
                image,
                "--build-arg",
                "ONLYALPHA_RELEASE_INPUTS_SHA256=" + args.release_inputs_sha256,
                "--build-arg",
                "ONLYALPHA_RELEASE_INPUTS_DIR=" + str(directory.relative_to(cut)),
                str(cut),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    image_record = json.loads(subprocess.check_output(["docker", "image", "inspect", image], text=True))[0]
    if source_inputs(root) != inputs or source_inputs(cut) != inputs:
        raise ValueError("RUNTIME_BUILD_SOURCE_CHANGED")
    (output / "image.json").write_bytes(
        encode({"image_id": image_record["Id"], "release_inputs": selection, "source_inputs": inputs})
    )
    reservation["completed"] = True
    print("RUNTIME_IMAGE_BUILD_PASS", image_record["Id"], str(output), flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "seal"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--selection-dir", default="")
    parser.add_argument("--sha256", default="")
    args = parser.parse_args()
    selection_dir = Path(args.selection_dir) if args.selection_dir else None
    if selection_dir is not None and not selection_dir.is_absolute():
        selection_dir = args.root / selection_dir
    if args.mode == "preflight":
        preflight(args.root, args.receipt, selection_dir=selection_dir, digest=args.sha256)
    elif args.artifact is None:
        parser.error("seal requires --artifact")
    else:
        finish(args.root, args.artifact, args.receipt, selection_dir=selection_dir, digest=args.sha256)


if __name__ == "__main__":
    main()
