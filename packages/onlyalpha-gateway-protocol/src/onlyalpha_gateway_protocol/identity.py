from __future__ import annotations

import hashlib

_TEST_MUTATION_DOMAIN = b"onlyalpha.gateway.v1.ApplyTestMutation\x00"


def canonical_test_mutation_fingerprint(payload: str) -> str:
    """Bind test command identity only to its provider-neutral canonical payload."""

    return hashlib.sha256(_TEST_MUTATION_DOMAIN + payload.encode("utf-8")).hexdigest()
