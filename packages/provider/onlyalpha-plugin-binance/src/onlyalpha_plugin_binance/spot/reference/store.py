"""Atomic immutable raw-evidence store with verified semantic replay."""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from onlyalpha_plugin_binance.errors import OnlyBinanceReferenceStoreError
from onlyalpha_plugin_binance.spot.reference.capture import OnlyBinanceSpotReferenceCapture


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotReferencePublication:
    raw_capture_fingerprints: tuple[str, ...]
    semantic_reference_fingerprint: str
    created: bool
    compatibility_status: str
    symbols: tuple[str, ...]
    observed_at: datetime


class OnlyBinanceSpotReferenceStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, capture: OnlyBinanceSpotReferenceCapture) -> bool:
        fingerprint = capture.authority.identity.authority_fingerprint
        target = self._root / fingerprint
        if target.exists():
            loaded = self.load_verified(fingerprint)
            if loaded.authority.identity != capture.authority.identity:
                raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_SEMANTIC_CONFLICT")
            return False
        self._root.mkdir(parents=True, exist_ok=True)
        stage = self._root / f".{fingerprint}.{os.getpid()}.tmp"
        try:
            stage.mkdir()
            (stage / "exchangeInfo.json").write_bytes(capture.exchange_info)
            (stage / "executionRules.json").write_bytes(capture.execution_rules)
            manifest = {
                "schema_version": 1,
                "authority_fingerprint": fingerprint,
                "captured_at": capture.captured_at.isoformat(),
                "exchange_info_fingerprint": capture.exchange_info_fingerprint,
                "execution_rules_fingerprint": capture.execution_rules_fingerprint,
            }
            (stage / "manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
            )
            stage.rename(target)
        except FileExistsError:
            if stage.exists():
                for item in stage.iterdir():
                    item.unlink()
                stage.rmdir()
            return self.put(capture)
        return True

    def publish(self, capture: OnlyBinanceSpotReferenceCapture) -> OnlyBinanceSpotReferencePublication:
        created = self.put(capture)
        references = capture.authority.references
        compatibility = "COMPATIBLE" if all(item.trade_eligible for item in references) else "INCOMPATIBLE"
        return OnlyBinanceSpotReferencePublication(
            (capture.exchange_info_fingerprint, capture.execution_rules_fingerprint),
            capture.authority.identity.authority_fingerprint,
            created,
            compatibility,
            tuple(item.raw_symbol for item in references),
            capture.captured_at,
        )

    def load_verified(self, fingerprint: str) -> OnlyBinanceSpotReferenceCapture:
        target = self._root / fingerprint
        if not target.is_dir():
            raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_NOT_FOUND")
        try:
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            exchange, execution = (
                (target / "exchangeInfo.json").read_bytes(),
                (target / "executionRules.json").read_bytes(),
            )
            if (
                sha256(exchange).hexdigest() != manifest["exchange_info_fingerprint"]
                or sha256(execution).hexdigest() != manifest["execution_rules_fingerprint"]
            ):
                raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_RAW_CORRUPT")
            capture = OnlyBinanceSpotReferenceCapture.create(
                exchange, execution, datetime.fromisoformat(manifest["captured_at"])
            )
        except OnlyBinanceReferenceStoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_CORRUPT") from exc
        if (
            capture.authority.identity.authority_fingerprint != fingerprint
            or manifest["authority_fingerprint"] != fingerprint
        ):
            raise OnlyBinanceReferenceStoreError("BINANCE_REFERENCE_SEMANTIC_CORRUPT")
        return capture
