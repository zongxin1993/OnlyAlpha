"""Read-only executable source projection; no Draft, publication or consent authority.

Revision fingerprint is an opaque owning-backend input. This SDK cannot certify
that a revision exists, was confirmed, or is authorized for Research.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol


class OnlyPrivateFactorExecutableSourceV1(Protocol):
    @property
    def factor_id(self) -> str: ...
    @property
    def semantic_version(self) -> str: ...
    @property
    def revision_fingerprint(self) -> str: ...
    @property
    def source_text(self) -> str: ...
    @property
    def source_sha256(self) -> str: ...
    @property
    def factor_api_version(self) -> int: ...
    @property
    def factor_api_contract_fingerprint(self) -> str: ...
    @property
    def input_contract(self) -> Mapping[str, object]: ...
    @property
    def parameter_contract(self) -> Mapping[str, object]: ...
    @property
    def output_contract(self) -> Mapping[str, object]: ...


def source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorExecutableSourceRecordV1:
    factor_id: str
    semantic_version: str
    revision_fingerprint: str
    source_text: str
    source_sha256: str
    factor_api_version: int
    factor_api_contract_fingerprint: str
    input_contract: Mapping[str, object]
    parameter_contract: Mapping[str, object]
    output_contract: Mapping[str, object]

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OnlyPrivateFactorExecutableSourceRecordV1:
        if set(raw) != set(cls.__dataclass_fields__):
            raise ValueError("PRIVATE_FACTOR_EXECUTABLE_SOURCE_INVALID")
        texts = (
            "factor_id",
            "semantic_version",
            "revision_fingerprint",
            "source_text",
            "source_sha256",
            "factor_api_contract_fingerprint",
        )
        values: dict[str, str] = {}
        for name in texts:
            value = raw[name]
            if type(value) is not str or not value:
                raise ValueError("PRIVATE_FACTOR_EXECUTABLE_SOURCE_INVALID")
            values[name] = value
        for name in ("revision_fingerprint", "source_sha256", "factor_api_contract_fingerprint"):
            value = values[name]
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("PRIVATE_FACTOR_EXECUTABLE_SOURCE_INVALID")
        api = raw["factor_api_version"]
        if type(api) is not int or api != 1:
            raise ValueError("PRIVATE_FACTOR_EXECUTABLE_SOURCE_INVALID")
        contracts: dict[str, Mapping[str, object]] = {}
        for name in ("input_contract", "parameter_contract", "output_contract"):
            value = raw[name]
            if not isinstance(value, Mapping) or any(type(k) is not str for k in value):
                raise ValueError("PRIVATE_FACTOR_EXECUTABLE_SOURCE_INVALID")
            contracts[name] = MappingProxyType(deepcopy(dict(value)))
        return cls(
            values["factor_id"],
            values["semantic_version"],
            values["revision_fingerprint"],
            values["source_text"],
            values["source_sha256"],
            api,
            values["factor_api_contract_fingerprint"],
            contracts["input_contract"],
            contracts["parameter_contract"],
            contracts["output_contract"],
        )
