"""Exact Generation composition of the existing native Backtest Application."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from onlyalpha.backtest.dataset_source import only_backtest_dataset_source_fingerprint
from onlyalpha.backtest.errors import OnlyBacktestError, OnlyBacktestErrorPhase
from onlyalpha.backtest.model import OnlyBacktestRun, OnlyBacktestSpecification
from onlyalpha.backtest.worker import (
    OnlyBacktestRuntimeCancellation,
    OnlyBacktestRuntimeComposition,
    OnlyBacktestRuntimeControl,
    OnlyBacktestRuntimeExecutionResult,
    OnlyEngineBacktestRuntimeExecutor,
)
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.distribution import OnlyDistributionArtifactManifest, OnlyDistributionArtifactRole
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.strategy.revision import OnlyStrategyRevision

from .artifact_store import OnlyLocalImmutableArtifactStore
from .backtest_plan import only_build_native_backtest_plan, only_native_backtest_plan_fingerprint
from .backtest_process import OnlyNativeBacktestProcess
from .builder import OnlyRuntimeGenerationBuilder

if TYPE_CHECKING:
    from onlyalpha.backtest.admission import OnlyBacktestDatasetBindingReader
    from onlyalpha.backtest.worker import OnlyBacktestEnginePlanBuilder
    from onlyalpha.research.dataset.ports import OnlyBoundedResearchDatasetSnapshotStore
    from onlyalpha.strategy.store import OnlyStrategyRevisionReader

    from .registry import OnlyRuntimeGenerationRegistry


def _native(
    registry: OnlyRuntimeGenerationRegistry, generation: str, *, historical: bool = False
) -> OnlyDistributionArtifactManifest | None:
    manifest = (
        registry.require_historical_generation(generation)
        if historical
        else registry.require_runtime_generation(generation)
    )
    artifacts = OnlyLocalImmutableArtifactStore(registry.root / "artifacts")
    OnlyRuntimeGenerationBuilder(artifacts, Path(sys.executable)).verify_exact_artifacts(manifest)
    matches = [artifacts.fetch_exact(sha)[0] for sha in manifest.artifact_sha256s]
    if {item.manifest_fingerprint for item in matches} != set(manifest.artifact_manifest_fingerprints):
        _reject("BACKTEST_NATIVE_ARTIFACT_MISMATCH")
    native = [item for item in matches if item.role is OnlyDistributionArtifactRole.BACKTEST_RUNTIME]
    if len(native) > 1 or (
        native and native[0].tested_core_execution_fingerprint != manifest.core_execution.fingerprint
    ):
        _reject("BACKTEST_NATIVE_ARTIFACT_MISMATCH")
    return native[0] if native else None


def only_validate_native_backtest_specification(
    specification: OnlyBacktestSpecification, strategy: OnlyStrategyRevision
) -> None:
    recipe = strategy.market_input_contract.construction_requirement.recipe
    if len(strategy.universe.instruments) != 1:
        _reject("BACKTEST_NATIVE_SHAPE_UNSUPPORTED")
    if recipe is None or recipe.kind.value != "PROVIDER_NATIVE":
        _reject("BACKTEST_NATIVE_RECIPE_UNSUPPORTED")
    if strategy.market_input_contract.bar_semantic.adjustment_policy.value != "RAW":
        _reject("BACKTEST_NATIVE_ADJUSTMENT_UNSUPPORTED")
    from onlyalpha_plugin_generic_t0_cash.fee_pack import only_generic_t0_cash_market_fee_pack

    expected = only_canonical_fingerprint(
        {
            "plugin_id": "onlyalpha-plugin-generic-t0-cash",
            "product_id": "GENERIC_T0_CASH",
            "product_version": "1",
            "config": {},
        }
    )
    if specification.market_product_configuration_fingerprint != expected:
        _reject("BACKTEST_NATIVE_MARKET_UNSUPPORTED")
    # Read the plugin's current fee authority; never invent a conversion or alter fees.
    pack = only_generic_t0_cash_market_fee_pack()
    if any(item.currency.code != specification.base_currency for item in pack.schedules):
        _reject("BACKTEST_NATIVE_FEE_CURRENCY_UNSUPPORTED")


def validate_backtest_work(
    registry: OnlyRuntimeGenerationRegistry, run: OnlyBacktestRun, strategy: OnlyStrategyRevision
) -> None:
    binding = registry.require_work_binding(run.run_id.value)
    generation = binding.runtime_generation_fingerprint
    native = _native(registry, generation)
    if (native is None) != (run.specification.order_policy is None):
        _reject("BACKTEST_NATIVE_RUNTIME_REQUIRED" if native is not None else "BACKTEST_NATIVE_RUNTIME_UNAVAILABLE")
    if native is None:
        return
    only_validate_native_backtest_specification(run.specification, strategy)
    manifest = registry.require_runtime_generation(generation)
    available = {item.implementation_fingerprint for item in manifest.implementations if item.backend == "TRADING"}
    required = {item.trading_implementation_fingerprint for item in strategy.implementation_bindings}
    if not required <= available or str(strategy.strategy_fingerprint) != run.specification.strategy_fingerprint:
        _reject("BACKTEST_NATIVE_STRATEGY_CLOSURE_MISMATCH")


def _reject(code: str) -> NoReturn:
    raise OnlyBacktestError(OnlyBacktestErrorPhase.ADMISSION, code, "Exact native Runtime closure is unavailable")


class OnlyGenerationBacktestExecutor:
    def __init__(self, registry: OnlyRuntimeGenerationRegistry, composition: OnlyBacktestRuntimeComposition) -> None:
        self._registry = registry
        self._composition = composition

    def execute(
        self, run: OnlyBacktestRun, control: OnlyBacktestRuntimeControl, *, initialize: bool = False
    ) -> OnlyBacktestRuntimeExecutionResult | OnlyBacktestRuntimeCancellation:
        c = self._composition
        generation = c.process_generation_fingerprint
        self._registry.require_work_generation(run.run_id.value, generation)
        self._registry.verify_hosted_generation(generation)
        native = _native(self._registry, generation)
        if native is None:
            if run.specification.order_policy is not None:
                _reject("BACKTEST_NATIVE_RUNTIME_UNAVAILABLE")
            return OnlyEngineBacktestRuntimeExecutor(c.plans).execute(run, control)
        strategy = c.strategies.load_verified(run.specification.strategy_fingerprint)
        validate_backtest_work(self._registry, run, strategy)
        control()
        _, configs, _ = c.plans.build(run)
        if len(configs) != 1:
            _reject("BACKTEST_NATIVE_PLAN_CLOSURE")
        from onlyalpha_calculation_worker.artifact import manifest as worker_manifest
        from onlyalpha_calculation_worker.backtest_dataset import load_dataset_inputs

        source = only_backtest_dataset_source_fingerprint(
            run.admission_resolution.base_dataset_snapshot_fingerprint, run.specification.dataset_binding_fingerprint
        )
        inputs = load_dataset_inputs(
            c.datasets,
            c.dataset_bindings,
            run.specification.dataset_binding_fingerprint,
            source,
            f"snapshot-{run.admission_resolution.base_dataset_snapshot_fingerprint}",
            0,
            run.admission_resolution.market_product_composition_fingerprint,
        )
        plan = only_build_native_backtest_plan(
            run,
            config=configs[0],
            strategy=strategy,
            inputs=inputs,
            generation=generation,
            native_artifact=native.artifact_sha256,
            worker_artifact=worker_manifest().implementation_fingerprint,
            python=Path(sys.executable),
        )
        executable = Path(sys.prefix) / "artifacts" / native.artifact_logical_name
        if executable.is_symlink() or hashlib.sha256(executable.read_bytes()).hexdigest() != native.artifact_sha256:
            _reject("BACKTEST_NATIVE_ARTIFACT_MISMATCH")
        base = OnlyUserDataLayout(c.user_data_root).backtest_root / "runtimes" / run.run_id.value
        if any(path.is_symlink() for path in (base.parent.parent, base.parent, base, base / "native")):
            _reject("BACKTEST_NATIVE_RUNTIME_ROOT_INVALID")
        root = base / "native"
        journal = root / "runtime.sqlite3"
        if (root.exists() and not journal.is_file()) or (not root.exists() and not initialize):
            raise OnlyBacktestError(
                OnlyBacktestErrorPhase.OPERATIONAL, "BACKTEST_NATIVE_HISTORY_UNAVAILABLE", run.run_id.value
            )
        base.mkdir(parents=True, exist_ok=True)
        control()
        # RunLoop's owning store holds its exclusive process lock. An expired Attempt
        # cannot open a second owner while the former process remains alive.
        with OnlyNativeBacktestProcess(
            executable, plan, root, base / "native.stderr.log", initialize=initialize
        ) as process:
            progress = process.progress
            while progress["status"] != "TERMINATED":
                command = control()
                if command == "CANCEL":
                    process.exchange("TERMINATE", status="CANCELLED")
                    return OnlyBacktestRuntimeCancellation()
                if command == "PAUSE":
                    if progress["status"] == "RUNNING":
                        process.exchange("PAUSE")
                    raise OnlyBacktestError(
                        OnlyBacktestErrorPhase.OPERATIONAL, "BACKTEST_WORKER_INTERRUPTED", run.run_id.value
                    )
                if progress["status"] == "PAUSED":
                    progress = process.exchange("RESUME")
                elif progress["cursor"] == progress["total"]:
                    progress = process.exchange("FINISH")
                else:
                    # Resource admission belongs to this versioned Application,
                    # not to the market-independent Kernel. Preserve the prefix.
                    journal = root / "runtime.sqlite3"
                    if journal.stat().st_size > 128 * 1024 * 1024:
                        process.exchange("TERMINATE", status="INCOMPLETE", reason="JOURNAL_RESOURCE_LIMIT")
                        raise OnlyBacktestError(
                            OnlyBacktestErrorPhase.OPERATIONAL,
                            "BACKTEST_NATIVE_RESOURCE_LIMIT",
                            "Native journal exceeded its 128 MiB execution budget; select a smaller sealed dataset",
                        )
                    progress = process.exchange("STEP")["progress"]
                _write_progress(base, progress)
            if progress["outcome"]["status"] == "CANCELLED":
                return OnlyBacktestRuntimeCancellation()
            control()
            exports = process.exchange("EXPORT")
            files: dict[str, bytes] = {}
            if set(exports) != {"files"} or set(exports["files"]) != {
                "result.json",
                "replay-proof.json",
                "replay-trace.json",
            }:
                _reject("BACKTEST_NATIVE_EXPORT_INVALID")
            for name, descriptor in exports["files"].items():
                path = root / "reports" / name
                if (
                    path.is_symlink()
                    or type(descriptor.get("size")) is not int
                    or not 0 < descriptor["size"] <= 1024**3
                ):
                    _reject("BACKTEST_NATIVE_EXPORT_INVALID")
                with path.open("rb") as stream:
                    content = stream.read(descriptor["size"] + 1)
                if len(content) != descriptor["size"] or hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
                    _reject("BACKTEST_NATIVE_EXPORT_INVALID")
                files[name] = content
            proof = json.loads(files["replay-proof.json"])
            result = json.loads(files["result.json"])
            if (
                proof["execution_result"] != result
                or proof["status"] != "COMPLETED"
                or result["run"]["status"] != "COMPLETED"
                or proof["outcome"]["status"] != "COMPLETED"
                or not proof["market_exhausted"]
                or not proof["drained"]
                or not proof["processed_prefix_verified"]
                or result["scope"] != plan["configuration"]
            ):
                raise OnlyBacktestError(
                    OnlyBacktestErrorPhase.EXECUTION,
                    "BACKTEST_NATIVE_INCOMPLETE",
                    "Native owning result did not certify completion and drain",
                )
            provenance = {
                "schema_version": 1,
                "implementation": "RUST",
                "backtest_run_id": run.run_id.value,
                "runtime_generation_fingerprint": generation,
                "native_artifact_sha256": native.artifact_sha256,
                "specification_fingerprint": run.specification_fingerprint,
                "admission_resolution_fingerprint": run.admission_resolution_fingerprint,
                "strategy_fingerprint": run.specification.strategy_fingerprint,
                "dataset_binding_fingerprint": run.specification.dataset_binding_fingerprint,
                "plan_fingerprint": only_native_backtest_plan_fingerprint(plan),
                "binding": progress["binding"],
                "result_fingerprint": result["result_fingerprint"],
            }
            files["runtime.json"] = only_canonical_json(provenance).encode()
            control()
            return OnlyBacktestRuntimeExecutionResult(
                result["result_fingerprint"],
                result["determinism_fingerprint"],
                tuple((name, content, "application/json") for name, content in sorted(files.items())),
            )


def _write_progress(base: Path, progress: dict[str, Any]) -> None:
    # Disposable projection for observability only. It grants no claim or completion.
    temporary = base / ".progress.tmp"
    temporary.write_text(only_canonical_json(progress), encoding="utf-8")
    temporary.replace(base / "progress.json")


def only_verify_native_result(
    registry: OnlyRuntimeGenerationRegistry,
    artifact_store: OnlyLocalImmutableArtifactStore,
    artifact: OnlyDistributionArtifactManifest,
    run: OnlyBacktestRun,
    plans: OnlyBacktestEnginePlanBuilder,
    strategies: OnlyStrategyRevisionReader,
    datasets: OnlyBoundedResearchDatasetSnapshotStore,
    dataset_bindings: OnlyBacktestDatasetBindingReader,
    plan_fingerprint: str,
    result: Mapping[str, object],
    trace: Mapping[str, object],
) -> None:
    """Read-only Kernel re-derivation through the exact retained executable bytes."""
    import os
    import signal
    import subprocess
    import tempfile

    from onlyalpha_calculation_worker.artifact import manifest as worker_manifest
    from onlyalpha_calculation_worker.backtest_dataset import load_dataset_inputs

    from onlyalpha.backtest.errors import OnlyBacktestIntegrityError, OnlyBacktestProofUnavailableError

    generation = registry.require_work_binding_evidence(run.run_id.value).runtime_generation_fingerprint
    try:
        registry.verify_hosted_generation(generation)
    except (RuntimeError, OSError) as exc:
        raise OnlyBacktestProofUnavailableError("Retained exact Generation reader is unavailable") from exc
    _, configs, _ = plans.build(run)
    if len(configs) != 1:
        raise OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", "Native owning plan closure differs")
    source = only_backtest_dataset_source_fingerprint(
        run.admission_resolution.base_dataset_snapshot_fingerprint, run.specification.dataset_binding_fingerprint
    )
    inputs = load_dataset_inputs(
        datasets,
        dataset_bindings,
        run.specification.dataset_binding_fingerprint,
        source,
        f"snapshot-{run.admission_resolution.base_dataset_snapshot_fingerprint}",
        0,
        run.admission_resolution.market_product_composition_fingerprint,
    )
    plan = only_build_native_backtest_plan(
        run,
        config=configs[0],
        strategy=strategies.load_verified(run.specification.strategy_fingerprint),
        inputs=inputs,
        generation=generation,
        native_artifact=artifact.artifact_sha256,
        worker_artifact=worker_manifest().implementation_fingerprint,
        python=Path(sys.executable),
    )
    if only_native_backtest_plan_fingerprint(plan) != plan_fingerprint:
        raise OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", "Native durable Run plan differs")
    payload = only_canonical_json({"result": result, "trace": trace, "plan": plan}).encode()
    if len(payload) > 128 * 1024 * 1024:
        raise OnlyBacktestProofUnavailableError("Native result verification exceeds its resource budget")
    _, content = artifact_store.fetch_exact(artifact.artifact_sha256)
    try:
        with tempfile.TemporaryDirectory(prefix="onlyalpha-native-result-") as temporary:
            binary = Path(temporary) / "runtime.elf"
            binary.write_bytes(content)
            binary.chmod(0o500)
            with subprocess.Popen(
                [str(binary), "--verify-result"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            ) as process:
                try:
                    stdout, _ = process.communicate(payload, timeout=30)
                except BaseException:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=10)
                    raise
                returncode = process.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OnlyBacktestProofUnavailableError("Exact native result reader is unavailable") from exc
    expected = only_canonical_json({"verified_result": result["result_fingerprint"]}).encode() + b"\n"
    if returncode != 0 or stdout != expected:
        raise OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", "Native owning result re-derivation failed")
