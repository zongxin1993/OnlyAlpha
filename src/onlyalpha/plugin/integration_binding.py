"""Pure Integration binding identity checks, without configuration or credential access."""

from collections.abc import Mapping
from uuid import UUID

from onlyalpha.canonical import only_canonical_fingerprint

from .integration import INTEGRATION_RUNTIME_BINDING_IDENTITY_DOMAIN


def only_verify_retained_integration_runtime_binding(payload: Mapping[str, object]) -> None:
    expected = {
        "schema_version",
        "integration_id",
        "revision_fingerprint",
        "type_id",
        "category",
        "type_descriptor_fingerprint",
        "runtime_configuration_fingerprint",
        "runtime_generation_fingerprint",
        "identity_domain",
        "binding_fingerprint",
    }
    if (
        set(payload) != expected
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["identity_domain"] != INTEGRATION_RUNTIME_BINDING_IDENTITY_DOMAIN
        or type(payload["integration_id"]) is not str
        or str(UUID(payload["integration_id"])) != payload["integration_id"]
        or payload["category"] != "DATA_SOURCE"
        or type(payload["type_id"]) is not str
        or not payload["type_id"]
    ):
        raise ValueError("retained Integration binding invalid")
    for name in (
        "revision_fingerprint",
        "type_descriptor_fingerprint",
        "runtime_configuration_fingerprint",
        "binding_fingerprint",
        "runtime_generation_fingerprint",
    ):
        value = payload[name]
        if name == "runtime_generation_fingerprint" and value is None:
            continue
        if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("retained Integration binding fingerprint invalid")
    body = {key: value for key, value in payload.items() if key != "binding_fingerprint"}
    if only_canonical_fingerprint(body) != payload["binding_fingerprint"]:
        raise ValueError("retained Integration binding identity differs")
