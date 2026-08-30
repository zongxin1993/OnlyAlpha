"""Path- and audit-time-independent cache fingerprints."""

import hashlib
import json

from onlyalpha.cache.historical.models import OnlyHistoricalBarCacheKey, OnlyTypedHistoricalCacheKey


def only_cache_key_payload(key: OnlyTypedHistoricalCacheKey) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_id": key.source_id,
        "dataset_type": key.dataset_type,
        "instrument_id": str(key.instrument_id),
        "schema_version": key.schema_version,
        "time_semantics_version": key.time_semantics_version,
        "data_version": key.data_version,
        "compatibility_profile_id": key.compatibility_profile_id,
    }
    if isinstance(key, OnlyHistoricalBarCacheKey):
        payload.update(
            {
                "bar_type": key.bar_type.to_dict(),
                "price_adjustment": key.price_adjustment.value,
                "adjustment_reference": key.adjustment_reference,
            }
        )
        if key.timestamp_semantics.value != "bar_close":
            payload["timestamp_semantics"] = key.timestamp_semantics.value
    return payload


def only_content_fingerprint(key: OnlyTypedHistoricalCacheKey, partition_hashes: dict[str, str]) -> str:
    payload = {"key": only_cache_key_payload(key), "partitions": sorted(partition_hashes.items())}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
