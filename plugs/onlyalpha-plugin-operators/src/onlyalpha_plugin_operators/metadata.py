"""Pure installed provider identity, shared with the isolated algorithm SDK."""

PROVIDER_ID = "onlyalpha.operator.library"
PROVIDER_VERSION = "6"
DISTRIBUTION_NAME = "onlyalpha-plugin-operators"
DISTRIBUTION_VERSION = "0.11.1"


def provider_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider_id": PROVIDER_ID,
        "provider_version": PROVIDER_VERSION,
        "kind": "OPERATOR",
        "source": {
            "kind": "DISTRIBUTION",
            "distribution_name": DISTRIBUTION_NAME,
            "distribution_version": DISTRIBUTION_VERSION,
        },
    }
