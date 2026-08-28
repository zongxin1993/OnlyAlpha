"""Deterministic governance for the canonical OnlyAlpha Gateway protocol."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from google.protobuf import descriptor_pb2

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "contracts/gateway/v1"
PROTO_PACKAGE_ROOT = Path("onlyalpha_gateway_protocol/v1")
PROJECTION_ROOT = ROOT / "packages/protocol/onlyalpha-gateway-protocol/src"
DESCRIPTOR = PROJECTION_ROOT / PROTO_PACKAGE_ROOT / "descriptor.pb"
EXPECTED_SOURCES = (
    PROTO_PACKAGE_ROOT / "common.proto",
    PROTO_PACKAGE_ROOT / "error.proto",
    PROTO_PACKAGE_ROOT / "gateway.proto",
    PROTO_PACKAGE_ROOT / "identity.proto",
    PROTO_PACKAGE_ROOT / "stream.proto",
)
GENERATED_SUFFIXES = ("_pb2.py", "_pb2.pyi", "_pb2_grpc.py")
PROTOCOL_PACKAGE = "onlyalpha.gateway.v1"
GRPCIO_TOOLS_VERSION = "1.73.1"
GRPCIO_VERSION = "1.73.1"
PROTOBUF_VERSION = "6.33.5"


def _require_toolchain() -> None:
    expected = {
        "grpcio-tools": GRPCIO_TOOLS_VERSION,
        "grpcio": GRPCIO_VERSION,
        "protobuf": PROTOBUF_VERSION,
    }
    mismatches = [
        f"{name}=={actual} (expected {version})"
        for name, version in expected.items()
        if (actual := importlib.metadata.version(name)) != version
    ]
    if mismatches:
        raise ValueError("Gateway protocol toolchain mismatch: " + ", ".join(mismatches))


def canonical_sources(root: Path = CONTRACT_ROOT) -> tuple[Path, ...]:
    sources = tuple(sorted(path.relative_to(root) for path in root.rglob("*.proto")))
    if sources != EXPECTED_SOURCES:
        raise ValueError(f"canonical Gateway v1 sources must be exactly {EXPECTED_SOURCES!r}, got {sources!r}")
    return sources


def _descriptor_path(output_root: Path) -> Path:
    return output_root / PROTO_PACKAGE_ROOT / "descriptor.pb"


def compile_projection(source_root: Path, output_root: Path, sources: Sequence[Path]) -> bytes:
    _require_toolchain()
    output_root.mkdir(parents=True, exist_ok=True)
    descriptor_path = _descriptor_path(output_root)
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{source_root}",
        f"--python_out={output_root}",
        f"--pyi_out={output_root}",
        f"--grpc_python_out={output_root}",
        f"--descriptor_set_out={descriptor_path}",
        "--include_imports",
        *(str(path) for path in sorted(sources)),
    ]
    completed = subprocess.run(command, cwd=source_root, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise ValueError(f"protoc failed: {completed.stderr.strip()}")
    descriptor = descriptor_pb2.FileDescriptorSet.FromString(descriptor_path.read_bytes())
    normalized = descriptor_pb2.FileDescriptorSet()
    for item in sorted(descriptor.file, key=lambda value: value.name):
        normalized.file.add().CopyFrom(item)
    payload = normalized.SerializeToString(deterministic=True)
    descriptor_path.write_bytes(payload)
    return payload


def compile_descriptor(source_root: Path, sources: Sequence[Path]) -> descriptor_pb2.FileDescriptorSet:
    with tempfile.TemporaryDirectory(prefix="onlyalpha-gateway-descriptor-") as raw:
        output = Path(raw) / "projection"
        payload = compile_projection(source_root, output, sources)
    return descriptor_pb2.FileDescriptorSet.FromString(payload)


def _generated_files(root: Path) -> tuple[Path, ...]:
    package = root / PROTO_PACKAGE_ROOT
    if not package.exists():
        return ()
    return tuple(
        sorted(
            path.relative_to(root)
            for path in package.iterdir()
            if path.name == "descriptor.pb" or path.name.endswith(GENERATED_SUFFIXES)
        )
    )


def _validate_contract(descriptor: descriptor_pb2.FileDescriptorSet) -> None:
    packages = {item.package for item in descriptor.file}
    if packages != {PROTOCOL_PACKAGE}:
        raise ValueError(f"Gateway protocol package must be exactly {PROTOCOL_PACKAGE!r}, got {packages!r}")
    services = {f"{item.package}.{service.name}": service for item in descriptor.file for service in item.service}
    expected = {
        "onlyalpha.gateway.v1.GatewayService": {
            "Handshake": (False, False),
            "ApplyTestMutation": (False, False),
        },
        "onlyalpha.gateway.v1.GatewayStreamService": {"WatchTestEvents": (False, True)},
    }
    actual = {
        name: {method.name: (method.client_streaming, method.server_streaming) for method in service.method}
        for name, service in services.items()
    }
    if actual != expected:
        raise ValueError(f"Gateway unary/stream service topology drift: expected {expected!r}, got {actual!r}")


def _generate_temporary() -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    temporary = tempfile.TemporaryDirectory(prefix="onlyalpha-gateway-protocol-")
    root = Path(temporary.name) / "projection"
    payload = compile_projection(CONTRACT_ROOT, root, canonical_sources())
    _validate_contract(descriptor_pb2.FileDescriptorSet.FromString(payload))
    return root, temporary


def write() -> None:
    candidate, temporary = _generate_temporary()
    try:
        expected = _generated_files(candidate)
        for relative in _generated_files(PROJECTION_ROOT):
            if relative not in expected:
                (PROJECTION_ROOT / relative).unlink()
        for relative in expected:
            target = PROJECTION_ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate / relative, target)
    finally:
        temporary.cleanup()


def check() -> str:
    candidate, temporary = _generate_temporary()
    try:
        expected = _generated_files(candidate)
        actual = _generated_files(PROJECTION_ROOT)
        if actual != expected:
            raise ValueError(f"generated Gateway projection file set drift: expected {expected!r}, got {actual!r}")
        drift = [
            relative
            for relative in expected
            if (candidate / relative).read_bytes() != (PROJECTION_ROOT / relative).read_bytes()
        ]
        if drift:
            raise ValueError(f"generated Gateway protocol is stale: {', '.join(map(str, drift))}")
        identity = hashlib.sha256((candidate / PROTO_PACKAGE_ROOT / "descriptor.pb").read_bytes()).hexdigest()
    finally:
        temporary.cleanup()
    return identity


def _walk_messages(
    file: descriptor_pb2.FileDescriptorProto,
) -> dict[str, descriptor_pb2.DescriptorProto]:
    result: dict[str, descriptor_pb2.DescriptorProto] = {}

    def visit(prefix: str, message: descriptor_pb2.DescriptorProto) -> None:
        name = f"{prefix}.{message.name}"
        result[name] = message
        for nested in message.nested_type:
            visit(name, nested)

    for message in file.message_type:
        visit(file.package, message)
    return result


def _walk_enums(file: descriptor_pb2.FileDescriptorProto) -> dict[str, descriptor_pb2.EnumDescriptorProto]:
    result = {f"{file.package}.{enum.name}": enum for enum in file.enum_type}

    def visit_message(prefix: str, message: descriptor_pb2.DescriptorProto) -> None:
        name = f"{prefix}.{message.name}"
        result.update({f"{name}.{enum.name}": enum for enum in message.enum_type})
        for nested in message.nested_type:
            visit_message(name, nested)

    for message in file.message_type:
        visit_message(file.package, message)
    return result


def _reserved_numbers(message: descriptor_pb2.DescriptorProto) -> set[int]:
    return {number for item in message.reserved_range for number in range(item.start, item.end)}


def _reserved_enum_numbers(enum: descriptor_pb2.EnumDescriptorProto) -> set[int]:
    return {number for item in enum.reserved_range for number in range(item.start, item.end + 1)}


def compatibility_errors(
    baseline: descriptor_pb2.FileDescriptorSet,
    candidate: descriptor_pb2.FileDescriptorSet,
) -> tuple[str, ...]:
    errors: list[str] = []
    old_files = {item.name: item for item in baseline.file}
    new_files = {item.name: item for item in candidate.file}
    old_packages = {item.package for item in baseline.file}
    new_packages = {item.package for item in candidate.file}
    if old_packages != {PROTOCOL_PACKAGE} or new_packages != {PROTOCOL_PACKAGE}:
        errors.append(f"protocol package major changed: {sorted(old_packages)!r} -> {sorted(new_packages)!r}")

    old_messages = {name: message for item in baseline.file for name, message in _walk_messages(item).items()}
    new_messages = {name: message for item in candidate.file for name, message in _walk_messages(item).items()}
    for name, old in sorted(old_messages.items()):
        current = new_messages.get(name)
        if current is None:
            errors.append(f"message removed: {name}")
            continue
        current_by_name = {field.name: field for field in current.field}
        current_by_number = {field.number: field for field in current.field}
        for field in old.field:
            replacement = current_by_name.get(field.name)
            if replacement is None:
                reused = current_by_number.get(field.number)
                if reused is None:
                    errors.append(f"field removed: {name}.{field.name} ({field.number})")
                else:
                    errors.append(f"field number reused: {name}.{field.name} ({field.number}) -> {reused.name}")
                continue
            if replacement.number != field.number:
                errors.append(f"field number changed: {name}.{field.name} {field.number} -> {replacement.number}")
            signature = (field.type, field.type_name, field.label)
            replacement_signature = (replacement.type, replacement.type_name, replacement.label)
            if replacement_signature != signature:
                errors.append(f"field type changed: {name}.{field.name}")
        old_reserved_names = set(old.reserved_name)
        old_reserved_numbers = _reserved_numbers(old)
        for field in current.field:
            if field.name in old_reserved_names:
                errors.append(f"reserved field name reused: {name}.{field.name}")
            if field.number in old_reserved_numbers:
                errors.append(f"reserved field number reused: {name}.{field.number}")

    old_enums = {name: enum for item in baseline.file for name, enum in _walk_enums(item).items()}
    new_enums = {name: enum for item in candidate.file for name, enum in _walk_enums(item).items()}
    for name, old in sorted(old_enums.items()):
        current = new_enums.get(name)
        if current is None:
            errors.append(f"enum removed: {name}")
            continue
        current_by_name = {value.name: value for value in current.value}
        current_by_number: dict[int, list[str]] = {}
        for value in current.value:
            current_by_number.setdefault(value.number, []).append(value.name)
        for value in old.value:
            replacement = current_by_name.get(value.name)
            if replacement is None:
                reused = current_by_number.get(value.number)
                if reused is None:
                    errors.append(f"enum value removed: {name}.{value.name} ({value.number})")
                else:
                    errors.append(
                        f"enum value number reused: {name}.{value.name} ({value.number}) -> {sorted(reused)!r}"
                    )
                continue
            if replacement.number != value.number:
                errors.append(f"enum value number changed: {name}.{value.name} {value.number} -> {replacement.number}")
        old_reserved_names = set(old.reserved_name)
        old_reserved_numbers = _reserved_enum_numbers(old)
        for value in current.value:
            if value.name in old_reserved_names:
                errors.append(f"reserved enum value name reused: {name}.{value.name}")
            if value.number in old_reserved_numbers:
                errors.append(f"reserved enum value number reused: {name}.{value.number}")

    for file_name, old_file in sorted(old_files.items()):
        current_file = new_files.get(file_name)
        if current_file is None:
            errors.append(f"proto file removed: {file_name}")
            continue
        current_services = {service.name: service for service in current_file.service}
        for service in old_file.service:
            current_service = current_services.get(service.name)
            if current_service is None:
                errors.append(f"service removed: {old_file.package}.{service.name}")
                continue
            current_methods = {method.name: method for method in current_service.method}
            for method in service.method:
                replacement = current_methods.get(method.name)
                qualified = f"{old_file.package}.{service.name}.{method.name}"
                if replacement is None:
                    errors.append(f"RPC removed: {qualified}")
                elif (
                    replacement.input_type,
                    replacement.output_type,
                    replacement.client_streaming,
                    replacement.server_streaming,
                ) != (
                    method.input_type,
                    method.output_type,
                    method.client_streaming,
                    method.server_streaming,
                ):
                    errors.append(f"RPC signature changed: {qualified}")
    return tuple(sorted(set(errors)))


def _extract_baseline(base: str, destination: Path) -> tuple[Path, ...]:
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("compatibility base must be an immutable 40-character lowercase Git SHA")
    verified = subprocess.run(
        ["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=ROOT, check=False, capture_output=True, text=True
    )
    if verified.returncode:
        raise ValueError(f"compatibility base is not a Git commit: {base}")
    prefix = CONTRACT_ROOT.relative_to(ROOT).as_posix() + "/"
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", base, "--", str(CONTRACT_ROOT.relative_to(ROOT))],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = tuple(
        sorted(Path(line.removeprefix(prefix)) for line in listing.stdout.splitlines() if line.endswith(".proto"))
    )
    for relative in paths:
        content = subprocess.run(
            ["git", "show", f"{base}:{prefix}{relative.as_posix()}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return paths


def verify(base: str) -> tuple[str, tuple[str, ...]]:
    identity = check()
    current = compile_descriptor(CONTRACT_ROOT, canonical_sources())
    with tempfile.TemporaryDirectory(prefix="onlyalpha-gateway-baseline-") as raw:
        baseline_root = Path(raw)
        baseline_sources = _extract_baseline(base, baseline_root)
        if not baseline_sources:
            return identity, ()
        baseline = compile_descriptor(baseline_root, baseline_sources)
    return identity, compatibility_errors(baseline, current)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Govern the canonical OnlyAlpha Gateway protocol")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("write")
    subparsers.add_parser("check")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            write()
            identity = check()
            print(f"GATEWAY PROTOCOL WRITTEN: {identity}")
        elif args.command == "check":
            print(f"GATEWAY PROTOCOL CURRENT: {check()}")
        else:
            identity, errors = verify(args.base)
            if errors:
                raise ValueError("incompatible Gateway protocol:\n" + "\n".join(f"- {item}" for item in errors))
            print(f"GATEWAY PROTOCOL COMPATIBLE: {identity}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"GATEWAY PROTOCOL FAILED: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
