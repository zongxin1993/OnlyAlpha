"""Seed the dev public Market Data source through the versioned Product API only.

This startup client has no database access, provider traffic or trading permission.
Publishing configuration is not a claim that history or realtime is READY; the Web
still obtains Instrument, Coverage and stream facts through their existing APIs.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, cast

from scripts.product_acceptance_client import AcceptanceFailure, ProductHttpClient

TYPE_ID = "binance.spot.market_data"
ENVIRONMENT = "GLOBAL"
# Deployment seed / command identities, never browser selection or Source identity.
# Fixed UUID4 keys let interrupted startup replay the same durable command receipts.
INTEGRATION_ID = "7eeb2a83-47d0-4afa-871f-1e97e2a98565"
CREATE_COMMAND_ID = "b6aba93d-51d1-4404-a0e9-c1881a8dc16a"
PUBLISH_COMMAND_ID = "0c112e29-d190-4aeb-adc5-325ead4ef1c5"


def _schema_v1(document: dict[str, Any]) -> bool:
    return type(document.get("schema_version")) is int and document["schema_version"] == 1


def _items(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = document.get(key)
    if (key == "sources" and not _schema_v1(document)) or not isinstance(items, list):
        raise AcceptanceFailure("DEV_MARKET_DATA_RESPONSE_INVALID")
    if any(not isinstance(item, dict) for item in items):
        raise AcceptanceFailure("DEV_MARKET_DATA_RESPONSE_INVALID")
    return cast(list[dict[str, Any]], items)


def _uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def _fingerprint(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _default_sources(client: ProductHttpClient) -> list[dict[str, Any]]:
    sources = _items(client.request("GET", "/api/v2/market-data/sources"), "sources")
    owners: set[str] = set()
    for source in sources:
        owner = source.get("integration_id")
        if (
            not _uuid4(owner)
            or not _fingerprint(source.get("integration_revision_fingerprint"))
            or any(
                not isinstance(source.get(key), str) or not source[key]
                for key in ("type_id", "source_id", "environment")
            )
            or owner in owners
        ):
            raise AcceptanceFailure("DEV_MARKET_DATA_SOURCE_PROOF_INVALID")
        owners.add(cast(str, owner))
    return [source for source in sources if source["type_id"] == TYPE_ID and source["environment"] == ENVIRONMENT]


def provision(client: ProductHttpClient) -> dict[str, object]:
    """Publish plugin defaults once, preserving all subsequent operator decisions."""

    existing = _default_sources(client)
    if existing:
        # More than one is intentionally left to the Web's explicit source selector.
        return {"provisioning": "EXISTING_SOURCE", "source_count": len(existing)}

    integrations = _items(client.request("GET", "/api/v2/integrations"), "items")
    identities = [item.get("integration_id") for item in integrations]
    if any(not _uuid4(identity) for identity in identities) or len(set(identities)) != len(identities):
        raise AcceptanceFailure("DEV_MARKET_DATA_INTEGRATION_PROOF_INVALID")
    seed = next((item for item in integrations if item["integration_id"] == INTEGRATION_ID), None)
    if seed is not None:
        if (
            seed.get("type_id") != TYPE_ID
            or seed.get("lifecycle_state") not in {"ACTIVE", "DISABLED", "ARCHIVED"}
            or "current_revision_fingerprint" not in seed
            or (
                seed["current_revision_fingerprint"] is not None
                and not _fingerprint(seed["current_revision_fingerprint"])
            )
            or type(seed.get("draft_version")) is not int
            or seed["draft_version"] < 1
        ):
            raise AcceptanceFailure("DEV_MARKET_DATA_INTEGRATION_PROOF_INVALID")
        if (
            seed["lifecycle_state"] != "ACTIVE"
            or seed["current_revision_fingerprint"] is not None
            or seed["draft_version"] != 1
        ):
            # Never re-enable, overwrite an edited draft, or replace a published revision.
            return {"provisioning": "PRESERVED", "integration_id": INTEGRATION_ID}

    created = client.request(
        "POST",
        "/api/v2/integrations",
        {
            "schema_version": 1,
            "integration_id": INTEGRATION_ID,
            "type_id": TYPE_ID,
            "display_name": "Binance Spot Market Data",
        },
        idempotency_key=CREATE_COMMAND_ID,
        expected_status=201,
    )
    if (
        not _schema_v1(created)
        or created.get("integration_id") != INTEGRATION_ID
        or created.get("command_id") != CREATE_COMMAND_ID
        or created.get("outcome_kind") != "INTEGRATION"
        or created.get("outcome_id") != INTEGRATION_ID
    ):
        raise AcceptanceFailure("DEV_MARKET_DATA_COMMAND_PROOF_INVALID")
    # The fresh draft is the plugin-declared GLOBAL / PUBLIC_MARKET_DATA defaults.
    # No endpoint override, secret, instrument whitelist or second configuration path.
    published = client.request(
        "POST",
        f"/api/v2/integrations/{INTEGRATION_ID}/revisions",
        {"schema_version": 1, "expected_draft_version": 1},
        idempotency_key=PUBLISH_COMMAND_ID,
    )
    if (
        not _schema_v1(published)
        or published.get("integration_id") != INTEGRATION_ID
        or published.get("command_id") != PUBLISH_COMMAND_ID
        or published.get("outcome_kind") != "INTEGRATION_REVISION"
        or not _fingerprint(published.get("outcome_id"))
    ):
        raise AcceptanceFailure("DEV_MARKET_DATA_COMMAND_PROOF_INVALID")
    sources = _default_sources(client)
    selected = [
        source
        for source in sources
        if source["integration_id"] == INTEGRATION_ID
        and source["integration_revision_fingerprint"] == published["outcome_id"]
    ]
    if len(selected) != 1:
        raise AcceptanceFailure("DEV_MARKET_DATA_PUBLISHED_SOURCE_UNAVAILABLE")
    return {
        "provisioning": "PUBLISHED",
        "integration_id": selected[0]["integration_id"],
        "revision_fingerprint": selected[0]["integration_revision_fingerprint"],
        "source_id": selected[0]["source_id"],
    }


if __name__ == "__main__":
    print(json.dumps(provision(ProductHttpClient(os.environ["ONLYALPHA_PRODUCT_API_URL"])), sort_keys=True))
