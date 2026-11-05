import pytest

from onlyalpha.algorithm.codec import decode, encode


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1.2}', b"[]" * 3000, b"[" * 100 + b"]" * 100])
def test_untrusted_records_are_bounded_and_have_no_duplicate_or_float(raw):
    with pytest.raises(ValueError):
        decode(raw)


def test_encode_rejects_float_without_implicit_coercion():
    with pytest.raises(ValueError):
        encode({"value": 1.0})
