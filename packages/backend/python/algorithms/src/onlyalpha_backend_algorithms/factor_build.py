"""Isolated source-to-data construction only; native Rust owns execution/READY."""

from __future__ import annotations

import hashlib
from typing import Any

from onlyalpha.algorithm.factor_program import compile_factor_source
from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_API_V1

from onlyalpha_backend_algorithms.chart_isolation import restrict


def compile_request(payload: dict[str, Any]) -> dict[str, Any]:
    if (
        type(payload) is not dict
        or set(payload) != {"schema_version", "contract", "source"}
        or payload["schema_version"] != 1
        or payload["contract"] != "ONLYALPHA_FACTOR_PROGRAM_COMPILE_V1"
    ):
        raise ValueError("FACTOR_PROGRAM_COMPILE_INPUT")
    s = payload["source"]
    fields = {
        "source_text",
        "source_sha256",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "input_contract",
        "parameter_contract",
        "output_contract",
    }
    if (
        type(s) is not dict
        or set(s) != fields
        or type(s["source_text"]) is not str
        or s["source_sha256"] != hashlib.sha256(s["source_text"].encode()).hexdigest()
        or s["factor_api_contract_fingerprint"] != ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint
    ):
        raise ValueError("FACTOR_PROGRAM_SOURCE_BINDING")
    # All trusted module/resource imports precede the one-way kernel sandbox.
    isolation = restrict()
    program = compile_factor_source(
        s["source_text"],
        s["factor_api_version"],
        input_contract=s["input_contract"],
        parameter_contract=s["parameter_contract"],
        output_contract=s["output_contract"],
    )
    return {
        "schema_version": 1,
        "contract": "ONLYALPHA_FACTOR_PROGRAM_COMPILED_V1",
        "source_sha256": s["source_sha256"],
        "isolation": isolation,
        "parse_count": 1,
        "program": program,
    }
