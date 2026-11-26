"""Installed Python SDK and authorized Research worker closure."""

import json
import subprocess
from pathlib import Path


def test_sdk_wheel_release_comes_from_frozen_source(tmp_path, monkeypatch):
    import importlib.metadata
    import zipfile

    from scripts import build_algorithm_sdk as builder

    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    backend = source / "packages/backend/Cargo.toml"
    backend.parent.mkdir(parents=True)
    backend.write_text('[package]\nversion = "0.11.0"\n')
    monkeypatch.setattr(builder, "ROOT", source)
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "0.10.21")
    path = builder.wheel(tmp_path, "onlyalpha-backend-algorithms", {}, ("onlyalpha", "protobuf"))
    with zipfile.ZipFile(path) as archive:
        metadata = archive.read("onlyalpha_backend_algorithms-0.11.0.dist-info/METADATA").decode()
    assert "Version: 0.11.0\n" in metadata
    assert "Requires-Dist: onlyalpha==0.11.0\n" in metadata
    assert "Requires-Dist: protobuf\n" in metadata
    assert "0.10.21" not in metadata


def test_managed_sdk_contains_factor_compiler_without_product_authoring(tmp_path: Path) -> None:
    import zipfile

    from scripts.build_algorithm_sdk import build

    wheels = build(tmp_path)
    assert not any(path.name.startswith("onlyalpha_plugin_indicators-") for path in wheels)
    core = next(path for path in wheels if path.name.startswith("onlyalpha-"))
    with zipfile.ZipFile(core) as archive:
        names = set(archive.namelist())
    with zipfile.ZipFile(
        next(path for path in wheels if path.name.startswith("onlyalpha_backend_algorithms-"))
    ) as archive:
        worker_names = set(archive.namelist())
    assert "onlyalpha_backend_algorithms/factor_build.py" in worker_names
    assert "onlyalpha/algorithm/factor_program.py" in names
    assert "onlyalpha_backend_algorithms/research_resolution.py" in worker_names
    assert "onlyalpha_backend_algorithms/sdk/private_factor_source.py" in worker_names
    assert "onlyalpha/quant_assets/private_factor_provider_snapshot.py" in names
    assert "onlyalpha/calculation/registry.py" in names
    assert not any(
        name.startswith(("onlyalpha/application/", "onlyalpha/research/", "onlyalpha/persistence/")) for name in names
    )
    assert {name for name in names if name.startswith("onlyalpha/quant_assets/")} == {
        "onlyalpha/quant_assets/__init__.py",
        "onlyalpha/quant_assets/private_factor_provider_snapshot.py",
    }
    assert not any(path.name.startswith("onlyalpha_plugin_operators-") for path in wheels)
    assert "onlyalpha_backend_algorithms/research_session.py" in worker_names
    assert any(path.name.startswith("onlyalpha_backend_algorithms-") for path in wheels)


def test_installed_research_core_verifies_exact_resources_and_size(tmp_path: Path) -> None:
    import hashlib

    from scripts.build_algorithm_sdk import install

    installation = tmp_path / "installed"
    install(tmp_path / "wheels", installation)
    core = next((tmp_path / "wheels").glob("onlyalpha-*.whl"))
    request = {
        "core_artifact": {
            "path": str(core),
            "sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
            "size": core.stat().st_size,
            "distribution_version": core.name.split("-")[1],
        }
    }
    code = r"""
import copy,json,sys
p=json.loads(sys.stdin.read())
# A small compressed wheel with excessive uncompressed metadata must fail
# before expansion. It retains the real matching SDK resources.
import hashlib,zipfile
from pathlib import Path
from onlyalpha_backend_algorithms.research_worker import verify_core,MAX_FRAME
original=verify_core(p['core_artifact'])
assert original['core_artifact_sha256']==p['core_artifact']['sha256']
assert len(original['core_resources_fingerprint'])==64
bad_identity={**p['core_artifact'], 'sha256':'f'*64}
try:verify_core(bad_identity)
except ValueError as error:assert str(error)=='RESEARCH_CORE_ARTIFACT_INVALID'
else:raise AssertionError('foreign Core SHA-256 accepted')
allowed_dto = {'onlyalpha.quant_assets', 'onlyalpha.quant_assets.private_factor_provider_snapshot'}
assert not any(k.startswith(('onlyalpha.quant_assets','onlyalpha.application','onlyalpha.runtime','onlyalpha.persistence','onlyalpha.research')) and k not in allowed_dto for k in sys.modules)
for change in ('namespace','semantic-dto'):
 alternate=Path(p['core_artifact']['path']).with_name(change+'-core.whl')
 with zipfile.ZipFile(p['core_artifact']['path']) as source, zipfile.ZipFile(alternate,'w') as output:
  for info in source.infolist():
   data=source.read(info)
   if change=='namespace' and info.filename=='onlyalpha/quant_assets/__init__.py':data=b'# Full Core namespace differs from the installed mathematical bootstrap.\n'
   if change=='semantic-dto' and info.filename=='onlyalpha/quant_assets/private_factor_provider_snapshot.py':data+=b'\n# changed semantic SDK bytes\n'
   output.writestr(info.filename,data)
 q=copy.deepcopy(p['core_artifact']);q.update(path=str(alternate),sha256=hashlib.sha256(alternate.read_bytes()).hexdigest(),size=alternate.stat().st_size)
 if change=='namespace':
  assert verify_core(q)['core_resources_fingerprint']==original['core_resources_fingerprint']
 else:
  try:verify_core(q)
  except ValueError as error:assert str(error)=='RESEARCH_CORE_SDK_MISMATCH'
  else:raise AssertionError('semantic SDK resource substitution accepted')
bad=Path(p['core_artifact']['path']).with_name('oversized-core.whl')
with zipfile.ZipFile(p['core_artifact']['path']) as source, zipfile.ZipFile(bad,'w',compression=zipfile.ZIP_DEFLATED) as output:
 for info in source.infolist():
  data=source.read(info)
  if info.filename.endswith('/METADATA'):data+=b'X'*(MAX_FRAME+1)
  output.writestr(info.filename,data)
q=copy.deepcopy(p['core_artifact']);q.update(path=str(bad),sha256=hashlib.sha256(bad.read_bytes()).hexdigest(),size=bad.stat().st_size)
try:verify_core(q)
except ValueError:pass
else:raise AssertionError('unbounded Core METADATA')
print(json.dumps(original))
"""
    result = subprocess.run(
        [str(installation / "bin/python"), "-B", "-I", "-c", code],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        env={},
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["core_artifact_sha256"] == request["core_artifact"]["sha256"]
