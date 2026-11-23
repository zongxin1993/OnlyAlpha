"""真实受控 Source 采集身份、冻结观察与联合行情一致性。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from packages.backend.tests.application.support.native_research_market_fixture import (
    SCOPE_FIELDS,
    probe,
)
from packages.backend.tests.application.support.native_research_market_fixture import (
    database as database,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(120)]


def retained(binary, database, root, capture, profile="STRATEGY_PREPARATION_V1", operation=None, **values):
    result = probe(
        binary,
        database,
        "retained-source-prerequisite",
        fixture_capture_id=capture,
        fixture_profile=profile,
        user_data=str(root),
        selected_backend=str(binary),
        selected_backend_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        **(
            operation
            or {"integration_id": str(uuid4()), "create_command": str(uuid4()), "publish_command": str(uuid4())}
        ),
        source_trust="/etc/ssl/certs/ca-certificates.crt",
        **values,
    )
    assert "error" not in result, result
    return result


def sealed_facts(result):
    raw = (Path(result["wal_root"]) / (result["segment"]["segment_id"] + ".sealed.wal")).read_bytes()
    offset, facts = 0, []
    while offset < len(raw):
        header = raw[offset : offset + 53]
        assert header[:5] == b"OAMD\x01"
        length = int.from_bytes(header[5:13], "big")
        payload = raw[offset + 53 : offset + 53 + length]
        assert hashlib.sha256(payload).digest() == header[21:53]
        facts.extend(json.loads(payload)["canonical_facts"])
        offset += 53 + length
    assert offset == len(raw)
    selected = {fact["canonical_fact_id"]: fact for fact in facts}
    assert len(selected) == len(facts), "duplicate fact IDs cannot disappear during comparison"
    return selected


def test_distinct_source_captures_have_distinct_immutable_segment_identities(native_release_probe, database, tmp_path):
    first = retained(native_release_probe, database, tmp_path / "first", str(uuid4()))
    second = retained(native_release_probe, database, tmp_path / "second", str(uuid4()))
    assert first["segment"]["segment_id"] != second["segment"]["segment_id"]
    assert first["segment"]["capture_session_id"] != second["segment"]["capture_session_id"]
    original = None
    for value in [first, second]:
        segment = value["segment"]
        scope = {key: segment[key] for key in SCOPE_FIELDS}
        result = probe(
            native_release_probe, database, "drain", root=value["wal_root"], ids=[segment["segment_id"]], scope=scope
        )
        assert "error" not in result, result
        view = probe(native_release_probe, database, "read", id=result["revision"]["revision_id"])
        assert len(view["facts"]) == 28
        if original is None:
            original = (result["revision"]["revision_id"], view)
    assert probe(native_release_probe, database, "read", id=original[0]) == original[1]


def test_joint_research_and_backtest_overlap_has_identical_complete_canonical_payload(
    native_release_probe, database, tmp_path
):
    research = retained(
        native_release_probe,
        database,
        tmp_path / "research",
        str(uuid4()),
        "STRATEGY_RESEARCH_EVIDENCE_V1",
        coherent_backtest=True,
    )
    backtest = retained(
        native_release_probe, database, tmp_path / "backtest", str(uuid4()), "BTC_SPOT_NEXT_OPEN_2025_V1"
    )
    left, right = sealed_facts(research), sealed_facts(backtest)
    assert len(left) == len(right) == 740
    common = left.keys() & right.keys()
    assert len(common) == 19
    for key in common:
        assert left[key]["canonical_payload"] == right[key]["canonical_payload"]
        assert left[key]["canonical_payload_hash"] == right[key]["canonical_payload_hash"]


def test_original_capture_ordinal_rejects_changed_segment_content(native_release_probe, database, tmp_path):
    capture = str(uuid4())
    first = retained(native_release_probe, database, tmp_path / "first", capture)
    second = retained(native_release_probe, database, tmp_path / "changed", capture, "RESEARCH_INPUT_ADMISSION_V1")
    assert first["segment"]["segment_id"] == second["segment"]["segment_id"]
    assert first["segment"]["content_hash"] != second["segment"]["content_hash"]
    segment = first["segment"]
    result = probe(
        native_release_probe,
        database,
        "drain",
        root=first["wal_root"],
        ids=[segment["segment_id"]],
        scope={k: segment[k] for k in SCOPE_FIELDS},
    )
    assert "error" not in result, result
    original = probe(native_release_probe, database, "read", id=result["revision"]["revision_id"])
    changed = second["segment"]
    assert probe(
        native_release_probe,
        database,
        "drain",
        root=second["wal_root"],
        ids=[changed["segment_id"]],
        scope={k: changed[k] for k in SCOPE_FIELDS},
    ) == {"error": "MARKET_DATA_IDENTITY_CONFLICT"}
    assert probe(native_release_probe, database, "read", id=result["revision"]["revision_id"]) == original


def test_same_canonical_fact_with_different_payload_remains_rejected(native_release_probe, database, tmp_path):
    operation = {"integration_id": str(uuid4()), "create_command": str(uuid4()), "publish_command": str(uuid4())}
    values = [
        retained(
            native_release_probe,
            database,
            tmp_path / name,
            str(uuid4()),
            "STRATEGY_RESEARCH_EVIDENCE_V1",
            operation=operation,
            coherent_backtest=coherent,
        )
        for name, coherent in [("first", False), ("changed", True)]
    ]
    refs = []
    for value in values:
        segment = value["segment"]
        scope = {k: segment[k] for k in SCOPE_FIELDS}
        result = probe(
            native_release_probe, database, "drain", root=value["wal_root"], ids=[segment["segment_id"]], scope=scope
        )
        assert "error" not in result, result
        refs.append([segment["segment_id"], segment["content_hash"]])
    assert probe(native_release_probe, database, "compose", scope=scope, refs=sorted(refs)) == {
        "error": "MARKET_DATA_IDENTITY_CONFLICT"
    }
