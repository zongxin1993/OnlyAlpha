"""Shipping UI acceptance with actual sealed native runtime and isolated canonical stores."""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.strategy_product import OnlyStrategyPromotionProductService
from onlyalpha.backtest import (
    OnlyBacktestDeploymentCatalog,
    OnlyBacktestEvidenceStore,
    OnlyBacktestMarketProductResourceRegistry,
)
from onlyalpha.backtest.market_adapter import OnlyMarketProductBacktestAdmissionAdapter
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation import OnlyCalculationDataType
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_json
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.strategy_product_store import OnlyPostgresStrategyProductStore
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchStatisticsResultStore,
)
from onlyalpha.research.dataset import OnlyDatasetEconomicBindingStore, OnlyResearchDatasetEconomicBinding
from onlyalpha.research.definition import (
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchSignals,
    OnlyResearchTypedLiteral,
    OnlyResearchVariableRef,
)
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreIdentity
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRequest
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterion,
    OnlyQualificationEvaluator,
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
    OnlyQualificationGate,
    OnlyQualificationPolicyRevision,
)
from onlyalpha.strategy.qualification_store import (
    OnlyQualificationPolicyStore,
    _only_compose_qualification_decision_authority,
)
from scripts.database import _initialize_deployment
from tests.backtest.test_product_engine import _deployment
from tests.certification.research_product.support import provision_product_api_master_key
from tests.research.calculation.support import bars, snapshot
from tests.research.definition.support import definition
from tests.strategy.test_strategy_freeze import _freeze_case
from tests.support.native_backtest_generation import build_native_backtest_generation

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.slow, pytest.mark.timeout(360)]


def _ready(url, process):
    # Startup readiness only; economic/recovery assertions use UI and durable barriers.
    deadline = time.monotonic() + 30
    wake = Event()
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            if process.poll() is not None:
                break
        wake.wait(0.05)
    raise AssertionError(f"service unavailable {url}, exit={process.poll()}")


def _stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def test_shipping_backtest_native_create_cancel_restart_result(postgres_dsn, tmp_path):
    repository = Path.cwd()
    root = tmp_path / "user-data"
    layout = OnlyUserDataLayout(root)
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, root)
    provision_product_api_master_key(root)
    values = tuple(x for x in bars() if str(x.instrument_id) == "A.XNAS")
    values += tuple(
        replace(
            x,
            open=OnlyPrice(x.open.value * 16, 2),
            high=OnlyPrice(x.high.value * 16, 2),
            low=OnlyPrice(x.low.value * 16, 2),
            close=OnlyPrice(x.close.value * 16, 2),
            bar_start=x.bar_start + timedelta(minutes=4),
            bar_end=x.bar_end + timedelta(minutes=4),
            ts_event=x.ts_event + timedelta(minutes=4),
            ts_init=x.ts_init + timedelta(minutes=4),
        )
        for x in values
    )
    source = definition(snapshot(values)[0].definition)
    signal0 = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchVariableRef("momentum", "factor_value"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0")),
    )
    source = replace(
        source,
        calculations=tuple(x for x in source.calculations if x.instance_key != "rsi"),
        signals=OnlyResearchSignals(signal0, signal0),
    )
    prior = tmp_path / "prior-research"
    freeze, prior_run, candidate, strategies, _ = _freeze_case(
        prior, semantic_root=layout.research_root, values=values, source_definition=source
    )
    frozen = freeze.freeze(
        OnlyStrategyFreezeRequest(prior_run.run_id, candidate.candidate_fingerprint, "controlled-prerequisite")
    )
    # These are verified existing immutable inputs, never a Backtest Run/result.
    for source_path, target in [
        (prior / "base/datasets", layout.research_dataset_root),
        (prior / "calculation-results", layout.research_calculation_result_root),
        (prior / "statistics-results", layout.research_statistics_result_root),
        (prior / "research-results", layout.research_result_root),
    ]:
        shutil.copytree(source_path, target, dirs_exist_ok=True)
    revision = strategies.load_verified(frozen.strategy_fingerprint)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    dataset_fp = prior_run.specification.dataset_snapshot_fingerprint
    document0 = _deployment(
        SimpleNamespace(bars=values, revision=revision, dataset_store=datasets, dataset_fingerprint=dataset_fp)
    )
    payload = json.loads(only_canonical_json(document0.normalized_payload))
    payload["runtime"]["base_currency"] = "CNY"
    payload["accounts"][0]["initial_cash"]["currency"] = "CNY"
    document = OnlyClusterRunConfig.from_mapping(payload, source_path="<controlled-product-config>")
    config = tmp_path / "backtest-product.json"
    config.write_text(only_canonical_json(document.normalized_payload))
    catalog = OnlyBacktestDeploymentCatalog((document,))
    factories = OnlyMarketProductFactoryRegistry()
    only_discover_plugins(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        factories,
        OnlyCalculationRegistry(),
        fail_fast=True,
    )
    market = OnlyMarketProductBacktestAdmissionAdapter(
        factories=factories,
        configurations=catalog.configurations,
        resources=OnlyBacktestMarketProductResourceRegistry(),
        instruments=catalog,
    ).resolve_for_backtest(
        catalog.configuration_fingerprints[0], revision, datasets.load_verified_table(dataset_fp).snapshot.definition
    )
    OnlyDatasetEconomicBindingStore(root).publish_verified(
        OnlyResearchDatasetEconomicBinding(dataset_fp, market.composition_fingerprint, ())
    )
    product = OnlyPostgresStrategyProductStore(
        postgres_dsn, OnlyResearchSemanticStoreIdentity(layout.research_root).load_verified()
    )
    product.ensure_strategy(frozen.strategy_fingerprint, revision.schema_version)
    product.append_freeze_record(frozen.freeze_record)
    calc = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calc)
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calc)
    policies = OnlyQualificationPolicyStore(layout.research_root)
    decisions, publisher = _only_compose_qualification_decision_authority(layout.research_root)
    policy = OnlyQualificationPolicyRevision(
        "controlled-research-backtest",
        "1",
        OnlyQualificationGate.RESEARCH_TO_BACKTEST,
        (
            OnlyQualificationCriterion(
                "statistics",
                OnlyQualificationEvidenceKind.RESEARCH_RESULT,
                "research.statistics_result_count",
                "GE",
                Decimal(1),
            ),
        ),
    )
    policies.put(policy)
    decision = OnlyQualificationEvaluator(
        strategies=strategies,
        policies=policies,
        research_results=results,
        backtest_evidence=OnlyBacktestEvidenceStore(root),
        decisions=publisher,
        research_statistics=statistics,
    ).evaluate(
        subject_strategy_fingerprint=frozen.strategy_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        evidence=(
            OnlyQualificationEvidenceReference(
                OnlyQualificationEvidenceKind.RESEARCH_RESULT,
                frozen.freeze_record.research_result_fingerprint,
                freeze._specification_resolver.resolve(prior_run.specification).workload.result_plan.fingerprint,
                frozen.freeze_record.semantic_relation.relation_fingerprint,
            ),
        ),
    )
    OnlyStrategyPromotionProductService(
        strategies=strategies,
        store=product,
        qualification_decisions=decisions,
        qualification_policies=policies,
        audit_time=lambda: prior_run.finished_at,
    ).promote_to_backtest(
        command_id=OnlyProductCommandId(str(uuid.uuid4())),
        strategy_fingerprint=frozen.strategy_fingerprint,
        qualification_decision_fingerprint=decision.decision_fingerprint,
        policy_fingerprint=policy.policy_fingerprint,
        reason="Existing controlled prerequisite for UI execution",
        actor="controlled-prerequisite",
    )
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    generation = build_native_backtest_generation(
        tmp_path / "generation",
        repository / "test-results/rust-kernel/target" / target / "release/onlyalpha-backtest-runtime",
    )
    artifacts = repository / "test-results/backtest-product/shipping-ui" / tmp_path.parent.name
    artifacts.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "ONLYALPHA_POSTGRES_DSN": postgres_dsn,
        "ONLYALPHA_WEB_API_TARGET": "http://127.0.0.1:8000",
        "OA_NATIVE_PYTHON": str(generation.environment / "bin/python"),
        "OA_NATIVE_ROOT": str(root),
        "OA_NATIVE_GENERATION_ROOT": str(generation.authority.root),
        "OA_NATIVE_GENERATION": generation.fingerprint,
        "OA_NATIVE_CONFIG": str(config),
        "OA_UI_EVIDENCE": str(artifacts),
    }
    logs = []
    processes = []
    try:
        for name, command, cwd in [
            (
                "api",
                [
                    str(generation.environment / "bin/python"),
                    "-I",
                    "-m",
                    "onlyalpha_http_server.main",
                    "--user-data-root",
                    str(root),
                    "--port",
                    "8000",
                    "--backtest-product-config",
                    str(config),
                    "--runtime-generation-authority-root",
                    str(generation.authority.root),
                ],
                repository,
            ),
            (
                "web",
                ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "4173"],
                repository / "packages/onlyalpha-web-console",
            ),
        ]:
            log = (artifacts / (name + ".log")).open("w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
            )
        _ready("http://127.0.0.1:8000/health/ready", processes[0])
        _ready("http://127.0.0.1:4173", processes[1])
        environment["OA_NATIVE_API_PID"] = str(processes[0].pid)
        completed = subprocess.run(
            ["node", "e2e-real/native-backtest.ts"],
            cwd=repository / "packages/onlyalpha-web-console",
            env=environment,
            capture_output=True,
            text=True,
            timeout=240,
        )
        (artifacts / "browser.log").write_text(completed.stdout + "\n" + completed.stderr)
        assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    finally:
        for process in reversed(processes):
            _stop(process)
        for log in logs:
            log.close()
        shutil.copytree(root, artifacts / "user-data", dirs_exist_ok=True)
        # Generation manifests/seals are retained; credentials stay only in test namespace.
