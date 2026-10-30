"""Pure installed chart algorithm closure, never Product/Runtime authority."""

import json
import signal
import subprocess
import sys
from pathlib import Path


def test_chart_factory_is_pure_and_current_fourteen_families() -> None:
    code = """
import json, sys
from onlyalpha_plugin_indicators.chart_factory import ChartFactory
factory = ChartFactory()
rows = factory.catalog()
assert len(rows) == 14
assert len({r["descriptor"]["type_id"] for r in rows}) == 14
assert not any(k.startswith(("onlyalpha.application", "onlyalpha.runtime", "onlyalpha.persistence", "onlyalpha.research", "onlyalpha.strategy", "onlyalpha.broker")) for k in sys.modules)
assert all(r["implementation_fingerprint"] for r in rows)
print(json.dumps([r["descriptor"]["type_id"] for r in rows]))
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)) == 14


def test_current_installed_minimal_algorithm_and_kernel_restrictions(tmp_path: Path) -> None:
    from scripts.build_algorithm_sdk import install

    installation = tmp_path / "installed"
    artifact = install(tmp_path / "wheels", installation)
    interpreter = installation / "bin/python"
    import ast
    import hashlib

    recorded = json.loads((installation / "algorithm-installation.json").read_text())
    ast_path = Path(ast.__file__).resolve()
    assert recorded["runtime_files"][str(ast_path)] == hashlib.sha256(ast_path.read_bytes()).hexdigest()

    # Execute the actual Shipping CI smoke body against this installed closure.
    # This catches stale CI imports/metadata consumers without mocking the package.
    import shlex

    import yaml

    from scripts.build_algorithm_sdk import ROOT

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    step = next(
        row
        for row in workflow["jobs"]["build-smoke"]["steps"]
        if row.get("name") == "Check the installed algorithm boundary"
    )
    smoke = shlex.split(step["run"])[-1]
    subprocess.run(
        [str(interpreter), "-B", "-I", "-c", smoke],
        env={
            "EXPECTED_VERSION": json.loads((installation / "algorithm-installation.json").read_text())[
                "distribution_version"
            ]
        },
        check=True,
    )
    code = r"""
import errno, importlib, json, os, resource, socket, subprocess, sys
from decimal import Decimal, ROUND_DOWN, getcontext
from onlyalpha_plugin_indicators.chart_factory import ChartFactory
from onlyalpha_backend_algorithms.chart_worker import verify_installation
from pathlib import Path
verify_installation(Path(sys.argv[1]), sys.argv[2])
import importlib.metadata, importlib.util
assert importlib.util.find_spec("onlyalpha_calculation_worker") is None
assert importlib.metadata.version("onlyalpha-backend-algorithms") == json.loads((Path(sys.argv[1])/"algorithm-installation.json").read_text())["distribution_version"]
f = ChartFactory()
expected = {
 'ema': ('value', '10'), 'sma': ('value','10'), 'bollinger': ('middle','10'),
 'rolling_return': ('value','0'), 'rolling_volatility': ('value','0'), 'zscore': ('value','0'),
 'wma': ('value','10'), 'roc': ('roc','0'), 'obv': ('obv','0'),
 'rsi': ('value','50'), 'atr': ('atr','4'), 'macd': ('histogram','0'),
 'vwap': ('vwap','10'), 'stochastic': ('k','50'),
}
for row in f.catalog():
 d=row['descriptor']; name=d['type_id'].rsplit('.',1)[-1]
 p=row['support']['default_parameters']
 definition=f.resolve(d['type_id'],d['semantic_version'],p)
 inputs={port.name: ([i*60_000_000_000 for i in range(80)] if port.name=='start_ns' else ['12' if port.name=='high' else '8' if port.name=='low' else '2' if port.name=='volume' else '10']*80) for port in definition.inputs}
 getcontext().prec=4; getcontext().rounding=ROUND_DOWN
 result=f.execute(d['type_id'],d['semantic_version'],p,inputs,row['implementation_fingerprint'])
 output,value=expected[name]
 assert Decimal(result['outputs'][output]['values'][-1])==Decimal(value), (name,result['outputs'])
 assert result['outputs'][output]['states'][-1]=='READY'
 assert result['outputs'][output]['reasons'][-1]=='NONE'
 assert set(result['outputs'])=={port.name for port in definition.outputs}
 # Missing exact versions cannot silently run the family's preferred algorithm.
 if name in {'rsi','atr','macd','vwap','stochastic'}:
  try: f.resolve(d['type_id'],'not-installed',{})
  except KeyError: pass
  else: raise AssertionError('latest substitution')
# Independent non-constant vectors exercise normalization, seed/warmup and
# undefined/missing distinctions through the same current installed factory.
def run(name, parameters, columns):
 row=next(row for row in f.catalog() if row['descriptor']['type_id'].endswith('.'+name))
 d=row['descriptor']
 return f.execute(d['type_id'],d['semantic_version'],parameters,columns,row['implementation_fingerprint'])
def values(result, output):
 return [None if v is None else Decimal(v) for v in result['outputs'][output]['values']]
assert values(run('sma',{'period':3},{'value':['1','2','3','6']}),'value')==[Decimal('1'),Decimal('1.5'),Decimal('2'),Decimal('3.666666666667')]
assert values(run('ema',{'period':3},{'value':['1','2','3','6']}),'value')==[Decimal('1'),Decimal('1.5'),Decimal('2.25'),Decimal('4.125')]
b=run('bollinger',{'period':2,'standard_deviations':'2'},{'value':['1','2','3']})
assert values(b,'upper')==[Decimal('1'),Decimal('2.5'),Decimal('3.5')]
assert values(b,'lower')==[Decimal('1'),Decimal('0.5'),Decimal('1.5')]
assert values(run('rolling_return',{'period':2},{'value':['1','2','4','8']}),'value')==[None,None,Decimal('3'),Decimal('3')]
assert values(run('rolling_volatility',{'period':2},{'value':['1','3','7']}),'value')==[Decimal('0'),Decimal('1'),Decimal('2')]
assert values(run('zscore',{'period':2},{'value':['1','3','1']}),'value')==[Decimal('0'),Decimal('1'),Decimal('-1')]
w=run('wma',{'period':2},{'price':[None,'2','4','6']})
assert values(w,'value')==[None,None,Decimal('3.333333333333'),Decimal('5.333333333333')]
assert w['outputs']['value']['states']==['UNAVAILABLE','UNAVAILABLE','READY','READY']
assert w['outputs']['value']['reasons']==['INPUT_UNAVAILABLE','INPUT_UNAVAILABLE','NONE','NONE']
assert values(run('roc',{'period':2},{'price':['1','2','4','8']}),'roc')==[None,None,Decimal('3'),Decimal('3')]
assert values(run('obv',{}, {'close':['10','12','11','11','13'],'volume':['1','2','3','4','5']}),'obv')==[Decimal('0'),Decimal('2'),Decimal('-1'),Decimal('-1'),Decimal('4')]
r=run('rsi',{'period':3},{'value':['1','2','4','3','2','5']})
assert values(r,'value')==[None,None,None,Decimal('75'),Decimal('54.545454545455'),Decimal('79.591836734694')]
assert r['outputs']['value']['states']==['PARTIAL']*3+['READY']*3
assert values(run('atr',{'period':3},{'high':['11','13','15','14'],'low':['9','10','12','10'],'close':['10','12','14','11']}),'atr')==[None,None,Decimal('2.666666666667'),Decimal('3.111111111111')]
m=run('macd',{'fast_period':1,'slow_period':3,'signal_period':1},{'value':['1','3','5']})
assert values(m,'dif')==[Decimal('0'),Decimal('1'),Decimal('1.5')]
assert values(m,'dea')==values(m,'dif')
assert values(m,'histogram')==[Decimal('0')]*3
st=run('stochastic',{'k_period':2,'smooth_k':2,'d_period':2},{'high':['10']*5,'low':['0']*5,'close':['1','2','4','8','6']})
assert values(st,'k')==[None,None,Decimal('30'),Decimal('60'),Decimal('70')]
assert values(st,'d')==[None,None,None,Decimal('45'),Decimal('65')]
assert st['outputs']['k']['states']==['PARTIAL','PARTIAL','READY','READY','READY']
u=run('stochastic',{'k_period':1,'smooth_k':1,'d_period':1},{'high':['0'],'low':['0'],'close':['0']})
assert u['outputs']['k']['states']==['READY'] and u['outputs']['k']['reasons']==['VALUE_UNDEFINED']
day=86_400_000_000_000
v=run('vwap',{}, {'start_ns':[day-2,day-1,day,day+1],'high':['12','24','36','48'],'low':['9','18','27','36'],'close':['9','18','27','36'],'volume':['1','3','0','2']})
assert values(v,'vwap')==[Decimal('10'),Decimal('17.5'),None,Decimal('40')]
assert v['outputs']['vwap']['reasons']==['NONE','NONE','VALUE_UNDEFINED','NONE']
from onlyalpha_plugin_indicators.chart import require_chart_capacity
wma=next(row for row in f.catalog() if row['descriptor']['type_id'].endswith('.wma'))
d=f.resolve(wma['descriptor']['type_id'],'1',{'period':10000})
require_chart_capacity(d,500)
try:require_chart_capacity(d,501)
except ValueError as e:assert str(e)=='CHART_STUDY_CAPACITY_EXCEEDED'
else:raise AssertionError('work budget')
for parameters in ({'period':0},{'period':True},{'period':10001},{'period':2,'unknown':1},{'period':2,'price_field':'VOLUME'}):
 try:f.resolve('onlyalpha.indicator.sma','1',parameters)
 except (ValueError,TypeError):pass
 else:raise AssertionError(('invalid normalization',parameters))
from onlyalpha.algorithm.private_factor import _SourcePolicy, _PrivateFactorAstInterpreter, ONLY_PRIVATE_FACTOR_NUMERIC_V1
from onlyalpha.calculation.value_semantics import OnlyCanonicalValueSemanticsV1
import ast
program=ast.parse("def calculate(api, inputs, parameters):\n return {'value':api.sub(inputs['close'],parameters['offset'])}\n")
_SourcePolicy().visit(program)
assert _PrivateFactorAstInterpreter(program.body[0],OnlyCanonicalValueSemanticsV1(ONLY_PRIVATE_FACTOR_NUMERIC_V1),{'close':Decimal('5.125')},{'offset':Decimal('2')}).run()=={'value':Decimal('3.125')}
try:_SourcePolicy().visit(ast.parse('import os'))
except ValueError:pass
else:raise AssertionError('private Factor import')
for module in ('onlyalpha.application','onlyalpha.runtime','onlyalpha.persistence','onlyalpha.broker','onlyalpha.research','onlyalpha.strategy'):
 try: importlib.import_module(module)
 except ModuleNotFoundError: pass
 else: raise AssertionError(module)
assert not any('.pth' in x for x in sys.path)
from onlyalpha_backend_algorithms.chart_isolation import restrict
assert restrict()=='LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1'
for operation in (lambda:open('/etc/passwd'), lambda:socket.socket(), lambda:subprocess.Popen(['/bin/true']), lambda:os.mkdir('/tmp/chart-forbidden')):
 try: operation()
 except OSError as error: assert error.errno==errno.EPERM, str(error)
 else: raise AssertionError('sandbox escape')
assert resource.getrlimit(resource.RLIMIT_CPU)==(10,10)
assert resource.getrlimit(resource.RLIMIT_AS)==(2*1024**3,2*1024**3)
try:bytearray(3*1024**3)
except MemoryError:pass
else:raise AssertionError('memory limit')
# Actual mathematics remains usable after the OS boundary closes external access.
assert values(run('sma',{'period':2},{'value':['2','4']}),'value')==[Decimal('2'),Decimal('3')]
print(json.dumps({'families':len(expected),'isolation':'enforced'}))
"""
    result = subprocess.run(
        [str(interpreter), "-B", "-I", "-c", code, str(installation), artifact],
        capture_output=True,
        text=True,
        check=False,
        env={},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"families": 14, "isolation": "enforced"}

    cpu = subprocess.run(
        [
            str(interpreter),
            "-B",
            "-I",
            "-c",
            "from onlyalpha_backend_algorithms.chart_isolation import restrict\nrestrict()\nwhile True: pass\n",
        ],
        capture_output=True,
        env={},
        timeout=20,
    )
    assert cpu.returncode == -signal.SIGKILL, cpu.stderr


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


def test_algorithm_plugin_wheel_keeps_its_own_version(tmp_path, monkeypatch):
    import zipfile

    from scripts import build_algorithm_sdk as builder

    source = tmp_path / "source"
    backend = source / "packages/backend/Cargo.toml"
    backend.parent.mkdir(parents=True)
    backend.write_text('[package]\nversion = "0.7.0"\n')
    plugin = source / "plugs/onlyalpha-plugin-indicators/pyproject.toml"
    plugin.parent.mkdir(parents=True)
    plugin.write_text('[project]\nversion = "0.2.0"\n')
    monkeypatch.setattr(builder, "ROOT", source)
    path = builder.wheel(tmp_path, "onlyalpha-plugin-indicators", {}, ("onlyalpha",))
    with zipfile.ZipFile(path) as archive:
        metadata = archive.read("onlyalpha_plugin_indicators-0.2.0.dist-info/METADATA").decode()
    assert "Version: 0.2.0\n" in metadata
    assert "Requires-Dist: onlyalpha==0.7.0\n" in metadata


def test_managed_sdk_contains_source_execution_without_product_authoring(tmp_path: Path) -> None:
    import zipfile

    from scripts.build_algorithm_sdk import build

    wheels = build(tmp_path)
    core = next(path for path in wheels if path.name.startswith("onlyalpha-"))
    with zipfile.ZipFile(core) as archive:
        names = set(archive.namelist())
    with zipfile.ZipFile(
        next(path for path in wheels if path.name.startswith("onlyalpha_backend_algorithms-"))
    ) as archive:
        worker_names = set(archive.namelist())
    assert "onlyalpha_backend_algorithms/sdk/private_factor_execution.py" in worker_names
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
    assert any(path.name.startswith("onlyalpha_plugin_operators-") for path in wheels)


def test_installed_research_source_resolution_is_not_execution(tmp_path: Path) -> None:
    from scripts.build_algorithm_sdk import ROOT, install

    installation = tmp_path / "installed"
    artifact = install(tmp_path / "wheels", installation)
    vector = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    names = (
        "factor_id",
        "semantic_version",
        "revision_fingerprint",
        "source_text",
        "source_sha256",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "input_contract",
        "parameter_contract",
        "output_contract",
    )
    import hashlib

    core = next((tmp_path / "wheels").glob("onlyalpha-*.whl"))
    request = {
        "schema_version": 1,
        "source": {name: vector["revision"][name] for name in names},
        "graph": vector["graph"],
        "core_artifact": {
            "path": str(core),
            "sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
            "size": core.stat().st_size,
            "distribution_version": vector["revision"]["semantic_version"],
        },
    }
    request["core_artifact"]["distribution_version"] = json.loads(
        (installation / "algorithm-installation.json").read_text()
    )["distribution_version"]
    code = r"""
import copy,json,sys
from onlyalpha_backend_algorithms.research_worker import resolve
from onlyalpha.calculation.implementation import OnlyCalculationImplementationManifest
p=json.loads(sys.stdin.read())
r=resolve(p,sys.argv[1])
assert r['graph']==p['graph']
assert r['core_artifact_sha256']==p['core_artifact']['sha256']
assert r['factor_revision_fingerprint']==p['source']['revision_fingerprint']
assert len(r['implementations'])==6
for m in r['implementations']:
 assert OnlyCalculationImplementationManifest.from_dict(m).to_dict()==m
assert 'equivalence_evidence' not in r and 'runtime_generation_fingerprint' not in r
allowed_dto = {'onlyalpha.quant_assets', 'onlyalpha.quant_assets.private_factor_provider_snapshot'}
assert not any(k.startswith(('onlyalpha.quant_assets','onlyalpha.application','onlyalpha.runtime','onlyalpha.persistence','onlyalpha.research')) and k not in allowed_dto for k in sys.modules)
for mode in ('source','definition','version','core'):
 q=copy.deepcopy(p)
 if mode=='source':q['source']['source_text']+='\n'
 elif mode=='definition':q['graph']['nodes'][0]['definition']['warmup']['minimum_observations']+=1
 elif mode=='version':q['graph']['nodes'][0]['definition']['semantic_version']='missing'
 else:q['core_artifact']['sha256']='f'*64
 try:resolve(q,sys.argv[1])
 except (ValueError,TypeError):pass
 else:raise AssertionError(mode)
# A small compressed wheel with excessive uncompressed metadata must fail
# before expansion. It retains the real matching SDK resources.
import hashlib,zipfile
from pathlib import Path
from onlyalpha_backend_algorithms.research_worker import verify_core,MAX_FRAME
original=verify_core(p['core_artifact'])
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
print(json.dumps(r))
"""
    result = subprocess.run(
        [str(installation / "bin/python"), "-B", "-I", "-c", code, artifact],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        env={},
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["algorithm_artifact"] == artifact
