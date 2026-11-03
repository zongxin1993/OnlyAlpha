"""Actual installed TRADING arithmetic; the SDK owns no execution authority."""

import json
import subprocess
from pathlib import Path


def test_installed_trading_session_preserves_actual_math_and_atomic_checkpoint(tmp_path: Path) -> None:
    from scripts.build_algorithm_sdk import ROOT, install

    installation = tmp_path / "installed"
    install(tmp_path / "wheels", installation)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    fields = {
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
    }
    request = {
        "source": {key: value for key, value in fixture["revision"].items() if key in fields},
        "nodes": {str(index): row["definition"] for index, row in enumerate(fixture["graph"]["nodes"])},
    }
    code = r"""
import copy, json, sys
from decimal import Decimal, ROUND_DOWN, getcontext
from onlyalpha_backend_algorithms.chart_isolation import restrict
from onlyalpha_backend_algorithms.trading_session import TradingGraphSession
from onlyalpha_backend_algorithms.research_evaluation import CalculationGraphEvaluator
from onlyalpha_plugin_targets.registration import resolve_forward_return
from onlyalpha.calculation.definition import OnlyCalculationReference
p=json.loads(sys.stdin.read())
assert restrict() == 'LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1'
getcontext().prec=4
getcontext().rounding=ROUND_DOWN
s=TradingGraphSession([p['source']], p['nodes'])

def rejected(call):
    try: call()
    except (ValueError, TypeError, ArithmeticError): pass
    else: raise AssertionError('invalid numerical request accepted')

def step(session, close, volume):
    lag=session.update('0', {'value': close})['value']
    mean=session.update('1', {'value': volume})['value']
    return session.update('2', {'close': close, 'close_lag_20': lag, 'volume': volume, 'volume_mean_20': mean})['value']

# Inclusive 20-observation volume window and previous-20 close are actual factories.
for index in range(20):
    assert step(s, Decimal(100 + index), Decimal(1)) is None
saved=s.checkpoint()
assert set(saved)=={'schema_version', 'nodes'}
assert saved['schema_version']==1
assert set(saved['nodes'])=={'0','1','2'}
assert saved['nodes']['0']['checkpoint_schema_version']==1
assert saved['nodes']['1']['checkpoint_schema_version']==2
assert saved['nodes']['2']['state_capability']=='STATELESS'
assert saved['nodes']['2']['state'] is None
assert step(s, Decimal(120), Decimal(21))==Decimal('2.1')
# A fresh candidate continues each captured rolling window, never precomputed signals.
r=TradingGraphSession([p['source']], p['nodes'])
r.restore(saved)
assert r.checkpoint()==saved
assert step(r, Decimal(120), Decimal(21))==Decimal('2.1')
assert step(r, Decimal(121), Decimal(1))==Decimal('0.099009900990')
# Instances and returned checkpoint dictionaries cannot alias each other.
fresh=TradingGraphSession([p['source']], p['nodes'])
assert fresh.update('0', {'value': Decimal(999)})=={'value': None}
copy_saved=copy.deepcopy(saved)
copy_saved['nodes']['0']['state']['inputs']['value'][0]='999'
assert s.checkpoint()['nodes']['0']['state']['inputs']['value'][0]=='100'
assert r.checkpoint()['nodes']['0']['state']['inputs']['value'][0]=='101'
# Validate all arguments before advancing a stateful factory.
before=r.checkpoint()
for invalid in (1.0, True, '1', Decimal('NaN'), Decimal('Infinity'), {'type':'DECIMAL','value':'1'}):
    rejected(lambda invalid=invalid: r.update('0', {'value': invalid}))
rejected(lambda: r.update('missing', {'value': Decimal(1)}))
rejected(lambda: r.update('0', {'value': Decimal(1), 'extra': Decimal(1)}))
rejected(lambda: r.update('0', {}))
assert r.checkpoint()==before
# Every restored entry is exact and all candidates are checked before installation.
for kind in ('definition','implementation','schema','history','missing','extra','null-stateless','control','boolean-schema'):
    bad=copy.deepcopy(saved)
    if kind=='definition': bad['nodes']['0']['definition']['warmup']['minimum_observations']+=1
    elif kind=='implementation': bad['nodes']['0']['implementation_fingerprint']='f'*64
    elif kind=='schema': bad['nodes']['1']['checkpoint_schema_version']=1
    elif kind=='history': bad['nodes']['1']['state']['inputs']['value']=['not-decimal']
    elif kind=='missing': del bad['nodes']['2']
    elif kind=='extra': bad['nodes']['unknown']=bad['nodes']['2']
    elif kind=='null-stateless': bad['nodes']['2']['state']={}
    elif kind=='boolean-schema': bad['schema_version']=True
    else: bad['runtime_generation']='opaque-authority-forgery'
    rejected(lambda bad=bad: r.restore(bad))
    assert r.checkpoint()==before
for kind in ('definition','unknown-version','predicate','budget'):
    bad=copy.deepcopy(p['nodes'])
    if kind=='definition': bad['0']['warmup']['minimum_observations']+=1
    elif kind=='unknown-version': bad['0']['semantic_version']='uninstalled'
    elif kind=='predicate': bad['0']['kind']='PREDICATE'
    else: bad={str(index): bad['0'] for index in range(129)}
    rejected(lambda bad=bad: TradingGraphSession([p['source']],bad))
bad=copy.deepcopy(p['nodes']);bad['0']['parameters']['period']['value']=8193
bad['0']['warmup']['minimum_observations']=8194
rejected(lambda: TradingGraphSession([p['source']],bad))
bad=copy.deepcopy(p['nodes']);bad['1']['parameters']['period']['value']=8193
bad['1']['warmup']['minimum_observations']=8193
rejected(lambda: TradingGraphSession([p['source']],bad))
rejected(lambda: TradingGraphSession([p['source']], {'\n': p['nodes']['0']}))
rejected(lambda: TradingGraphSession([p['source']] * 129, p['nodes']))
# Existing graph consumers can resolve actual resources after confinement too.
# This only evaluates controlled numerical vectors; no Research admission is implied.
graph={'schema_version':1, 'nodes':[{'alias':None, 'definition':definition} for definition in p['nodes'].values()]}
evaluator=CalculationGraphEvaluator([p['source']], graph)
rows=[{'at_ns':index*60_000_000_000, 'values':{'close':str(100+index),'volume':'21' if index==20 else '1'}} for index in range(21)]
evaluation=evaluator.evaluate(rows, include_trading=True)
for field in ('outputs','trading_outputs'):
    assert Decimal(next(row['values']['value'] for row in evaluation[field] if row['node_fingerprint']==evaluator.graph.nodes[-1].fingerprint)[-1])==Decimal('2.1')
target=resolve_forward_return({'entry_offset':0,'exit_offset':1}, OnlyCalculationReference(None,'entry_price','bar.close'), OnlyCalculationReference(None,'exit_price','bar.close'))
target_program=CalculationGraphEvaluator([], {'schema_version':1,'nodes':[{'alias':None,'definition':dict(target.to_dict())}]})
target_values=target_program.evaluate(rows[:3])['outputs'][0]['values']['target_value']
assert Decimal(target_values[0])==Decimal('0.01')
assert target_values[-1] is None
# Source references are opaque inputs; arithmetic never certifies backend authority.
assert not any(name.startswith(('onlyalpha.application','onlyalpha.runtime','onlyalpha.strategy','onlyalpha.persistence','onlyalpha.execution','onlyalpha.account','onlyalpha.risk','onlyalpha.broker')) for name in sys.modules)
assert not any(key in saved for key in ('cursor','receipt','grant','runtime_generation','authority'))
print('actual trading math/checkpoint PASS')
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
    assert result.stdout.strip() == "actual trading math/checkpoint PASS"
