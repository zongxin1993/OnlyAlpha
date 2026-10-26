"""Reference conformance: actual sealed Generation/native journal, not Shipping acceptance."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.backtest import OnlyBacktestDeploymentCatalog, OnlyBacktestMarketProductResourceRegistry
from onlyalpha.backtest.market_adapter import OnlyMarketProductBacktestAdmissionAdapter
from onlyalpha.backtest.model import OnlyBacktestLimitPolicy
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation import OnlyCalculationDataType
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_json
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.research.dataset import OnlyDatasetEconomicBindingStore, OnlyResearchDatasetEconomicBinding
from onlyalpha.research.definition import (
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchSignals,
    OnlyResearchTypedLiteral,
    OnlyResearchVariableRef,
)
from tests.backtest.test_product_engine import _deployment, _run
from tests.research.calculation.support import bars, snapshot
from tests.research.definition.support import definition
from tests.strategy.product_support import publish_frozen_strategy_for_execution_test, strategy_product_case
from tests.support.native_backtest_generation import build_native_backtest_generation

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.timeout(360)]

# Offline integration includes a real artifact build and full owning replay (184 seconds measured warm).
# The 360-second test budget includes a cold release build; per-command deadlines remain unchanged.
EXECUTE = r"""
import json,sys
from pathlib import Path

from onlyalpha.backtest.model import OnlyBacktestRun,OnlyBacktestRunId,OnlyBacktestSpecification,OnlyBacktestAdmissionResolution
from datetime import datetime
from onlyalpha.backtest.worker import OnlyBacktestProductEnginePlanBuilder,OnlyBacktestRuntimeComposition,OnlyBacktestRuntimeCancellation
from onlyalpha.backtest import OnlyBacktestDeploymentCatalog,OnlyBacktestMarketProductResourceRegistry,only_default_backtest_profile_registry
from onlyalpha.backtest.errors import OnlyBacktestError
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.strategy import OnlyFrozenStrategyRevisionStore
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore,OnlyDatasetEconomicBindingStore
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry
assert Path(__import__('onlyalpha').__file__).is_relative_to(Path(sys.prefix))
payload=json.loads(Path(sys.argv[1]).read_text());root=Path(payload['root'])
value=payload['run'];run=OnlyBacktestRun.queued(run_id=OnlyBacktestRunId(value['run_id']),specification=OnlyBacktestSpecification.from_dict(value['specification']),admission_resolution=OnlyBacktestAdmissionResolution.from_dict(value['admission_resolution']),queued_at=datetime.fromisoformat(value['queued_at']));document=OnlyClusterRunConfig.from_mapping(payload['document'],source_path='<native-integration>')
strategies=OnlyFrozenStrategyRevisionStore(root/'research');datasets=OnlyParquetResearchDatasetSnapshotStore(Path(payload['datasets']));bindings=OnlyDatasetEconomicBindingStore(root)
registry=OnlyRuntimeGenerationRegistry(Path(payload['authority']))
plans=OnlyBacktestProductEnginePlanBuilder(user_data_root=root,catalog=OnlyBacktestDeploymentCatalog((document,)),strategies=strategies,datasets=datasets,profiles=only_default_backtest_profile_registry(),market_product_resources=OnlyBacktestMarketProductResourceRegistry())
executor=registry.backtest_executor(OnlyBacktestRuntimeComposition(plans,strategies,datasets,bindings,root,payload['generation']))
progress_path=root/'backtest/runtimes'/run.run_id.value/'progress.json'
def pause():
 return 'PAUSE' if progress_path.is_file() and json.loads(progress_path.read_text())['cursor']>=1 else 'CONTINUE'
try: executor.execute(run,pause,initialize=True)
except OnlyBacktestError as error: assert error.code=='BACKTEST_WORKER_INTERRUPTED',str(error)
else: raise AssertionError('expected durable pause')
progress=json.loads((root/'backtest/runtimes'/run.run_id.value/'progress.json').read_text())
assert progress['cursor']==1,progress
# Missing history is not a fresh Run. Damage only copies, preserving the owned prefix.
import shutil
for damage in ('journal','directory','empty-first-attempt'):
 broken=root.parent/('broken-'+damage)
 shutil.copytree(root,broken)
 native=broken/'backtest/runtimes'/run.run_id.value/'native'
 if damage=='journal': (native/'runtime.sqlite3').unlink()
 elif damage=='directory': shutil.rmtree(native)
 else:
  shutil.rmtree(native); native.mkdir()
 damaged=registry.backtest_executor(OnlyBacktestRuntimeComposition(plans,strategies,datasets,bindings,broken,payload['generation']))
 try: damaged.execute(run,lambda:'CONTINUE',initialize=damage=='empty-first-attempt')
 except OnlyBacktestError as error: assert error.code=='BACKTEST_NATIVE_HISTORY_UNAVAILABLE',str(error)
 else: raise AssertionError('missing native history was reinitialized: '+damage)
 assert not (native/'runtime.sqlite3').exists()
 shutil.rmtree(broken)
first=executor.execute(run,lambda:'CONTINUE');second=executor.execute(run,lambda:'CONTINUE')
assert first==second,'same exact Run reopen must preserve every result/artifact byte'
result=json.loads(dict((name,data) for name,data,_ in first.artifacts)['result.json'])
assert result['run']['status']=='COMPLETED',result['diagnostics']
assert result['execution']['trade_count']==2,result['execution']
assert result['execution']['order_count']==2,result['orders']
# Virtual Broker LIMIT matches at the configured limit: 100000 - 200 - .20 + 64 - .06.
assert result['runtime_performance']['summary']['final_equity']=='99863.74',result['runtime_performance']
assert result['runtime_performance']['summary']['fees']=='0.26'
assert result['reconciliation']['status']!='MISMATCHED'
from onlyalpha.backtest.worker import _manifest
from onlyalpha.backtest.evidence import OnlyBacktestEvidenceStore
from onlyalpha.backtest.native_evidence import only_verify_native_backtest_evidence
manifest,artifacts=_manifest(run,first);evidence=OnlyBacktestEvidenceStore(root);evidence.publish(manifest,artifacts)
verified=only_verify_native_backtest_evidence(run,manifest,evidence,registry,dataset=datasets.load_verified_table(run.admission_resolution.base_dataset_snapshot_fingerprint),plans=plans,strategies=strategies,datasets=datasets,dataset_bindings=bindings)
assert verified['result']==result
# Mint coherent replacement envelopes, rather than testing only stale hashes.
from copy import deepcopy
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.backtest.worker import OnlyBacktestRuntimeExecutionResult
from onlyalpha.backtest.errors import OnlyBacktestIntegrityError
for mutation in ('causal-processing','broker-not-drained','wrong-capital','wrong-policy','missing-steps','changed-equity'):
 values={name:json.loads(content) for name,content,_ in first.artifacts}
 target_run=run
 if mutation=='missing-steps': values['replay-trace.json']['steps']=[]
 elif mutation=='changed-equity': values['result.json']['runtime_performance']['summary']['final_equity']='1.00'
 elif mutation=='causal-processing':
  step=next(row['step'] for row in values['replay-trace.json']['steps'] if row['step']['cause']['kind']=='BAR' and row['step']['inputs'])
  step['cause']['processing']['processing']=None
 elif mutation=='broker-not-drained':
  values['replay-trace.json']['steps'][-1]['step']['state']['participants']['world']['pending']=1
  values['replay-trace.json']['state']=deepcopy(values['replay-trace.json']['steps'][-1]['step']['state'])
 elif mutation in ('wrong-capital','wrong-policy'):
  from dataclasses import replace
  spec=replace(run.specification,initial_capital='200000.00') if mutation=='wrong-capital' else replace(run.specification,order_policy=replace(run.specification.order_policy,entry_limit='99.00'))
  target_run=OnlyBacktestRun.queued(run_id=run.run_id,specification=spec,admission_resolution=run.admission_resolution,queued_at=run.queued_at)
  values['runtime.json']['specification_fingerprint']=target_run.specification_fingerprint
  from onlyalpha_runtime_generation_manager.backtest_plan import only_build_native_backtest_plan, only_native_backtest_plan_fingerprint
  from onlyalpha_calculation_worker.artifact import manifest as worker_manifest
  _,target_configs,_=plans.build(target_run)
  target_plan=only_build_native_backtest_plan(target_run,config=target_configs[0],strategy=strategies.load_verified(target_run.specification.strategy_fingerprint),inputs=values['replay-trace.json']['inputs'],generation=payload['generation'],native_artifact=values['runtime.json']['native_artifact_sha256'],worker_artifact=worker_manifest().implementation_fingerprint,python=Path(sys.executable))
  values['runtime.json']['plan_fingerprint']=only_native_backtest_plan_fingerprint(target_plan)
 previous=only_canonical_fingerprint(values['replay-trace.json']['binding'])
 for row in values['replay-trace.json']['steps']:
  row['step']['previous']=previous
  previous=only_canonical_fingerprint(row['step'])
 changed=values['result.json'];sealed={k:v for k,v in changed.items() if k not in {'id','result_fingerprint','determinism_fingerprint'}}
 changed['result_fingerprint']=only_canonical_fingerprint(sealed)
 changed['id']='BTR-'+only_canonical_fingerprint({**sealed,'result_fingerprint':changed['result_fingerprint'],'determinism_fingerprint':changed['determinism_fingerprint']})
 values['runtime.json']['result_fingerprint']=changed['result_fingerprint']
 values['replay-proof.json']['execution_result']=deepcopy(changed)
 values['replay-proof.json']['source']=only_canonical_fingerprint(values['replay-trace.json'])
 candidate=OnlyBacktestRuntimeExecutionResult(changed['result_fingerprint'],changed['determinism_fingerprint'],tuple((name,__import__('onlyalpha.canonical',fromlist=['only_canonical_json']).only_canonical_json(value).encode(),'application/json') for name,value in sorted(values.items())))
 counterfeit,parts=_manifest(target_run,candidate);mutants=OnlyBacktestEvidenceStore(root/'mutants'/mutation);mutants.publish(counterfeit,parts)
 try: only_verify_native_backtest_evidence(target_run,counterfeit,mutants,registry,dataset=datasets.load_verified_table(run.admission_resolution.base_dataset_snapshot_fingerprint),plans=plans,strategies=strategies,datasets=datasets,dataset_bindings=bindings)
 except OnlyBacktestIntegrityError: pass
 else: raise AssertionError('coherently rehashed native evidence accepted: '+mutation)
registry.release_work(run.run_id.value,actor='test-completed',occurred_at=run.queued_at)
assert only_verify_native_backtest_evidence(run,manifest,evidence,registry,dataset=datasets.load_verified_table(run.admission_resolution.base_dataset_snapshot_fingerprint),plans=plans,strategies=strategies,datasets=datasets,dataset_bindings=bindings)==verified
print(json.dumps({'result':first.result_fingerprint,'determinism':first.determinism_fingerprint,'execution':result['execution']}))
"""


def test_exact_sealed_generation_executes_factor_and_recovers_same_rust_run(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    executable = repository / "test-results/rust-kernel/target" / target / "release/onlyalpha-backtest-runtime"
    values = tuple(item for item in bars() if str(item.instrument_id) == "A.XNAS")
    values = values + tuple(
        replace(
            item,
            open=OnlyPrice(item.open.value * 16, 2),
            high=OnlyPrice(item.high.value * 16, 2),
            low=OnlyPrice(item.low.value * 16, 2),
            close=OnlyPrice(item.close.value * 16, 2),
            bar_start=item.bar_start + timedelta(minutes=4),
            bar_end=item.bar_end + timedelta(minutes=4),
            ts_event=item.ts_event + timedelta(minutes=4),
            ts_init=item.ts_init + timedelta(minutes=4),
        )
        for item in values
    )
    definition0 = definition(snapshot(values)[0].definition)
    definition0 = replace(
        definition0, calculations=tuple(item for item in definition0.calculations if item.instance_key != "rsi")
    )
    signal = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchVariableRef("momentum", "factor_value"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0")),
    )
    case = strategy_product_case(
        tmp_path / "case",
        values=values,
        source_definition=replace(definition0, signals=OnlyResearchSignals(signal, signal)),
    )
    root = tmp_path / "user-data"
    publish_frozen_strategy_for_execution_test(root / "research", case.revision)
    document0 = _deployment(case)
    document_payload = json.loads(only_canonical_json(document0.normalized_payload))
    document_payload["runtime"]["base_currency"] = "CNY"
    document_payload["accounts"][0]["initial_cash"]["currency"] = "CNY"
    from onlyalpha.config import OnlyClusterRunConfig

    document = OnlyClusterRunConfig.from_mapping(document_payload, source_path="<native-conformance-cny>")
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
        catalog.configuration_fingerprints[0],
        case.revision,
        case.dataset_store.load_verified_table(case.dataset_fingerprint).snapshot.definition,
    )
    binding = OnlyResearchDatasetEconomicBinding(case.dataset_fingerprint, market.composition_fingerprint, ())
    OnlyDatasetEconomicBindingStore(root).publish_verified(binding)
    old = _run(case, document, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    spec = replace(
        old.specification,
        base_currency="CNY",
        dataset_binding_fingerprint=binding.fingerprint,
        schema_version=2,
        order_policy=OnlyBacktestLimitPolicy("2", "100.00", "32.00", "2", 1),
    )
    resolution = replace(
        old.admission_resolution,
        dataset_binding_fingerprint=binding.fingerprint,
        market_product_composition_fingerprint=market.composition_fingerprint,
        implementation_fingerprints=tuple(
            sorted(
                {
                    *market.implementation_fingerprints,
                    *(item.trading_implementation_fingerprint for item in case.revision.implementation_bindings),
                }
            )
        ),
    )
    run = type(old).queued(
        run_id=old.run_id, specification=spec, admission_resolution=resolution, queued_at=old.queued_at
    )
    generation = build_native_backtest_generation(tmp_path / "generation", executable)
    from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore

    distributions = {
        item.distribution_name
        for item in OnlyLocalImmutableArtifactStore(generation.authority.root / "artifacts").manifests()
    }
    assert "onlyalpha-runtime-generation-manager" in distributions
    assert not {"onlyalpha-http-server", "onlyalpha-agent-orchestrator"}.intersection(distributions)
    generation.authority.bind_new_work_exact(
        run.run_id.value,
        generation.fingerprint,
        owner="native-integration-command",
        actor="test-setup",
        occurred_at=datetime(2026, 10, 21, tzinfo=UTC),
    )
    payload = tmp_path / "input.json"
    payload.write_text(
        only_canonical_json(
            {
                "root": str(root),
                "datasets": str(tmp_path / "case/datasets"),
                "authority": str(generation.authority.root),
                "generation": generation.fingerprint,
                "run": {
                    "run_id": run.run_id.value,
                    "specification": run.specification.to_dict(),
                    "admission_resolution": run.admission_resolution.to_dict(),
                    "queued_at": run.queued_at.isoformat(),
                },
                "document": document.normalized_payload,
            }
        )
    )
    completed = subprocess.run(
        [str(generation.environment / "bin/python"), "-I", "-c", EXECUTE, str(payload)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, (
        completed.stdout
        + "\n"
        + completed.stderr
        + "\n"
        + "\n".join(path.read_text() for path in root.glob("backtest/runtimes/*/native.stderr.log"))
    )
    assert len(json.loads(completed.stdout)["result"]) == 64

    # Deployment locators may change without replacing any authority, input or executable bytes.
    moved_environment = tmp_path / "moved-reader"
    generation.environment.rename(moved_environment)
    moved_root = tmp_path / "moved-user-data"
    root.rename(moved_root)
    moved_payload = json.loads(payload.read_text())
    moved_payload["root"] = str(moved_root)
    payload.write_text(only_canonical_json(moved_payload))
    read_script = (
        EXECUTE[: EXECUTE.index("executor=registry.backtest_executor")]
        + r"""
from onlyalpha.backtest.evidence import OnlyBacktestEvidenceStore
from onlyalpha.backtest.native_evidence import only_verify_native_backtest_evidence
evidence=OnlyBacktestEvidenceStore(root);manifest=evidence.find_for_run(run.run_id.value)
assert manifest is not None
value=only_verify_native_backtest_evidence(run,manifest,evidence,registry,dataset=datasets.load_verified_table(run.admission_resolution.base_dataset_snapshot_fingerprint),plans=plans,strategies=strategies,datasets=datasets,dataset_bindings=bindings)
assert value['result']['runtime_performance']['summary']['final_equity']=='99863.74'
print(value['result']['result_fingerprint'])
"""
    )
    moved = subprocess.run(
        [str(moved_environment / "bin/python"), "-I", "-c", read_script, str(payload)],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert moved.returncode == 0, moved.stdout + moved.stderr
    assert moved.stdout.strip() == json.loads(completed.stdout)["result"]
