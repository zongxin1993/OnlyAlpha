"""Separate immutable capture evidence and canonical semantic reference storage."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from onlyalpha_market_binance_spot.reference import OnlyBinanceSpotReferenceAuthority

from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment
from onlyalpha_plugin_binance.errors import OnlyBinanceReferenceStoreError
from onlyalpha_plugin_binance.spot.reference.capture import OnlyBinanceSpotReferenceCapture


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotReferencePublication:
    capture_fingerprint: str
    semantic_reference_fingerprint: str
    capture_created: bool
    reference_created: bool
    compatibility_status: str
    symbols: tuple[str, ...]
    captured_at: datetime


class OnlyBinanceSpotReferenceStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def publish(self, capture: OnlyBinanceSpotReferenceCapture) -> OnlyBinanceSpotReferencePublication:
        capture_created = self._publish_capture(capture)
        reference_created = self._publish_reference(capture)
        authority = capture.authority
        compatible = authority.compatibility_status.value == "COMPATIBLE" and all(
            item.compatibility_status.value == "COMPATIBLE" for item in authority.references
        )
        return OnlyBinanceSpotReferencePublication(
            capture.capture_fingerprint,
            authority.identity.authority_fingerprint,
            capture_created,
            reference_created,
            "COMPATIBLE" if compatible else "INCOMPATIBLE",
            tuple(item.raw_symbol for item in authority.references),
            capture.captured_at,
        )

    def load_capture_verified(self, capture_fingerprint: str) -> OnlyBinanceSpotReferenceCapture:
        target = self._root / "captures" / capture_fingerprint
        if not target.is_dir():
            raise OnlyBinanceReferenceStoreError("BINANCE_CAPTURE_NOT_FOUND")
        try:
            manifest = _read_object(target / "manifest.json")
            if (
                set(manifest)
                != {
                    "schema_version",
                    "capture_fingerprint",
                    "semantic_reference_fingerprint",
                    "provenance",
                    "evidence",
                }
                or manifest["schema_version"] != 1
            ):
                raise ValueError("capture manifest schema")
            provenance = manifest["provenance"]
            evidence = manifest["evidence"]
            if not isinstance(provenance, dict) or not isinstance(evidence, list) or len(evidence) != 2:
                raise ValueError("capture manifest shape")
            raw_by_endpoint: dict[str, bytes] = {}
            for item in evidence:
                if not isinstance(item, dict):
                    raise ValueError("capture evidence shape")
                endpoint = _required_text(item, "endpoint_id")
                filename = _required_text(item, "filename")
                raw = (target / filename).read_bytes()
                if sha256(raw).hexdigest() != _required_text(item, "raw_sha256"):
                    raise OnlyBinanceReferenceStoreError("BINANCE_CAPTURE_RAW_CORRUPT")
                raw_by_endpoint[endpoint] = raw
            capture = OnlyBinanceSpotReferenceCapture.create(
                raw_by_endpoint["/api/v3/exchangeInfo"],
                raw_by_endpoint["/api/v3/executionRules"],
                datetime.fromisoformat(_required_text(provenance, "captured_at_utc")),
                environment=OnlyBinanceEnvironment(_required_text(provenance, "environment")),
                requested_symbols=_text_list(provenance, "requested_symbols"),
                parser_contract_version=_required_text(provenance, "parser_contract_version"),
            )
            expected_provenance = {
                "schema_version": capture.provenance.schema_version,
                "provider": capture.provenance.provider,
                "product": capture.provenance.product,
                "environment": capture.provenance.environment.value,
                "captured_at_utc": capture.provenance.captured_at_utc.isoformat(),
                "parser_contract_version": capture.provenance.parser_contract_version,
                "requested_symbols": list(capture.provenance.requested_symbols),
                "server_time": capture.provenance.server_time,
            }
            if provenance != expected_provenance:
                raise OnlyBinanceReferenceStoreError("BINANCE_CAPTURE_PROVENANCE_CORRUPT")
            for manifest_item, actual in zip(evidence, capture.evidence, strict=True):
                if manifest_item.get("request_parameters") != [list(pair) for pair in actual.request_parameters]:
                    raise OnlyBinanceReferenceStoreError("BINANCE_CAPTURE_REQUEST_CORRUPT")
        except OnlyBinanceReferenceStoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OnlyBinanceReferenceStoreError("BINANCE_CAPTURE_CORRUPT") from exc
        if (
            capture.capture_fingerprint != capture_fingerprint
            or manifest["capture_fingerprint"] != capture_fingerprint
            or manifest["semantic_reference_fingerprint"] != capture.authority.identity.authority_fingerprint
        ):
            raise OnlyBinanceReferenceStoreError("BINANCE_CAPTURE_FINGERPRINT_MISMATCH")
        return capture

    def load_reference_verified(self, authority_fingerprint: str) -> OnlyBinanceSpotReferenceAuthority:
        target = self._root / "references" / authority_fingerprint
        if not target.is_dir():
            raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_NOT_FOUND")
        try:
            manifest = _read_object(target / "manifest.json")
            if (
                set(manifest)
                != {
                    "schema_version",
                    "authority_fingerprint",
                    "observed_at",
                    "semantic_sha256",
                }
                or manifest["schema_version"] != 1
            ):
                raise ValueError("reference manifest schema")
            semantic_bytes = (target / "reference.json").read_bytes()
            if sha256(semantic_bytes).hexdigest() != _required_text(manifest, "semantic_sha256"):
                raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_SEMANTIC_CORRUPT")
            semantic = json.loads(semantic_bytes)
            if not isinstance(semantic, dict):
                raise ValueError("reference semantic object")
            authority = OnlyBinanceSpotReferenceAuthority.from_semantic_dict(
                semantic,
                observed_at=datetime.fromisoformat(_required_text(manifest, "observed_at")),
            )
        except OnlyBinanceReferenceStoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_CORRUPT") from exc
        if (
            authority.identity.authority_fingerprint != authority_fingerprint
            or manifest["authority_fingerprint"] != authority_fingerprint
        ):
            raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_FINGERPRINT_MISMATCH")
        return authority

    def _publish_capture(self, capture: OnlyBinanceSpotReferenceCapture) -> bool:
        target = self._root / "captures" / capture.capture_fingerprint
        if target.exists():
            loaded = self.load_capture_verified(capture.capture_fingerprint)
            if loaded != capture:
                raise OnlyBinanceReferenceStoreError("BINANCE_CAPTURE_CONFLICT")
            return False
        evidence_manifest = []
        filenames = ("exchangeInfo.json", "executionRules.json")
        files: dict[str, bytes] = {}
        for item, filename in zip(capture.evidence, filenames, strict=True):
            files[filename] = item.raw_bytes
            evidence_manifest.append(
                {
                    "endpoint_id": item.endpoint_id,
                    "request_parameters": [list(pair) for pair in item.request_parameters],
                    "filename": filename,
                    "raw_sha256": item.raw_sha256,
                }
            )
        provenance = capture.provenance
        manifest = {
            "schema_version": 1,
            "capture_fingerprint": capture.capture_fingerprint,
            "semantic_reference_fingerprint": capture.authority.identity.authority_fingerprint,
            "provenance": {
                "schema_version": provenance.schema_version,
                "provider": provenance.provider,
                "product": provenance.product,
                "environment": provenance.environment.value,
                "captured_at_utc": provenance.captured_at_utc.isoformat(),
                "parser_contract_version": provenance.parser_contract_version,
                "requested_symbols": list(provenance.requested_symbols),
                "server_time": provenance.server_time,
            },
            "evidence": evidence_manifest,
        }
        created = self._publish_directory(target, files, manifest)
        if not created and self.load_capture_verified(capture.capture_fingerprint) != capture:
            raise OnlyBinanceReferenceStoreError("BINANCE_CAPTURE_CONFLICT")
        return created

    def _publish_reference(self, capture: OnlyBinanceSpotReferenceCapture) -> bool:
        fingerprint = capture.authority.identity.authority_fingerprint
        target = self._root / "references" / fingerprint
        semantic_bytes = _canonical_json_bytes(capture.authority.to_semantic_dict())
        if target.exists():
            loaded = self.load_reference_verified(fingerprint)
            if _canonical_json_bytes(loaded.to_semantic_dict()) != semantic_bytes:
                raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_SEMANTIC_CONFLICT")
            return False
        manifest = {
            "schema_version": 1,
            "authority_fingerprint": fingerprint,
            "observed_at": capture.captured_at.isoformat(),
            "semantic_sha256": sha256(semantic_bytes).hexdigest(),
        }
        created = self._publish_directory(target, {"reference.json": semantic_bytes}, manifest)
        if not created:
            loaded = self.load_reference_verified(fingerprint)
            if _canonical_json_bytes(loaded.to_semantic_dict()) != semantic_bytes:
                raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_SEMANTIC_CONFLICT")
        return created

    def _publish_directory(self, target: Path, files: dict[str, bytes], manifest: dict[str, object]) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        try:
            for name, payload in files.items():
                (stage / name).write_bytes(payload)
            (stage / "manifest.json").write_bytes(_canonical_json_bytes(manifest))
            try:
                stage.rename(target)
            except FileExistsError:
                return False
            return True
        finally:
            if stage.exists():
                for item in stage.iterdir():
                    item.unlink()
                stage.rmdir()


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _required_text(raw: dict[str, object], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} text required")
    return value


def _text_list(raw: dict[str, object], name: str) -> tuple[str, ...]:
    value = raw.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} text list required")
    return tuple(value)
