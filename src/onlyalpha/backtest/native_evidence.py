"""Read-only validation of native Backtest Evidence relations across existing owners."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.dataset.codec import only_table_to_bars
from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset
from onlyalpha.strategy.revision import OnlyStrategyRevision

from .dataset_source import only_backtest_dataset_source_fingerprint
from .errors import OnlyBacktestError, OnlyBacktestIntegrityError, OnlyBacktestProofUnavailableError
from .evidence import OnlyBacktestEvidenceManifest, OnlyBacktestEvidenceStore
from .model import OnlyBacktestRun

if TYPE_CHECKING:
    from onlyalpha.backtest.admission import OnlyBacktestDatasetBindingReader
    from onlyalpha.backtest.worker import OnlyBacktestEnginePlanBuilder
    from onlyalpha.research.dataset.ports import OnlyBoundedResearchDatasetSnapshotStore
    from onlyalpha.strategy.store import OnlyStrategyRevisionReader


def only_verify_native_backtest_evidence(
    run: OnlyBacktestRun,
    manifest: OnlyBacktestEvidenceManifest,
    evidence: OnlyBacktestEvidenceStore,
    authority: OnlyRuntimeGenerationWorkAuthority | None,
    *,
    dataset: OnlyVerifiedResearchDataset | None = None,
    plans: OnlyBacktestEnginePlanBuilder | None = None,
    strategies: OnlyStrategyRevisionReader | None = None,
    datasets: OnlyBoundedResearchDatasetSnapshotStore | None = None,
    dataset_bindings: OnlyBacktestDatasetBindingReader | None = None,
) -> dict[str, Any]:
    try:
        if {item[0] for item in manifest.artifacts} != {
            "result.json",
            "runtime.json",
            "replay-proof.json",
            "replay-trace.json",
        }:
            raise ValueError("native evidence closure")

        def read(name: str) -> dict[str, Any]:
            raw, _ = evidence.read_artifact(manifest.evidence_fingerprint, name)
            value = json.loads(raw)
            if type(value) is not dict:
                raise ValueError("native evidence object")
            return value

        runtime = read("runtime.json")
        result = read("result.json")
        proof = read("replay-proof.json")
        trace = read("replay-trace.json")
        expected = {
            "backtest_run_id": run.run_id.value,
            "specification_fingerprint": run.specification_fingerprint,
            "admission_resolution_fingerprint": run.admission_resolution_fingerprint,
            "strategy_fingerprint": run.specification.strategy_fingerprint,
            "dataset_binding_fingerprint": run.specification.dataset_binding_fingerprint,
            "result_fingerprint": manifest.result_fingerprint,
        }
        if (
            runtime["implementation"] != "RUST"
            or runtime["schema_version"] != 1
            or any(runtime.get(key) != value for key, value in expected.items())
        ):
            raise ValueError("native provenance relation")
        if authority is None:
            raise OnlyBacktestProofUnavailableError("Native retained authority is unavailable")
        scope = result["scope"]
        name = f"backtest-{run.run_id.value}"
        if (
            scope["engine"] != name + "-engine"
            or scope["runtime"] != name + "-runtime"
            or scope["generation"] != runtime["runtime_generation_fingerprint"]
            or scope["runtime_kind"] != "BACKTEST"
            or set(scope["profiles"]) != {name}
            or scope["profiles"][name]["revision"] != run.specification.strategy_fingerprint
        ):
            raise ValueError("native scope relation")
        sealed = dict(result)
        identity = sealed.pop("id")
        fingerprint = sealed.pop("result_fingerprint")
        determinism = sealed.pop("determinism_fingerprint")
        if (
            fingerprint != manifest.result_fingerprint
            or determinism != manifest.determinism_fingerprint
            or only_canonical_fingerprint(sealed) != fingerprint
            or identity
            != "BTR-"
            + only_canonical_fingerprint(
                {**sealed, "result_fingerprint": fingerprint, "determinism_fingerprint": determinism}
            )
        ):
            raise ValueError("native result identity")
        binding = trace["binding"]
        inputs = trace["inputs"]
        if (
            proof["execution_result"] != result
            or proof["source"] != only_canonical_fingerprint(trace)
            or proof["binding"] != only_canonical_fingerprint(binding)
            or runtime["binding"] != proof["binding"]
            or binding["configuration"] != only_canonical_fingerprint(scope)
            or binding["input_pin"] != only_canonical_fingerprint(inputs)
            or any(binding[key] != runtime["native_artifact_sha256"] for key in ("kernel_artifact", "driver_artifact"))
        ):
            raise ValueError("native replay relation")
        if (
            proof["status"] != "COMPLETED"
            or result["run"]["status"] != "COMPLETED"
            or proof["outcome"] != {"schema_version": 1, "status": "COMPLETED", "reason": None}
            or any(proof[key] is not True for key in ("market_exhausted", "processed_prefix_verified", "drained"))
            or result["closure"]["complete"] is not True
        ):
            raise ValueError("native completion relation")
        if (
            len(inputs["sources"]) != 1
            or inputs["sources"][0]["snapshot"] != run.admission_resolution.base_dataset_snapshot_fingerprint
            or inputs["sources"][0]["dataset_binding"] != run.specification.dataset_binding_fingerprint
            or inputs["sources"][0]["rows"] != len(inputs["records"])
            or trace["state"]["cursor"] != len(inputs["records"])
            or trace["state"]["status"] != "TERMINATED"
            or trace["state"]["outcome"] != proof["outcome"]
        ):
            raise ValueError("native immutable input relation")
        if (
            dataset is None
            or dataset.snapshot.snapshot_fingerprint != run.admission_resolution.base_dataset_snapshot_fingerprint
        ):
            raise OnlyBacktestProofUnavailableError("Native physical Dataset proof is unavailable")
        if [row["bar"] for row in inputs["records"]] != [bar.to_dict() for bar in only_table_to_bars(dataset.table)]:
            raise ValueError("native Dataset physical content relation")
        expected_source = only_backtest_dataset_source_fingerprint(
            dataset.snapshot.snapshot_fingerprint, run.specification.dataset_binding_fingerprint
        )
        if inputs["sources"][0]["source"] != expected_source or result["manifest"]["input_pin"] != binding["input_pin"]:
            raise ValueError("native input identity relation")
        program = binding["initial_state"]["participants"]["preparation"]["strategy"]["program"]
        product = program["revision"]["product"]
        revision = OnlyStrategyRevision.from_dict(product["source"])
        if (
            str(revision.strategy_fingerprint) != run.specification.strategy_fingerprint
            or program["revision"]["strategy_fingerprint"] != str(revision.strategy_fingerprint)
            or program["generation"] != scope["generation"]
            or program["scope"] != {"engine": scope["engine"], "runtime": scope["runtime"], "cluster": name}
            or program["source"] != inputs["sources"][0]["source"]
        ):
            raise ValueError("native Strategy materialization relation")
        if plans is None or strategies is None or datasets is None or dataset_bindings is None:
            raise OnlyBacktestProofUnavailableError("Native owning plan readers are unavailable")
        authority.validate_backtest_result_binding(
            run.run_id.value,
            runtime["runtime_generation_fingerprint"],
            runtime["native_artifact_sha256"],
            run=run,
            plans=plans,
            strategies=strategies,
            datasets=datasets,
            dataset_bindings=dataset_bindings,
            plan_fingerprint=runtime["plan_fingerprint"],
            result=result,
            trace=trace,
        )
        return {"schema_version": 1, "implementation": "RUST", "runtime": runtime, "result": result}
    except OnlyBacktestError:
        raise
    except Exception as exc:
        raise OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", run.run_id.value) from exc
