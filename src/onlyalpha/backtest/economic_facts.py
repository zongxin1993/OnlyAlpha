"""Immutable economic-fact payloads bound to Dataset economic manifests."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.data.models import OnlyMarketDataInboundUpdate
from onlyalpha.research.dataset import OnlyResearchDatasetEconomicBinding

from .dataset_source import OnlyBacktestEconomicFactReader


class OnlyBacktestEconomicFactStore(OnlyBacktestEconomicFactReader):
    def __init__(self, root: Path) -> None:
        self._root = root / "backtest" / "economic-facts" / "sha256"

    def publish(
        self,
        binding: OnlyResearchDatasetEconomicBinding,
        updates: tuple[OnlyMarketDataInboundUpdate, ...],
    ) -> None:
        ordered = tuple(sorted(updates, key=_order_key))
        self._verify_binding(binding, ordered)
        target = self._target(binding.fingerprint)
        if target.exists() or target.is_symlink():
            if self.load_for_binding(binding.fingerprint) != ordered:
                raise ValueError("BACKTEST_ECONOMIC_FACT_CONFLICT")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            payload = {
                "schema_version": 1,
                "dataset_binding_fingerprint": binding.fingerprint,
                "updates": [item.to_dict() for item in ordered],
            }
            path = stage / "facts.json"
            with path.open("x", encoding="utf-8") as stream:
                stream.write(only_canonical_json(payload))
                stream.flush()
                os.fsync(stream.fileno())
            self._read(target=stage, binding_fingerprint=binding.fingerprint)
            directory = os.open(stage, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
            if self.load_for_binding(binding.fingerprint) != ordered:
                raise ValueError("BACKTEST_ECONOMIC_FACT_CORRUPT")
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def load_for_binding(self, binding_fingerprint: str) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        return self._read(target=self._target(binding_fingerprint), binding_fingerprint=binding_fingerprint)

    def _read(self, *, target: Path, binding_fingerprint: str) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        if not target.is_dir() or target.is_symlink():
            raise ValueError("BACKTEST_ECONOMIC_FACT_NOT_FOUND")
        try:
            if {item.name for item in target.iterdir()} != {"facts.json"}:
                raise ValueError("unexpected entries")
            path = target / "facts.json"
            if path.is_symlink():
                raise ValueError("symlink")
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"schema_version", "dataset_binding_fingerprint", "updates"}
                or payload["schema_version"] != 1
                or payload["dataset_binding_fingerprint"] != binding_fingerprint
                or not isinstance(payload["updates"], list)
                or raw != only_canonical_json(payload)
            ):
                raise ValueError("schema")
            updates = tuple(OnlyMarketDataInboundUpdate.from_dict(item) for item in payload["updates"])
            if updates != tuple(sorted(updates, key=_order_key)):
                raise ValueError("ordering")
            return updates
        except Exception as exc:
            raise ValueError("BACKTEST_ECONOMIC_FACT_CORRUPT") from exc

    @staticmethod
    def _verify_binding(
        binding: OnlyResearchDatasetEconomicBinding,
        updates: tuple[OnlyMarketDataInboundUpdate, ...],
    ) -> None:
        for manifest in binding.economic_facts:
            selected = tuple(
                item
                for item in updates
                if item.data_type is manifest.fact_family
                and (
                    manifest.reference_price_kind is None
                    or getattr(getattr(item.payload, "fact", None), "kind", None) is manifest.reference_price_kind
                )
            )
            if (
                len(selected) != manifest.record_count
                or any(str(item.data_version) != manifest.data_version for item in selected)
                or only_canonical_fingerprint([item.to_dict() for item in selected]) != manifest.content_fingerprint
            ):
                raise ValueError("BACKTEST_ECONOMIC_FACT_MANIFEST_MISMATCH")
        if sum(item.record_count for item in binding.economic_facts) != len(updates):
            raise ValueError("BACKTEST_ECONOMIC_FACT_SET_MISMATCH")

    def _target(self, fingerprint: str) -> Path:
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise ValueError("BACKTEST_ECONOMIC_FACT_ID_INVALID")
        return self._root / fingerprint[:2] / fingerprint


def _order_key(item: OnlyMarketDataInboundUpdate) -> tuple[int, str, str, str]:
    return (item.ts_event.unix_nanos, str(item.instrument_id), item.data_type.value, str(item.update_id))


__all__ = ["OnlyBacktestEconomicFactStore"]
