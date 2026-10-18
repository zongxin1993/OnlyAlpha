from decimal import Decimal, localcontext

import pytest
from onlyalpha_calculation_worker.backend import resolve
from onlyalpha_calculation_worker.contracts import decode, encode, scalar


def test_component_decimal_quantum_is_canonical_and_context_independent():
    record = resolve({"period": 3})["definition"]
    assert record["schema_version"] == 3
    assert record["numeric"]["output_quantum"] == "0.000000000001"
    with localcontext() as context:
        context.prec = 2
        assert scalar(Decimal("123456789.00")) == {"type": "DECIMAL", "value": "123456789"}
    assert scalar(Decimal("-0E-99"))["value"] == "0"


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1.2}', b"[]" * 3000, b"[" * 100 + b"]" * 100])
def test_untrusted_records_are_bounded_and_have_no_duplicate_or_float(raw):
    with pytest.raises(ValueError):
        decode(raw)


def test_encode_rejects_float_without_implicit_coercion():
    with pytest.raises(ValueError):
        encode({"value": 1.0})


def test_worker_provenance_binds_loaded_native_codec_and_decimal_runtime():
    from onlyalpha_calculation_worker.artifact import manifest

    resources = {r.relative_path: r.byte_sha256 for r in manifest().resources}
    assert {
        "runtime/decimal-native",
        "runtime/protobuf-native",
        "runtime/python-executable",
        "runtime/python-library",
    } <= resources.keys()
    assert all(len(value) == 64 for value in resources.values())
