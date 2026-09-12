from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


def _isolated_runtime_proof() -> str:
    return textwrap.dedent(
        """
        import importlib.metadata
        import json
        import os
        import selectors
        import shutil
        import signal
        import subprocess
        import sys
        import urllib.request
        from pathlib import Path
        from types import SimpleNamespace

        import onlyalpha
        import onlyalpha_agent_orchestrator.runtime as runtime
        from onlyalpha.build_provenance import only_packaged_build_provenance
        from onlyalpha.research.agent import (
            OnlyAgentContextError,
            OnlyAgentOrchestrationResourceKind,
            OnlyAgentOrchestrationResourceV1,
            OnlyAgentWorkflowImplementationManifestV1,
        )
        from onlyalpha_agent_orchestrator.provenance import (
            only_agent_orchestrator_packaged_build_provenance,
        )

        repository_root = Path(sys.argv[1]).resolve()
        environment_root = Path(sys.prefix).resolve()
        working_directory = Path.cwd().resolve()
        assert not working_directory.is_relative_to(repository_root)
        assert not any((candidate / ".git").exists() for candidate in (working_directory, *working_directory.parents))
        assert shutil.which("git") is None
        assert all(
            not Path(entry).resolve().is_relative_to(repository_root)
            for entry in sys.path
            if entry
        )

        first = runtime.build_current_agent_workflow_implementation_manifest()
        second = runtime.build_current_agent_workflow_implementation_manifest()
        assert first == second
        assert first.implementation_fingerprint == second.implementation_fingerprint
        assert first.workflow_id == runtime.ONLY_AGENT_WORKFLOW_ID == "ONLYALPHA_AGENT_V1"
        assert first.workflow_semantic_version == runtime.ONLY_AGENT_WORKFLOW_SEMANTIC_VERSION
        assert first.ordered_executable_resources

        resource_identities = tuple(item.logical_resource_identity for item in first.ordered_executable_resources)
        assert resource_identities == tuple(sorted(resource_identities))
        assert len(resource_identities) == len(set(resource_identities))

        core_provenance = only_packaged_build_provenance()
        orchestrator_provenance = only_agent_orchestrator_packaged_build_provenance()
        assert core_provenance.distribution_name == "onlyalpha"
        assert orchestrator_provenance.distribution_name == "onlyalpha-agent-orchestrator"
        assert core_provenance.distribution_version == importlib.metadata.version("onlyalpha")
        assert orchestrator_provenance.distribution_version == importlib.metadata.version(
            "onlyalpha-agent-orchestrator"
        )
        assert core_provenance.source_revision == orchestrator_provenance.source_revision == first.source_revision
        assert tuple(item.distribution_name for item in first.distribution_provenance) == (
            "onlyalpha",
            "onlyalpha-agent-orchestrator",
        )

        installed_module_paths = []
        for module_name, module in tuple(sys.modules.items()):
            if module_name != "onlyalpha" and not module_name.startswith(("onlyalpha.", "onlyalpha_agent_orchestrator")):
                continue
            module_file = getattr(module, "__file__", None)
            if module_file is None:
                continue
            module_path = Path(module_file).resolve()
            installed_module_paths.append(module_path)
            assert module_path.is_relative_to(environment_root)
            assert "site-packages" in module_path.parts
            assert not module_path.is_relative_to(repository_root)
        assert Path(onlyalpha.__file__).resolve() in installed_module_paths
        assert Path(runtime.__file__).resolve() in installed_module_paths

        contract_path = Path(sys.argv[2]).resolve()
        node_root = working_directory / "node-state"
        lock_root = working_directory / "node-locks"
        secret_paths = []
        for name in ("product", "model", "control"):
            path = working_directory / f"{name}.secret"
            path.write_text(f"{name}-secret\\n", encoding="utf-8")
            secret_paths.append(path)
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-m",
                "onlyalpha_agent_orchestrator.node_main",
                "serve",
                "--durable-root",
                str(node_root),
                "--coordination-root",
                str(lock_root),
                "--product-api-url",
                "http://127.0.0.1:9",
                "--product-api-contract",
                str(contract_path),
                "--product-token-file",
                str(secret_paths[0]),
                "--model-api-url",
                "http://127.0.0.1:9",
                "--model-token-file",
                str(secret_paths[1]),
                "--control-token-file",
                str(secret_paths[2]),
                "--host",
                "127.0.0.1",
                "--port",
                "18019",
            ],
            cwd=working_directory,
            env=dict(os.environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        selector = selectors.DefaultSelector()
        assert process.stderr is not None
        selector.register(process.stderr, selectors.EVENT_READ)
        startup_lines = []
        while "Application startup complete." not in "".join(startup_lines):
            events = selector.select(timeout=30)
            assert events, "Agent node startup barrier timed out"
            line = process.stderr.readline()
            startup_lines.append(line)
            assert process.poll() is None, "Agent node exited during startup: " + "".join(startup_lines)
        with urllib.request.urlopen("http://127.0.0.1:18019/internal/v1/healthz", timeout=5) as response:
            response_status = response.status
            response_payload = json.loads(response.read())
            assert response_status == 200, (response_status, response_payload, startup_lines)
            assert response_payload == {"status": "ALIVE"}, (
                response_payload,
                startup_lines,
            )
        process.send_signal(signal.SIGTERM)
        remaining_stdout, remaining_stderr = process.communicate(timeout=10)
        shutdown_output = "".join(startup_lines) + remaining_stderr
        assert "Application shutdown complete." in shutdown_output, shutdown_output
        assert "Finished server process" in shutdown_output, shutdown_output
        assert process.returncode in (0, -signal.SIGTERM), (
            process.returncode,
            startup_lines,
            remaining_stdout,
            remaining_stderr,
        )

        session_fingerprint = "1" * 64
        historical = OnlyAgentOrchestrationResourceV1(
            OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
            1,
            "1.0.0",
            first,
        )

        class SessionReader:
            def __init__(self, workflow_resource):
                self.context = SimpleNamespace(
                    session=SimpleNamespace(session_fingerprint=session_fingerprint),
                    workflow_resource=workflow_resource,
                )

            def load_session_manifest_verified(self, requested_fingerprint):
                assert requested_fingerprint == session_fingerprint
                return self.context

        original_mint = runtime._mint_runtime_execution_permit
        minted = 0
        continued = 0

        def counted_mint(*args, **kwargs):
            global minted
            minted += 1
            return original_mint(*args, **kwargs)

        def continuation(permit):
            global continued
            continued += 1
            runtime.assert_runtime_execution_permit(
                permit,
                agent_session_fingerprint=session_fingerprint,
                historical_workflow_resource_fingerprint=historical.resource_fingerprint,
                workflow_implementation_fingerprint=first.implementation_fingerprint,
                source_revision=first.source_revision,
            )
            return permit

        runtime._mint_runtime_execution_permit = counted_mint
        permit = runtime.execute_after_runtime_admission(
            session_fingerprint,
            SessionReader(historical),
            continuation,
        )
        assert type(permit) is runtime.OnlyAgentRuntimeExecutionPermit
        assert minted == 1
        assert continued == 1

        mismatched_manifest = OnlyAgentWorkflowImplementationManifestV1(
            first.workflow_id,
            "1.0.1",
            first.source_revision,
            first.ordered_executable_resources,
            first.distribution_provenance,
        )
        mismatched_historical = OnlyAgentOrchestrationResourceV1(
            OnlyAgentOrchestrationResourceKind.AGENT_WORKFLOW_IMPLEMENTATION_MANIFEST,
            1,
            "1.0.0",
            mismatched_manifest,
        )
        minted = 0
        continued = 0
        try:
            runtime.execute_after_runtime_admission(
                session_fingerprint,
                SessionReader(mismatched_historical),
                continuation,
            )
        except OnlyAgentContextError as exc:
            assert exc.code == "AGENT_WORKFLOW_RUNTIME_MISMATCH"
        else:
            raise AssertionError("historical/current workflow mismatch was admitted")
        assert minted == 0
        assert continued == 0

        print(
            json.dumps(
                {
                    "admission_success": True,
                    "core_wheel_version": core_provenance.distribution_version,
                    "dual_provenance": True,
                    "manifest_deterministic": True,
                    "mismatch_fail_closed": True,
                    "orchestrator_wheel_version": orchestrator_provenance.distribution_version,
                    "source_revision": first.source_revision,
                    "source_tree_isolated": True,
                },
                sort_keys=True,
            )
        )
        """
    )


def test_built_wheels_admit_only_the_exact_installed_agent_runtime(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    execution_directory = tmp_path / "execution"
    execution_directory.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        }
    )

    for package in ("onlyalpha", "onlyalpha-agent-orchestrator"):
        _run(
            [
                uv,
                "build",
                "--offline",
                "--no-build-isolation",
                "--wheel",
                "--package",
                package,
                "--out-dir",
                str(artifacts),
            ],
            cwd=ROOT,
            env=environment,
        )

    onlyalpha_wheel = next(artifacts.glob("onlyalpha-[0-9]*.whl"))
    orchestrator_wheel = next(artifacts.glob("onlyalpha_agent_orchestrator-*.whl"))
    locked_packages = {
        package["name"]: package["version"]
        for package in tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]
    }
    dependency_constraints = tmp_path / "runtime-dependency-constraints.txt"
    dependency_constraints.write_text(
        "".join(
            f"{name}=={locked_packages[name]}\n"
            for name in (
                "annotated-types",
                "annotated-doc",
                "anyio",
                "click",
                "fastapi",
                "h11",
                "idna",
                "pydantic",
                "pydantic-core",
                "psycopg",
                "psycopg-binary",
                "pyarrow",
                "pyyaml",
                "starlette",
                "typing-extensions",
                "typing-inspection",
                "tzdata",
                "uvicorn",
            )
        ),
        encoding="utf-8",
    )
    isolated_environment = tmp_path / "isolated-environment"
    _run(
        [uv, "venv", "--offline", "--no-project", "--python", sys.executable, str(isolated_environment)],
        cwd=execution_directory,
        env=environment,
    )
    isolated_python = isolated_environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--no-build",
            "--strict",
            "--constraint",
            str(dependency_constraints),
            "--python",
            str(isolated_python),
            str(onlyalpha_wheel),
            str(orchestrator_wheel),
        ],
        cwd=execution_directory,
        env=environment,
    )

    runtime_environment = dict(environment)
    runtime_environment.update({"PATH": "", "PWD": str(execution_directory)})
    contract_copy = execution_directory / "product-openapi.json"
    shutil.copyfile(ROOT / "contracts/product-api/v2/openapi.json", contract_copy)
    completed = _run(
        [str(isolated_python), "-I", "-c", _isolated_runtime_proof(), str(ROOT), str(contract_copy)],
        cwd=execution_directory,
        env=runtime_environment,
    )
    proof = completed.stdout.strip().splitlines()[-1]
    assert '"admission_success": true' in proof
    assert '"mismatch_fail_closed": true' in proof
    assert '"source_tree_isolated": true' in proof
