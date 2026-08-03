from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.operations.acceptance import (
    OnlyAcceptanceArtifactWriter,
    OnlyAcceptanceEvidence,
    OnlyAcceptanceVerdict,
    only_evidence_from_dict,
    only_evidence_to_dict,
)

pytestmark = pytest.mark.contract


def _evidence() -> OnlyAcceptanceEvidence:
    stamp = OnlyTimestamp.from_datetime(datetime(2026, 8, 3, 1, 2, tzinfo=UTC))
    return OnlyAcceptanceEvidence(
        "evidence-1",
        "AUTOMATED_CONTRACT",
        "ENVIRONMENT",
        OnlyAcceptanceVerdict.PASS,
        "PASSED",
        stamp,
        stamp,
        {"amount": Decimal("1.20")},
        {"state": OnlyAcceptanceVerdict.PASS},
        ("worker/result.json",),
    )


def test_evidence_json_round_trip_preserves_decimal_timestamp_enum_and_relative_paths() -> None:
    payload = only_evidence_to_dict(_evidence())
    assert payload["expected"] == {"amount": "1.20"}
    assert payload["started_at"] == "2026-08-03T01:02:00+00:00"
    restored = only_evidence_from_dict(payload)
    assert restored.verdict is OnlyAcceptanceVerdict.PASS
    assert restored.artifact_paths == ("worker/result.json",)


def test_artifact_writer_redacts_sensitive_values_and_creates_complete_last(tmp_path) -> None:
    bundle = OnlyAcceptanceArtifactWriter().write(
        run_root=tmp_path / "run",
        manifest={"verdict": "PASS", "schema_version": 1},
        environment={"account_id": "secret-account", "userdata_mini_path": r"C:\Users\private\userdata_mini"},
        sanitized_config={"token": "secret-token"},
        evidences=(_evidence(),),
    )
    assert bundle.complete_path.is_file()
    combined = "".join(path.read_text(encoding="utf-8") for path in bundle.run_root.glob("*.json"))
    assert "secret-account" not in combined
    assert "secret-token" not in combined
    assert r"C:\Users\private" not in combined
    assert bundle.manifest_path.is_file()
    assert bundle.assertions_path.is_file()
    assert bundle.report_path.is_file()
