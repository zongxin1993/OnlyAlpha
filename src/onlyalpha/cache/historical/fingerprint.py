"""Path- and audit-time-independent cache fingerprints."""

import hashlib
import json

from onlyalpha.cache.historical.models import OnlyHistoricalCacheKey


def only_cache_key_payload(key: OnlyHistoricalCacheKey) -> dict[str, object]:
    return {
        "source_id": key.source_id,
        "dataset_type": key.dataset_type,
        "instrument_id": str(key.instrument_id),
        "bar_type": key.bar_type.to_dict(),
        "price_adjustment": key.price_adjustment.value,
        "adjustment_reference": key.adjustment_reference,
        "schema_version": key.schema_version,
        "time_semantics_version": key.time_semantics_version,
    }


def only_content_fingerprint(key: OnlyHistoricalCacheKey, partition_hashes: dict[str, str]) -> str:
    payload = {"key": only_cache_key_payload(key), "partitions": sorted(partition_hashes.items())}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
