"""Actual immutable-history to PG reconciliation; not Shipping business acceptance."""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.strategy_store import OnlyPostgresStrategyStore
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreId
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRecord
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
from tests.support.frozen_strategy import call, pair
from tests.support.postgres_link import CommitAckCut, wait_for_database_lock_barrier, wait_no_advisory_locks

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
NAMESPACE = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 10, 22, tzinfo=UTC)


@pytest.fixture
def prepared(postgres_dsn: str, tmp_path: Path) -> tuple[Path, str, str, dict[str, Any]]:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute(
            "INSERT INTO public.research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,%s)",
            (NAMESPACE,),
        )
    root = tmp_path / "research"
    root.mkdir()
    (root / ".onlyalpha-semantic-store.json").write_text(
        only_canonical_json({"schema_version": 1, "store_id": NAMESPACE})
    )
    repo = Path(__file__).resolve().parents[4]
    row = json.loads((repo / "test-data/strategy/product-sources-v1.jsonl").read_text().splitlines()[0])
    identity, relation = pair(root, row["record"])
    document = json.loads(
        (root / "strategy/freeze-relations/sha256" / relation[:2] / relation / "manifest.json").read_text()
    )
    return root, identity, relation, document


def reconcile(probe: Path, root: Path, **options: object) -> dict[str, Any]:
    return call(probe, action="frozen-reconcile", root=str(root), namespace=NAMESPACE, **options)


def snapshot(dsn: str) -> list[list[tuple[Any, ...]]]:
    with psycopg.connect(dsn) as conn:
        return [
            conn.execute(f"SELECT * FROM public.{table} ORDER BY 1").fetchall()
            for table in ("strategy_catalog", "strategy_freeze_record")
        ]


def test_current_history_reconstructs_only_projections_and_survives_fresh_process(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, identity, relation, document = prepared
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("manifest.json")}
    outcome = reconcile(integration_http_probe, root)
    assert outcome["reconciled"] is True and outcome["error"] is None and outcome["session_error"] is None, outcome
    reader = OnlyPostgresStrategyStore(postgres_dsn, OnlyResearchSemanticStoreId(NAMESPACE))
    row = reader.find_freeze_relation(
        document["candidate_fingerprint"], document["research_result_fingerprint"], identity
    )
    assert row is not None and row.record_fingerprint == relation
    assert row.actor == "onlyalpha-semantic-reconciler" and row.created_at == NOW
    with psycopg.connect(postgres_dsn) as conn:
        assert conn.execute(
            "SELECT created_at FROM public.strategy_catalog WHERE strategy_fingerprint=%s", (identity,)
        ).fetchone() == (NOW,)
    first = snapshot(postgres_dsn)
    assert reconcile(integration_http_probe, root, audit_at="2030-01-01T00:00:00+00:00")["reconciled"] is True
    assert snapshot(postgres_dsn) == first
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("manifest.json")}


def test_existing_exact_audit_and_catalog_metadata_are_preserved(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, identity, _, document = prepared
    writer = OnlyPostgresStrategyStore(postgres_dsn, OnlyResearchSemanticStoreId(NAMESPACE))
    writer.ensure_strategy(identity, 1)
    writer.append_freeze_record(
        OnlyStrategyFreezeRecord(
            document["candidate_fingerprint"],
            document["research_result_fingerprint"],
            tuple(document["research_execution_evidence_fingerprints"]),
            identity,
            document["admission_evidence_fingerprint"],
            tuple(document["equivalence_evidence_fingerprints"]),
            "original human",
            NOW,
            "original audit",
        )
    )
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("UPDATE public.strategy_catalog SET display_name='original name',catalog_family='original family'")
    first = snapshot(postgres_dsn)
    assert reconcile(integration_http_probe, root)["reconciled"] is True
    assert snapshot(postgres_dsn) == first


def test_dangling_projection_never_recreates_missing_immutable_history(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, identity, _, _ = prepared
    OnlyPostgresStrategyStore(postgres_dsn, OnlyResearchSemanticStoreId(NAMESPACE)).ensure_strategy(identity, 1)
    path = root / "strategy/frozen-revisions/sha256" / identity[:2] / identity / "manifest.json"
    path.unlink()
    path.parent.rmdir()
    before = snapshot(postgres_dsn)
    result = reconcile(integration_http_probe, root)
    assert (
        result["error"] == "STRATEGY_PROJECTION_CONFLICT" and result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    )
    assert snapshot(postgres_dsn) == before and not path.exists()


def test_invalid_audit_time_fails_without_effects(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, _, _, _ = prepared
    before = snapshot(postgres_dsn)
    result = reconcile(integration_http_probe, root, audit_at="2026-10-22T00:00:00.000000001+00:00")
    assert result["error"] == "STRATEGY_PROJECTION_AUDIT_INVALID"
    assert snapshot(postgres_dsn) == before


def test_deferred_catalog_mutation_is_detected_before_commit(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, _, _, _ = prepared
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute(
            "CREATE FUNCTION public.corrupt_deferred_catalog() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE public.strategy_catalog SET schema_version=2 WHERE strategy_fingerprint=NEW.strategy_fingerprint; RETURN NEW; END $$"
        )
        conn.execute(
            "CREATE CONSTRAINT TRIGGER corrupt_deferred_catalog AFTER INSERT ON public.strategy_catalog DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.corrupt_deferred_catalog()"
        )
    before = snapshot(postgres_dsn)
    result = reconcile(integration_http_probe, root)
    assert result["error"] == "STRATEGY_PROJECTION_CONFLICT", (result, snapshot(postgres_dsn))
    assert result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    assert snapshot(postgres_dsn) == before


class CountWire(CommitAckCut):
    """Forward the actual protocol unchanged and count received DataRow bytes."""

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self.data_row_bytes = 0

    def backend(self, upstream: socket.socket, downstream: socket.socket) -> None:
        try:
            while kind := upstream.recv(1):
                length = self.exact(upstream, 4)
                size = struct.unpack("!I", length)[0]
                if not 4 <= size <= 16 * 1024 * 1024:
                    raise ValueError("controlled PG frame outside bound")
                payload = self.exact(upstream, size - 4)
                if kind == b"D":
                    self.data_row_bytes += len(payload) + 5
                downstream.sendall(kind + length + payload)
        except (ConnectionResetError, BrokenPipeError):
            return
        except Exception as error:
            self.errors.append(error)


def test_cumulative_wire_budget_is_checked_before_large_projection_rows(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, identity, _, _ = prepared
    size = 12 * 1024 * 1024
    with psycopg.connect(postgres_dsn) as conn:
        for fingerprint in [identity, "0" * 64]:
            conn.execute(
                "INSERT INTO public.strategy_catalog(strategy_fingerprint,semantic_namespace_id,schema_version,display_name) VALUES(%s,%s,1,%s)",
                (fingerprint, NAMESPACE, "x" * size),
            )
    before = snapshot(postgres_dsn)
    cap = 20 * 1024 * 1024
    with CountWire(postgres_dsn) as link:
        result = subprocess.run(
            [str(integration_http_probe)],
            input=json.dumps(
                {
                    "op": "node-authority",
                    "action": "frozen-reconcile",
                    "root": str(root),
                    "namespace": NAMESPACE,
                    "max_work": cap,
                }
            ),
            text=True,
            capture_output=True,
            env={**os.environ, "ONLYALPHA_POSTGRES_DSN": link.dsn},
            timeout=25,
        )
        assert result.returncode == 0, result.stderr
        outcome = json.loads(result.stdout)
    assert outcome["error"] == "STRATEGY_PROJECTION_UNAVAILABLE", outcome
    assert link.data_row_bytes <= cap, link.data_row_bytes
    assert snapshot(postgres_dsn) == before


@pytest.mark.parametrize(
    "attack",
    [
        "catalog-schema",
        "catalog-namespace",
        "audit-schema1",
        "audit-schema3",
        "audit-identity",
        "audit-reference",
        "actor-blank",
    ],
)
def test_existing_corrupt_projection_never_changes_immutable_truth(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]], attack: str
) -> None:
    root, _, _, _ = prepared
    assert reconcile(integration_http_probe, root)["reconciled"] is True
    files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("manifest.json")}
    statements = {
        "catalog-schema": "UPDATE public.strategy_catalog SET schema_version=2",
        "catalog-namespace": "ALTER TABLE public.strategy_catalog DROP CONSTRAINT strategy_catalog_semantic_namespace_id_fkey; UPDATE public.strategy_catalog SET semantic_namespace_id='22222222-2222-4222-8222-222222222222'",
        "audit-schema1": "UPDATE public.strategy_freeze_record SET schema_version=1,research_execution_evidence_fingerprints=NULL,equivalence_evidence_fingerprints=NULL",
        "audit-schema3": "UPDATE public.strategy_freeze_record SET schema_version=3",
        "audit-identity": "UPDATE public.strategy_freeze_record SET admission_evidence_fingerprint=repeat('0',64)",
        "audit-reference": "UPDATE public.strategy_freeze_record SET equivalence_evidence_fingerprints=ARRAY[repeat('0',64)]",
        "actor-blank": "UPDATE public.strategy_freeze_record SET actor=chr(28)",
    }
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute(statements[attack])
    before = snapshot(postgres_dsn)
    result = reconcile(integration_http_probe, root)
    assert result["error"] == "STRATEGY_PROJECTION_CONFLICT", result
    assert result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    assert snapshot(postgres_dsn) == before
    assert files == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("manifest.json")}


@pytest.mark.parametrize("attack", ["file-missing", "file-mismatch", "binding-missing", "binding-mismatch"])
def test_namespace_is_selected_from_same_physical_root_and_exact_transaction(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]], attack: str
) -> None:
    root, _, _, _ = prepared
    metadata = root / ".onlyalpha-semantic-store.json"
    if attack == "file-missing":
        metadata.unlink()
    elif attack == "file-mismatch":
        metadata.write_text(
            only_canonical_json({"schema_version": 1, "store_id": "22222222-2222-4222-8222-222222222222"})
        )
    else:
        with psycopg.connect(postgres_dsn) as conn:
            conn.execute(
                "DELETE FROM public.research_deployment_semantic_store_binding"
                if attack == "binding-missing"
                else "UPDATE public.research_deployment_semantic_store_binding SET semantic_store_id='22222222-2222-4222-8222-222222222222'"
            )
    result = reconcile(integration_http_probe, root)
    expected = {
        "file-missing": "SEMANTIC_STORE_IDENTITY_MISSING",
        "file-mismatch": "SEMANTIC_STORE_IDENTITY_MISMATCH",
        "binding-missing": "DEPLOYMENT_BINDING_MISSING",
        "binding-mismatch": "SEMANTIC_STORE_IDENTITY_MISMATCH",
    }
    assert result["error"] == expected[attack], result
    assert result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    assert snapshot(postgres_dsn) == [[], []]


def test_relation_first_orphan_remains_unprojected(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, identity, _, _ = prepared
    manifest = root / "strategy/frozen-revisions/sha256" / identity[:2] / identity / "manifest.json"
    manifest.unlink()
    manifest.parent.rmdir()
    assert reconcile(integration_http_probe, root)["reconciled"] is True
    assert snapshot(postgres_dsn) == [[], []]
    assert not manifest.exists()


def test_contradictory_physical_relations_reject_before_effects(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, _, _, document = prepared
    relation = OnlyStrategyFreezeRelation.from_dict(document)
    changed = OnlyStrategyFreezeRelation(
        relation.strategy_fingerprint,
        relation.candidate_fingerprint,
        relation.research_result_fingerprint,
        relation.research_execution_evidence_fingerprints,
        "0" * 64,
        relation.equivalence_evidence_fingerprints,
    )
    target = root / "strategy/freeze-relations/sha256" / changed.relation_fingerprint[:2] / changed.relation_fingerprint
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(only_canonical_json(changed.to_dict()))
    assert reconcile(integration_http_probe, root)["error"] == "STRATEGY_PROJECTION_CONFLICT"
    assert snapshot(postgres_dsn) == [[], []]


@pytest.mark.parametrize("rows", [0, 1])
def test_whole_batch_row_budget_exhaustion_rolls_back(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]], rows: int
) -> None:
    root, _, _, _ = prepared
    result = reconcile(integration_http_probe, root, max_rows=rows)
    assert result["error"] == "STRATEGY_PROJECTION_UNAVAILABLE", result
    assert result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    assert snapshot(postgres_dsn) == [[], []]


@pytest.mark.parametrize("mutation", ["semantic", "actor", "time", "catalog-display", "raise"])
def test_projection_write_proof_detects_trigger_effects_and_rolls_back(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]], mutation: str
) -> None:
    root, _, _, _ = prepared
    table = "strategy_catalog" if mutation == "catalog-display" else "strategy_freeze_record"
    body = {
        "semantic": "NEW.admission_evidence_fingerprint=repeat('0',64); RETURN NEW;",
        "actor": "NEW.actor='unexpected actor'; RETURN NEW;",
        "time": "NEW.created_at='2030-01-01T00:00:00+00:00'; RETURN NEW;",
        "catalog-display": "NEW.display_name='unexpected name'; RETURN NEW;",
        "raise": "RAISE EXCEPTION 'controlled projection failure';",
    }[mutation]
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute(
            f"CREATE FUNCTION public.mutate_projection() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$"
        )
        conn.execute(
            f"CREATE TRIGGER mutate_projection BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.mutate_projection()"
        )
    result = reconcile(integration_http_probe, root)
    assert result["error"] == (
        "STRATEGY_PROJECTION_UNAVAILABLE" if mutation == "raise" else "STRATEGY_PROJECTION_CONFLICT"
    ), result
    assert result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    assert snapshot(postgres_dsn) == [[], []]


def test_real_commit_ack_loss_is_unknown_and_fresh_process_preserves_committed_audit(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, _, _, _ = prepared
    with CommitAckCut(postgres_dsn) as link:
        result = subprocess.run(
            [str(integration_http_probe)],
            input=json.dumps(
                {"op": "node-authority", "action": "frozen-reconcile", "root": str(root), "namespace": NAMESPACE}
            ),
            text=True,
            capture_output=True,
            env={**os.environ, "ONLYALPHA_POSTGRES_DSN": link.dsn},
            timeout=25,
        )
        assert result.returncode == 0, result.stderr
        outcome = json.loads(result.stdout)
    assert link.done.is_set()
    assert outcome["error"] == "STRATEGY_PROJECTION_OUTCOME_UNKNOWN", outcome
    assert outcome["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    committed = snapshot(postgres_dsn)
    assert len(committed[0]) == len(committed[1]) == 1
    assert reconcile(integration_http_probe, root, audit_at="2030-01-01T00:00:00+00:00")["reconciled"] is True
    assert snapshot(postgres_dsn) == committed


def test_shadow_search_path_cannot_select_alternate_projection_tables(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, _, _, _ = prepared
    assert reconcile(integration_http_probe, root, shadow_projection=True)["reconciled"] is True
    assert list(map(len, snapshot(postgres_dsn))) == [1, 1]


def test_pending_reconciliation_cancellation_revokes_original_physical_session(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, _, _, _ = prepared
    result = reconcile(integration_http_probe, root, cancel_reconcile=True)
    assert result["cancelled"] is True
    assert result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
    wait_no_advisory_locks(postgres_dsn, result["backend_pid"])
    assert snapshot(postgres_dsn) == [[], []]
    assert reconcile(integration_http_probe, root)["reconciled"] is True


def test_transaction_wait_cancellation_aborts_owned_driver_without_partial_projection(
    integration_http_probe: Path, postgres_dsn: str, prepared: tuple[Path, str, str, dict[str, Any]]
) -> None:
    root, _, _, _ = prepared
    with psycopg.connect(postgres_dsn) as blocker:
        blocker.execute("LOCK TABLE public.strategy_catalog IN ACCESS EXCLUSIVE MODE")
        blocking_pid = blocker.info.backend_pid
        with subprocess.Popen(
            [str(integration_http_probe)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as child:
            assert child.stdin is not None and child.stdout is not None and child.stderr is not None
            try:
                child.stdin.write(
                    json.dumps(
                        {
                            "op": "node-authority",
                            "action": "frozen-reconcile",
                            "root": str(root),
                            "namespace": NAMESPACE,
                            "cancel_reconcile": "blocked",
                        }
                    )
                    + "\n"
                )
                child.stdin.flush()
                barrier = json.loads(child.stdout.readline())
                wait_for_database_lock_barrier(postgres_dsn, child, barrier["barrier_pid"], blocking_pid, "relation")
                child.stdin.write("cancel\n")
                child.stdin.flush()
                child.stdin.close()
                result = json.loads(child.stdout.read())
                assert child.wait(timeout=20) == 0, child.stderr.read()
                assert result["cancelled"] is True and result["session_error"] == "PRODUCT_KERNEL_AUTHORITY_LOST"
                wait_no_advisory_locks(postgres_dsn, barrier["barrier_pid"])
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=20)
    assert snapshot(postgres_dsn) == [[], []]
    assert reconcile(integration_http_probe, root)["reconciled"] is True
