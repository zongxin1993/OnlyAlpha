"""Actual native Qualification startup infrastructure; not business acceptance."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

from packages.backend.tests.application.test_schema_postgres import migration_backend as migration_backend
from packages.backend.tests.application.test_schema_postgres import schema_db as schema_db
from packages.backend.tests.transport.frozen_strategy_fixture import call, canonical_json

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
NAMESPACE = "11111111-1111-4111-8111-111111111111"


def fingerprint(value: object) -> str:
    # Independent test-data identity, not a Python business constructor.
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def owner_fixture(probe: Path, **options: object) -> dict[str, Any]:
    result = subprocess.run(
        [str(probe)],
        input=json.dumps({"op": "qualification-fixture", **options}),
        text=True,
        capture_output=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def policy(
    probe: Path, version: str = "1", threshold: str = "-0.000001", policy_id: str = "research"
) -> dict[str, Any]:
    result = owner_fixture(probe, action="model", version=version, threshold=threshold, policy_id=policy_id)
    assert result["error"] is None, result
    record = cast(dict[str, Any], result["policy"])
    assert record["policy_version"] == version
    semantic = {key: value for key, value in record.items() if key != "policy_fingerprint"}
    assert record["policy_fingerprint"] == fingerprint(
        {"domain": "onlyalpha.strategy.qualification-policy", **semantic}
    )
    return record


def policies(probe: Path, root: Path) -> list[dict[str, Any]]:
    result = owner_fixture(probe, action="policies", root=str(root))
    assert result["error"] is None, result
    return cast(list[dict[str, Any]], result["policies"])


def load_policy(probe: Path, root: Path, policy_id: str, version: str) -> dict[str, Any]:
    result = owner_fixture(probe, action="load", root=str(root), policy_id=policy_id, version=version)
    assert result["error"] is None, result
    return cast(dict[str, Any], result["policy"])


@pytest.fixture
def research(schema_db: str, tmp_path: Path) -> Path:
    with psycopg.connect(schema_db) as conn:
        conn.execute(
            "INSERT INTO public.research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,%s)",
            (NAMESPACE,),
        )
    root = tmp_path / "research"
    root.mkdir()
    (root / ".onlyalpha-semantic-store.json").write_text(canonical_json({"schema_version": 1, "store_id": NAMESPACE}))
    return root


def admit(probe: Path, root: Path, policies: list[dict[str, Any]], **options: object) -> dict[str, Any]:
    return call(probe, action="qualification-admit", root=str(root), namespace=NAMESPACE, policies=policies, **options)


def test_native_put_once_reads_original_history_and_preserves_content(
    integration_http_probe: Path, research: Path
) -> None:
    old = policy(integration_http_probe, "٠١")
    assert admit(integration_http_probe, research, [old])["error"] is None
    original = {str(p.relative_to(research)): p.read_bytes() for p in research.rglob("manifest.json")}
    new = policy(integration_http_probe, "2", "100.125")
    result = admit(integration_http_probe, research, [new])
    assert result["error"] is None and result["session_error"] is None, result
    assert result["policies"] == policies(integration_http_probe, research)
    assert load_policy(integration_http_probe, research, "research", "2") == new
    assert all((research / path).read_bytes() == raw for path, raw in original.items())
    assert admit(integration_http_probe, research, [new, new])["policies"] == result["policies"]


def test_batch_conflict_is_rejected_before_any_publication(integration_http_probe: Path, research: Path) -> None:
    one, different = policy(integration_http_probe), policy(integration_http_probe, threshold="1")
    result = admit(integration_http_probe, research, [one, different])
    assert result["error"] == "QUALIFICATION_POLICY_IDENTITY_CONFLICT", result
    assert result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    assert not (research / "strategy/qualification-policies").exists()


def test_existing_same_identity_conflict_never_overwrites_history(integration_http_probe: Path, research: Path) -> None:
    old = policy(integration_http_probe)
    assert admit(integration_http_probe, research, [old])["error"] is None
    first = next(research.rglob("manifest.json")).read_bytes()
    result = admit(integration_http_probe, research, [policy(integration_http_probe, threshold="1")])
    assert result["error"] == "QUALIFICATION_POLICY_IDENTITY_CONFLICT", result
    assert next(research.rglob("manifest.json")).read_bytes() == first
    assert load_policy(integration_http_probe, research, "research", "1") == old


@pytest.mark.parametrize("version", ["1", "٠١", "١", "１", "𝟙", "1٠"])
def test_native_policy_identity_matches_original_unicode_version(
    integration_http_probe: Path, research: Path, version: str
) -> None:
    document = policy(integration_http_probe, version)
    result = admit(integration_http_probe, research, [document])
    assert result["error"] is None and result["policies"] == [document], result
    assert load_policy(integration_http_probe, research, "research", version) == document


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_version", "01"),
        ("policy_version", "٠"),
        ("policy_version", "²"),
        ("gate", "SIM_TO_LIVE"),
        ("schema_version", True),
        ("criteria", []),
        ("aggregation", "\x1c"),
    ],
)
def test_invalid_model_is_not_admitted(integration_http_probe: Path, research: Path, field: str, value: object) -> None:
    document = policy(integration_http_probe)
    document[field] = value
    document.pop("policy_fingerprint")
    document["policy_fingerprint"] = fingerprint({"domain": "onlyalpha.strategy.qualification-policy", **document})
    result = admit(integration_http_probe, research, [document])
    assert result["error"] == "QUALIFICATION_POLICY_IDENTITY_CONFLICT", result
    assert not (research / "strategy/qualification-policies").exists()


def test_oversized_public_model_cannot_publish_an_unreadable_manifest(
    integration_http_probe: Path, research: Path
) -> None:
    result = admit(
        integration_http_probe,
        research,
        [policy(integration_http_probe)],
        large_policy_metric_bytes=9 * 1024 * 1024,
        policy_model_work=16 * 1024 * 1024,
    )
    assert result["error"] == "QUALIFICATION_POLICY_STORE_UNAVAILABLE", result
    assert not (research / "strategy/qualification-policies/research/1").exists()


def test_empty_inventory_is_observed_without_initializing_history(integration_http_probe: Path, research: Path) -> None:
    result = admit(integration_http_probe, research, [])
    assert result["policies"] == [] and result["session_error"] is None, result
    assert not (research / "strategy").exists()


def test_unknown_nonblank_policy_semantics_remain_exact_data_not_approval(
    integration_http_probe: Path, research: Path
) -> None:
    doc = policy(integration_http_probe)
    doc["aggregation"] = "future-aggregate"
    doc["missing_evidence_behavior"] = "future-behavior"
    doc["criteria"][0]["comparison"] = "future-comparison"
    doc["criteria"][0]["metric"] = "future-metric"
    doc.pop("policy_fingerprint")
    doc["policy_fingerprint"] = fingerprint({"domain": "onlyalpha.strategy.qualification-policy", **doc})
    assert owner_fixture(integration_http_probe, action="validate", document=doc)["policy"] == doc
    result = admit(integration_http_probe, research, [doc])
    assert result["error"] is None and result["policies"] == [doc], result


@pytest.mark.parametrize(
    "threshold",
    ["0", "1", "-1", "0.000000001", "-0.000000001", "10000000000000000000000000000000000000000000000000001.125"],
)
def test_fixed_decimal_identity_matches_python(integration_http_probe: Path, research: Path, threshold: str) -> None:
    doc = policy(integration_http_probe, threshold=threshold)
    result = admit(integration_http_probe, research, [doc])
    assert result["error"] is None and result["policies"] == [doc], result


@pytest.mark.parametrize("threshold", ["-0", "00", ".1", "1.", "1.0", "1e3", "+1", "١", "NaN", "Infinity"])
def test_noncanonical_thresholds_cannot_be_published(
    integration_http_probe: Path, research: Path, threshold: str
) -> None:
    doc = policy(integration_http_probe)
    doc["criteria"][0]["threshold"] = threshold
    doc.pop("policy_fingerprint")
    doc["policy_fingerprint"] = fingerprint({"domain": "onlyalpha.strategy.qualification-policy", **doc})
    assert (
        owner_fixture(integration_http_probe, action="validate", document=doc)["error"]
        == "QUALIFICATION_POLICY_IDENTITY_CONFLICT"
    )
    result = admit(integration_http_probe, research, [doc])
    assert result["error"] == "QUALIFICATION_POLICY_IDENTITY_CONFLICT", result
    assert not (research / "strategy").exists()


@pytest.mark.parametrize("fault", ["canonical", "fingerprint", "path", "extra", "stage", "symlink"])
def test_existing_corrupt_history_refuses_admission_without_repair(
    integration_http_probe: Path, research: Path, fault: str
) -> None:
    doc = policy(integration_http_probe)
    assert admit(integration_http_probe, research, [doc])["error"] is None
    target = research / "strategy/qualification-policies/research/1"
    manifest = target / "manifest.json"
    if fault == "canonical":
        manifest.write_text(json.dumps(doc, indent=2))
    elif fault == "fingerprint":
        doc["policy_fingerprint"] = "0" * 64
        manifest.write_text(canonical_json(doc))
    elif fault == "path":
        target.rename(target.with_name("2"))
    elif fault == "extra":
        (target / "unexpected").write_text("unexpected")
    elif fault == "stage":
        (target.parent / ".stage-abandoned").mkdir()
    elif fault == "symlink":
        saved = research / "retained-manifest"
        manifest.rename(saved)
        manifest.symlink_to(saved)
    before = {str(p.relative_to(research)): p.read_bytes() for p in research.rglob("*") if p.is_file()}
    result = admit(integration_http_probe, research, [policy(integration_http_probe, "3")])
    assert (
        result["error"] == "QUALIFICATION_POLICY_IDENTITY_CONFLICT"
        and result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    ), result
    assert not (target.parent / "3").exists()
    assert before == {str(p.relative_to(research)): p.read_bytes() for p in research.rglob("*") if p.is_file()}


def test_trusted_history_hardlink_remains_readable(integration_http_probe: Path, research: Path) -> None:
    import os

    doc = policy(integration_http_probe)
    assert admit(integration_http_probe, research, [doc])["error"] is None
    manifest = research / "strategy/qualification-policies/research/1/manifest.json"
    os.link(manifest, research / "retained-link")
    result = admit(integration_http_probe, research, [])
    assert result["error"] is None and result["policies"] == [doc], result


@pytest.mark.parametrize("fault", ["missing-file", "file-mismatch", "db-missing", "db-mismatch", "guard"])
def test_namespace_and_actual_guard_are_required_before_any_write(
    integration_http_probe: Path, postgres_dsn: str, research: Path, fault: str
) -> None:
    metadata = research / ".onlyalpha-semantic-store.json"
    if fault == "missing-file":
        metadata.unlink()
    elif fault == "file-mismatch":
        metadata.write_text(canonical_json({"schema_version": 1, "store_id": "22222222-2222-4222-8222-222222222222"}))
    elif fault == "db-missing":
        with psycopg.connect(postgres_dsn) as conn:
            conn.execute("DELETE FROM public.research_deployment_semantic_store_binding")
    elif fault == "db-mismatch":
        with psycopg.connect(postgres_dsn) as conn:
            conn.execute(
                "UPDATE public.research_deployment_semantic_store_binding SET semantic_store_id='22222222-2222-4222-8222-222222222222'"
            )
    result = admit(integration_http_probe, research, [policy(integration_http_probe)], lose_guard=fault == "guard")
    assert result["error"] is not None and result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST", result
    assert not (research / "strategy").exists()


def test_input_work_exhaustion_precedes_all_publication(integration_http_probe: Path, research: Path) -> None:
    result = admit(integration_http_probe, research, [policy(integration_http_probe)], max_work=0)
    assert result["error"] == "QUALIFICATION_POLICY_STORE_UNAVAILABLE", result
    assert not (research / "strategy").exists()


def test_initial_pending_cancel_revokes_session_without_publication(
    integration_http_probe: Path, postgres_dsn: str, research: Path
) -> None:
    from packages.backend.tests.postgres_link import wait_no_advisory_locks

    result = admit(integration_http_probe, research, [policy(integration_http_probe)], cancel_admission=True)
    assert result["cancelled"] is True and result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST", result
    assert not (research / "strategy").exists()
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])


def test_partial_later_write_preserves_earlier_published_fact_and_refuses_blind_retry(
    integration_http_probe: Path, research: Path
) -> None:
    import resource
    import signal
    import subprocess

    first = policy(integration_http_probe, policy_id="a")
    second = policy(integration_http_probe, policy_id="b")
    second["criteria"][0]["metric"] = "large-metric" * 1000
    second.pop("policy_fingerprint")
    second["policy_fingerprint"] = fingerprint({"domain": "onlyalpha.strategy.qualification-policy", **second})
    size = len(canonical_json(first).encode()) + 16

    def short_files() -> None:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))

    result = subprocess.run(
        [str(integration_http_probe)],
        input=json.dumps(
            {
                "op": "node-authority",
                "action": "qualification-admit",
                "root": str(research),
                "namespace": NAMESPACE,
                "policies": [first, second],
            }
        ),
        text=True,
        capture_output=True,
        timeout=25,
        preexec_fn=short_files,
    )
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert (
        outcome["error"] == "QUALIFICATION_POLICY_STORE_UNAVAILABLE"
        and outcome["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    ), outcome
    before = {str(p.relative_to(research)): p.read_bytes() for p in research.rglob("manifest.json")}
    published = (research / "strategy/qualification-policies/a/1/manifest.json").read_bytes()
    assert published == canonical_json(first).encode("utf-8")
    validated = owner_fixture(integration_http_probe, action="validate", document=json.loads(published))
    assert validated["error"] is None and validated["policy"] == first
    assert (
        owner_fixture(integration_http_probe, action="load", root=str(research), policy_id="a", version="1")["error"]
        == "QUALIFICATION_POLICY_IDENTITY_CONFLICT"
    )
    assert owner_fixture(integration_http_probe, action="policies", root=str(research))["error"] == (
        "QUALIFICATION_POLICY_IDENTITY_CONFLICT"
    )
    assert before == {str(p.relative_to(research)): p.read_bytes() for p in research.rglob("manifest.json")}
    assert not (research / "strategy/qualification-policies/b/1").exists()
    stages = list((research / "strategy/qualification-policies/b").glob(".stage-*"))
    assert len(stages) == 1 and (stages[0] / "manifest.json").stat().st_size == size
    again = admit(integration_http_probe, research, [first, second])
    assert again["error"] == "QUALIFICATION_POLICY_IDENTITY_CONFLICT", again
    assert before == {str(p.relative_to(research)): p.read_bytes() for p in research.rglob("manifest.json")}


def test_lost_final_guard_response_preserves_published_history_for_fresh_process(
    integration_http_probe: Path, postgres_dsn: str, research: Path
) -> None:
    import os
    import socket
    import struct
    import subprocess

    from packages.backend.tests.postgres_link import CommitAckCut

    class FinalProofCut(CommitAckCut):
        def __init__(self, dsn: str) -> None:
            super().__init__(dsn)
            self.true_rows = 0

        def backend(self, source: socket.socket, destination: socket.socket) -> None:
            try:
                while True:
                    tag = self.exact(source, 1)
                    length = self.exact(source, 4)
                    size = struct.unpack("!I", length)[0]
                    if not 4 <= size <= 16 * 1024 * 1024:
                        raise ValueError("controlled PG frame outside bound")
                    payload = self.exact(source, size - 4)
                    if tag == b"D" and payload == b"\x00\x01\x00\x00\x00\x01\x01":
                        self.true_rows += 1
                        # Actual acquire, initial admission and Client lending
                        # precede publication; the fifth true row is its final proof.
                        if self.true_rows == 5:
                            self.done.set()
                            return
                    destination.sendall(tag + length + payload)
            except Exception as error:
                self.errors.append(error)
            finally:
                destination.shutdown(socket.SHUT_RDWR)

    doc = policy(integration_http_probe)
    with FinalProofCut(postgres_dsn) as link:
        child = subprocess.run(
            [str(integration_http_probe)],
            input=json.dumps(
                {
                    "op": "node-authority",
                    "action": "qualification-admit",
                    "root": str(research),
                    "namespace": NAMESPACE,
                    "policies": [doc],
                }
            ),
            env={**os.environ, "ONLYALPHA_POSTGRES_DSN": link.dsn},
            text=True,
            capture_output=True,
            timeout=25,
        )
        assert child.returncode == 0, child.stderr
        result = json.loads(child.stdout)
        assert link.done.is_set() and link.true_rows == 5
        assert (
            result["error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
            and result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
        ), result
    assert load_policy(integration_http_probe, research, "research", "1") == doc
    before = next(research.rglob("manifest.json")).read_bytes()
    again = admit(integration_http_probe, research, [doc])
    assert again["error"] is None and again["policies"] == [doc], again
    assert next(research.rglob("manifest.json")).read_bytes() == before
