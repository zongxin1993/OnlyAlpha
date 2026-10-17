"""Hermetic cross-language check; invoked with Cargo's exact diagnostic executable.

The wheels/registry are controlled test fixtures, not a released or deployed generation.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata as metadata
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from onlyalpha_plugin_operators.provider import quant_asset_provider  # noqa: E402
from onlyalpha_runtime_generation_manager import (  # noqa: E402
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
    OnlyRuntimeGenerationRegistry,
)

from onlyalpha.calculation.definition import (  # noqa: E402
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry  # noqa: E402
from onlyalpha.quant_assets import (  # noqa: E402
    OnlyQuantAssetCatalogGeneration,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.runtime.generation import (  # noqa: E402
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives  # noqa: E402
from tests.support.runtime_distribution_wheels import (  # noqa: E402
    build_wheel,
    installed_distribution_wheel,
    plain_artifact,
)

CHILD = r"""
import hashlib,json,sys,selectors,subprocess
from pathlib import Path
from unittest.mock import patch
from onlyalpha.application.runtime_generation import OnlyRuntimeWorkBindingEvidence
from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha.distribution import OnlyDistributionArtifactManifest
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore,OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager import predicate_comparison as module
payload=json.loads(Path(sys.argv[1]).read_text())
store=OnlyLocalImmutableArtifactStore(Path(sys.argv[2]))
registry=OnlyRuntimeGenerationRegistry(Path(sys.argv[3]))
service=module.OnlyPredicateComparisonService(store,registry)
binding=OnlyRuntimeWorkBindingEvidence(**payload['binding'])
native=OnlyDistributionArtifactManifest.from_dict(payload['native'])
ledger=(registry.root/'generation-events.jsonl').read_bytes()
for case in payload['cases']:
 definition=OnlyCalculationDefinition.from_dict(case['definition'])
 rows=tuple(tuple(row) for row in case['inputs'])
 observed=json.loads(service.observe(binding,definition,rows,native).canonical_json)
 assert observed['status']=='MATCH',observed
 assert observed['python_outputs']==case['expected']
 assert observed['context']['binding']==payload['binding']
 assert observed['context']['native_artifact']==payload['native']
 assert observed['python_implementation'] in {item.implementation_fingerprint for item in registry.require_work_generation(binding.work_id,binding.runtime_generation_fingerprint).implementations}
content=store.fetch_exact(native.artifact_sha256)[1]
frame=('ONLYALPHA_PREDICATE_DIAGNOSTIC_V2\t'+'a'*64+'\n0\tonlyalpha.predicate.internal.boolean.not\t1\ttrue\n').encode()
real_popen=subprocess.Popen
children=[]
def tracked(*args,**kwargs):
 child=real_popen(*args,**kwargs)
 children.append(child)
 return child
with patch.object(module.subprocess,'Popen',tracked),patch.object(module.selectors.DefaultSelector,'select',side_effect=TimeoutError('CONTROLLED_DEADLINE')):
 try: module._run_native(content,frame,native.native_target)
 except TimeoutError: pass
 else: raise AssertionError('deadline was converted to success')
assert len(children)==1 and children[0].returncode is not None
assert children[0].stdin.closed and children[0].stdout.closed
try: module._run_native(content,b'bad\n',native.native_target)
except ValueError as exc: assert 'PROCESS_FAILED' in str(exc)
else: raise AssertionError('failed process was converted to success')
assert (registry.root/'generation-events.jsonl').read_bytes()==ledger
print('SEALED_PYTHON_NATIVE_PREDICATE_COMPARISON: PASS')
"""


def main() -> None:
    executable = Path(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix="onlyalpha-predicate-comparison-") as temporary:
        root = Path(temporary)
        source = root / "source"
        shutil.copytree(
            ROOT,
            source,
            copy_function=shutil.copyfile,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "node_modules",
                "test-results",
                "__pycache__",
                "build",
                "dist",
                ".test-cache",
                ".mypy_cache",
                ".ruff_cache",
            ),
        )
        subprocess.run(
            [sys.executable, str(source / "scripts/embed_build_provenance.py"), "--revision", "1" * 40],
            check=True,
            cwd=source,
        )
        core = build_wheel(source, root / "core-wheel")
        manager = build_wheel(source / "packages/onlyalpha-runtime-generation-manager", root / "manager-wheel")
        operator = build_wheel(source / "plugs/onlyalpha-plugin-operators", root / "operator-wheel")
        arrow = installed_distribution_wheel("pyarrow", root / "arrow-wheel")
        store = OnlyLocalImmutableArtifactStore(root / "artifacts")
        core_manifest = plain_artifact(
            core,
            role=OnlyDistributionArtifactRole.CORE,
            authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
            repository="OnlyAlpha",
            revision="1" * 40,
        )
        identity = OnlyCoreExecutionIdentity(
            core_manifest.distribution_name, core_manifest.distribution_version, core_manifest.artifact_sha256
        )
        provider = quant_asset_provider()
        operator_manifest = only_quant_asset_distribution_artifact_manifest(
            source_repository="OnlyAlpha-plugin-operators",
            source_revision="1" * 40,
            artifact_logical_name=operator.name,
            artifact_bytes=operator.read_bytes(),
            tested_core_execution_fingerprint=identity.fingerprint,
            provider=provider,
        )
        manifests = [core_manifest, operator_manifest]
        store.put_once(core_manifest, core.read_bytes())
        store.put_once(operator_manifest, operator.read_bytes())
        for wheel, authority, repository in [
            (manager, OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT, "OnlyAlpha"),
            (arrow, OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE, "Apache-Arrow"),
        ]:
            manifest = plain_artifact(
                wheel,
                role=OnlyDistributionArtifactRole.SUPPORT,
                authority=authority,
                repository=repository,
                revision="1" * 40,
            )
            store.put_once(manifest, wheel.read_bytes())
            manifests.append(manifest)
        validated = OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build_validated(
            artifacts=tuple(manifests),
            expected_catalog=OnlyQuantAssetCatalogGeneration((provider,)),
            environment_root=root / "hosted",
        )
        registry = OnlyRuntimeGenerationRegistry(root / "registry")
        now = datetime(2026, 10, 17, tzinfo=UTC)
        registry.prepare(validated.manifest, actor="fixture", occurred_at=now)
        registry.admit_ready(validated.validation_evidence, actor="fixture", occurred_at=now)
        generation = validated.manifest.runtime_generation_fingerprint
        registry.activate_for_new_work(expected_current=None, target=generation, actor="human", occurred_at=now)
        registry.bind_new_work_exact(
            "predicate-fixture", generation, owner="DIAGNOSTIC_FIXTURE", actor="fixture", occurred_at=now
        )
        content = executable.read_bytes()
        target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
        version = metadata.version("onlyalpha")
        native = OnlyDistributionArtifactManifest(
            OnlyDistributionArtifactRole.SUPPORT,
            OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
            "OnlyAlpha",
            "1" * 40,
            "onlyalpha-kernel",
            version,
            f"onlyalpha_kernel-{version}-{target}.elf",
            hashlib.sha256(content).hexdigest(),
            len(content),
        )
        store.put_once(native, content)
        calculations = OnlyCalculationRegistry()
        only_register_trading_predicate_primitives(calculations)
        corpus = [
            row
            for name in ("boolean-v1.tsv", "integer-refs-v1.tsv")
            for row in csv.DictReader((ROOT / "test-data/predicate" / name).open(), delimiter="\t")
        ]
        scalars = {"true": True, "false": False, "null": None}
        cases = []
        for type_id in dict.fromkeys(row["type_id"] for row in corpus):
            rows = [row for row in corpus if row["type_id"] == type_id]
            integer = type_id.endswith(".integer.refs")
            names = ("left", "right") if integer or type_id.endswith((".and", ".or")) else ("value",)

            def scalar(token, integer=integer):
                return None if token == "null" else int(token) if integer else scalars[token]

            definition = calculations.rematerialize_definition(
                OnlyCalculationTypeReference(OnlyCalculationKind.PREDICATE, type_id, "1"),
                {},
                {key: OnlyCalculationReference(None, key, "bar.close") for key in names},
            )
            cases.append(
                {
                    "definition": dict(definition.to_dict()),
                    "inputs": [[scalar(row["left"]), scalar(row["right"])][: len(names)] for row in rows],
                    "expected": [scalars[row["expected"]] for row in rows],
                }
            )
        payload = root / "input.json"
        payload.write_text(
            json.dumps(
                {
                    "binding": asdict(registry.require_work_binding_evidence("predicate-fixture")),
                    "native": native.to_dict(),
                    "cases": cases,
                }
            )
        )
        result = subprocess.run(
            [str(root / "hosted/bin/python"), "-I", "-c", CHILD, str(payload), str(store.root), str(registry.root)],
            cwd=root,
            env={"LANG": "C"},
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        print(result.stdout, flush=True)


if __name__ == "__main__":
    main()
