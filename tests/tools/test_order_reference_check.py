from scripts.order_reference_check import check_fixture


def test_order_domain_fixture_is_current() -> None:
    check_fixture()


def test_python_reference_checks_native_values_and_detects_mismatch() -> None:
    import json

    import pytest

    from scripts.order_reference_check import ROOT, compare_native_outputs

    rows = [json.loads(line) for line in (ROOT / "test-data/order/lifecycle-v1.jsonl").read_text().splitlines()]
    observed = [{"case": row["case"], "observed": row["expected"]} for row in rows]
    compare_native_outputs(observed)
    observed[0]["observed"] = [["FILLED", "4", "99.99", "399.96"]]
    with pytest.raises(AssertionError):
        compare_native_outputs(observed)
