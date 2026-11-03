"""Lossless type values from one selected algorithm; no registry or discovery."""

from decimal import Decimal
from itertools import chain
from typing import cast

from onlyalpha.algorithm.codec import MAX_FRAME, decode
from onlyalpha.calculation.definition import OnlyCalculationTypeDefinition
from onlyalpha.canonical import only_canonical_json


def _scalar(value: object) -> dict[str, object]:
    if value is None:
        return {"type": "NULL", "value": None}
    for kind, scalar_type in (("BOOLEAN", bool), ("INTEGER", int), ("STRING", str)):
        if type(value) is scalar_type:
            return {"type": kind, "value": value}
    if type(value) is Decimal and value.is_finite():
        # str preserves exponent, coefficient scale and signed zero. Fixed-f
        # Product identity is only a projection, not a lossless SDK value.
        return {"type": "DECIMAL", "value": str(value)}
    raise ValueError("CALCULATION_TYPE_DECLARATION_INVALID")


def _decimal_projection_size(value: object) -> int:
    if type(value) is not Decimal:
        return 0
    if not value.is_finite():
        raise ValueError("CALCULATION_TYPE_DECLARATION_INVALID")
    parts = value.as_tuple()
    exponent = cast(int, parts.exponent)
    digits = len(parts.digits)
    if exponent >= 0:
        length = 1 if value.is_zero() else digits + exponent
    elif digits + exponent > 0:
        length = digits + 1
    else:
        length = 2 - exponent
    return length + int(value.is_signed())


def type_declaration(definition: OnlyCalculationTypeDefinition) -> dict[str, object]:
    # Charge fixed-f expansion before calling the public formatter. The final
    # private decoder/encoder still enforces total JSON, depth and scalar bounds.
    remaining = MAX_FRAME
    values = chain(
        (definition.numeric.output_quantum,),
        (
            value
            for field in definition.parameters.fields
            for value in chain((field.default, field.minimum, field.maximum), field.enum_values)
        ),
    )
    for value in values:
        remaining -= _decimal_projection_size(value)
        if remaining < 0:
            raise ValueError("CALCULATION_TYPE_DECLARATION_UNAVAILABLE")
    descriptor = decode(only_canonical_json(definition.descriptor()).encode("utf-8"))
    return {
        "schema_version": 1,
        "descriptor": descriptor,
        "parameter_values": [
            {
                "default": _scalar(field.default),
                "minimum": _scalar(field.minimum),
                "maximum": _scalar(field.maximum),
                "enum_values": [_scalar(value) for value in field.enum_values],
            }
            for field in definition.parameters.fields
        ],
    }
