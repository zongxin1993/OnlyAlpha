"""Actual private Factor TRADING SPI; graph/window authority remains in Rust."""

import json
import subprocess
from pathlib import Path


def test_installed_trading_session_preserves_actual_math_and_atomic_checkpoint(tmp_path: Path) -> None:
    from onlyalpha.calculation.definition import OnlyCalculationReference
    from onlyalpha_backend_algorithms.sdk import private_factor_execution as execution
    from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

    from scripts.build_algorithm_sdk import ROOT, install

    installation = tmp_path / "installed"
    install(tmp_path / "wheels", installation)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    source = {key: fixture["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__}
    record = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(source)
    definition = execution.OnlyPrivateFactorDefinitionResolverV1(
        execution.only_private_factor_type_definition(record)
    ).resolve({}, {name: OnlyCalculationReference(None, "value", name) for name in record.input_contract})
    request = {"source": source, "nodes": {"factor": dict(definition.to_dict())}}
    code = r"""
import copy, json, sys
from decimal import Decimal, ROUND_DOWN, getcontext
from onlyalpha_backend_algorithms.chart_isolation import restrict
from onlyalpha_backend_algorithms.trading_session import TradingGraphSession
p=json.loads(sys.stdin.read())
assert restrict() == 'LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1'
getcontext().prec=4
getcontext().rounding=ROUND_DOWN
s=TradingGraphSession([p['source']], p['nodes'])

def rejected(call):
    try: call()
    except (ValueError, TypeError, ArithmeticError): pass
    else: raise AssertionError('invalid numerical request accepted')

def operands(close='120', lag='100', volume='21', mean='2'):
    return {'close':Decimal(close),'close_lag_20':Decimal(lag),'volume':Decimal(volume),'volume_mean_20':Decimal(mean)}

saved=s.checkpoint()
assert set(saved)=={'schema_version', 'nodes'} and saved['schema_version']==1
assert set(saved['nodes'])=={'factor'}
assert saved['nodes']['factor']['state_capability']=='STATELESS'
assert saved['nodes']['factor']['checkpoint_schema_version'] is None
assert saved['nodes']['factor']['state'] is None
assert s.update('factor', operands())=={'value':Decimal('2.1')}
# The private SPI has no rolling state or execution cursor. A fresh factory
# consumes the exact same immutable definition/checkpoint and declared operands.
r=TradingGraphSession([p['source']], p['nodes'])
r.restore(saved)
assert r.checkpoint()==saved
assert r.update('factor', operands())=={'value':Decimal('2.1')}
assert r.update('factor', operands('121','101','1','2'))=={'value':Decimal('0.099009900990')}
assert r.update('factor', operands(volume='0',mean='0'))=={'value':None}
assert r.checkpoint()==saved
copy_saved=copy.deepcopy(saved)
copy_saved['nodes']['factor']['definition']['parameters']['literal_1']['value']='999'
assert r.checkpoint()==saved and s.checkpoint()==saved
before=r.checkpoint()
for invalid in (1.0, True, '1', Decimal('NaN'), Decimal('Infinity'), {'type':'DECIMAL','value':'1'}):
    bad=operands();bad['close']=invalid
    rejected(lambda bad=bad: r.update('factor',bad))
rejected(lambda: r.update('missing', operands()))
rejected(lambda: r.update('factor', {**operands(),'extra':Decimal(1)}))
rejected(lambda: r.update('factor', {}))
assert r.checkpoint()==before
for kind in ('definition','implementation','schema','missing','extra','null-stateless','control','boolean-schema'):
    bad=copy.deepcopy(saved)
    if kind=='definition': bad['nodes']['factor']['definition']['warmup']['minimum_observations']+=1
    elif kind=='implementation': bad['nodes']['factor']['implementation_fingerprint']='f'*64
    elif kind=='schema': bad['nodes']['factor']['checkpoint_schema_version']=1
    elif kind=='missing': del bad['nodes']['factor']
    elif kind=='extra': bad['nodes']['unknown']=bad['nodes']['factor']
    elif kind=='null-stateless': bad['nodes']['factor']['state']={}
    elif kind=='boolean-schema': bad['schema_version']=True
    else: bad['runtime_generation']='opaque-authority-forgery'
    rejected(lambda bad=bad: r.restore(bad))
    assert r.checkpoint()==before
for kind in ('definition','unknown-version','predicate','budget'):
    bad=copy.deepcopy(p['nodes'])
    if kind=='definition': bad['factor']['warmup']['minimum_observations']+=1
    elif kind=='unknown-version': bad['factor']['semantic_version']='uninstalled'
    elif kind=='predicate': bad['factor']['kind']='PREDICATE'
    else: bad={str(index):bad['factor'] for index in range(129)}
    rejected(lambda bad=bad: TradingGraphSession([p['source']],bad))
rejected(lambda: TradingGraphSession([p['source']], {'\n':p['nodes']['factor']}))
rejected(lambda: TradingGraphSession([p['source']]*129,p['nodes']))
assert not any(name.startswith(('onlyalpha.application','onlyalpha.runtime','onlyalpha.strategy','onlyalpha.persistence','onlyalpha.execution','onlyalpha.account','onlyalpha.risk','onlyalpha.broker')) for name in sys.modules)
assert not any(key in saved for key in ('cursor','receipt','grant','runtime_generation','authority'))
assert not any(name.startswith('onlyalpha_plugin_operators') for name in sys.modules)
print('actual private Factor trading/checkpoint PASS')
"""
    result = subprocess.run(
        [str(installation / "bin/python"), "-B", "-I", "-c", code],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        env={},
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "actual private Factor trading/checkpoint PASS"
