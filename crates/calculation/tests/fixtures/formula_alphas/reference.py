"""按两个清单的顺序，用独立的 Decimal 求值器生成冻结的 JSONL 数值基准。"""

import ast
import hashlib
import json
import operator
import sys
from decimal import Decimal as D, ROUND_HALF_EVEN, getcontext, localcontext
from fractions import Fraction
from math import prod
from pathlib import Path


PERIODS = 320
INSTRUMENTS = 6
SAMPLES = (0, 15, 63, 255, 316, 319)
SCALE = D('1e-12')
ZERO = D(0)
ONE = D(1)


def public(x):
    if x is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 28
        ctx.rounding = ROUND_HALF_EVEN
        v = (+D(x)).quantize(SCALE)
    return v if v else ZERO


def market(i):
    columns = {}
    for t in range(PERIODS):
        close = D(1000 + (t * (19 + 7*i) + t*t * (3+i) + 13*i + t//7) % 141) / 100
        # 交替扩大的振幅使 60 日均值与短窗排名连续变化，覆盖多层滚动相关。
        swing = (1 if (t+i) % 2 else -1) * (t-127) * (i+1) if t >= 128 else 0
        if swing:
            close = 11 + D(swing) / 1000
        opening = close + D((7*t + 11*i + t//4) % 41 - 20) / 100
        high = max(opening, close) + D((t*t + 3*i + 1) % 17 + 1) / 100
        low = min(opening, close) - D((5*t + 7*i + 2) % 19 + 1) / 100
        vwap = (opening + 2*close + high + low) / 5
        volume = D(80 + ((t*t + 7*t) * (i+3) + 23*i + t//5) % 131)
        if swing:
            volume = 150 + D(swing) / 10
        benchmark = D(1000 + (t*t + 13*t + t//3) % 101) / 10
        values = dict(open=opening, close=close, high=high, low=low, vwap=vwap,
                      volume=volume, dollar_volume=vwap*volume, amount=vwap*volume,
                      market_cap=close*(10000 + 700*i), index_close=benchmark,
                      index_open=benchmark + D(t % 5 - 2) / 10,
                      mkt=D((13*t + t//5) % 17 - 8)/1000,
                      smb=D((7*t + t//7) % 19 - 9)/1000,
                      hml=D((t*t + t//4) % 23 - 11)/1000,
                      sector=(i + (t//53)*(i%2)) % 2,
                      industry=(i//2 + t//73*(i%2)) % 3,
                      subindustry=(i + t//61*(i//3)) % 3,
                      subindustry_inner=i % 3, subindustry_outer=(i//2 + t//67*(i%2)) % 3,
                      subindustry_correlation=(i//3 + t//79*(i%2)) % 2)
        if i == 5:
            for missing_time, fields in ((15, ('volume', 'amount', 'dollar_volume')),
                                         (63, ('sector', 'low')), (316, ('close', 'vwap', 'amount', 'dollar_volume'))):
                if t == missing_time:
                    values.update(dict.fromkeys(fields))
        previous = columns['close'][-1] if t else None
        values['returns'] = public(close / previous - 1) if previous and values['close'] is not None else None
        for name, value in values.items():
            columns.setdefault(name, []).append(D(value) if value is not None else None)
    return columns


def rank(values, target):
    if len(values) == 1:
        return D('0.5')
    below = sum(x < target for x in values)
    ties = values.count(target)
    return D(2*below + ties - 1) / (2*(len(values)-1))


def power(x, y):
    if (not x and y <= 0) or (x < 0 and y != y.to_integral_value()):
        return None
    return x ** y


POINT = {'Abs': abs, 'Sign': lambda x: (x > 0) - (x < 0),
         'Log': lambda x: x.ln() if x > 0 else None, 'Greater': max, 'Less': min, 'Pow': power}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: lambda x, y: x/y if y else None, ast.Eq: operator.eq, ast.NotEq: operator.ne,
          ast.Lt: operator.lt, ast.Gt: operator.gt, ast.LtE: operator.le, ast.GtE: operator.ge}


def pointwise(fn, *matrices, allow_null=False):
    return [[public(fn(*cells)) if allow_null or None not in cells else None
             for cells in zip(*series)] for series in zip(*matrices)]


def cross_section(name, matrices):
    result = [[] for _ in matrices[0]]
    for t in range(PERIODS):
        column = [row[t] for row in matrices[0]]
        valid = [v for v in column if v is not None]
        groups = [row[t] for row in matrices[1]] if name == 'GroupDemean' else None
        scale = sum(map(abs, valid)) if name == 'CSScale' else None
        for i, value in enumerate(column):
            answer = None
            if value is not None:
                if name == 'Rank':
                    answer = rank(valid, value)
                elif name == 'CSScale':
                    answer = value / scale if scale else None
                elif groups[i] is not None:
                    peers = [v for v, g in zip(column, groups) if v is not None and g == groups[i]]
                    answer = (value * len(peers) - sum(peers)) / len(peers)
            result[i].append(public(answer))
    return result


def regression_residual(y, regressors):
    # 正规方程含独立的截距列，通过带主元的消元求解。
    columns = [[ONE] * len(y), *regressors]
    def dot(a, b):
        return sum(v*w for v, w in zip(a, b))
    if len(y) <= len(columns):
        return None
    matrix = [[Fraction(dot(col, other)) for other in columns] + [Fraction(dot(col, y))]
              for col in columns]
    for k in range(4):
        pivot = max(range(k, 4), key=lambda i: abs(matrix[i][k]))
        if not matrix[pivot][k]:
            return None
        matrix[k], matrix[pivot] = matrix[pivot], matrix[k]
        matrix[k] = [v / matrix[k][k] for v in matrix[k]]
        for i in range(4):
            if i != k:
                multiplier = matrix[i][k]
                matrix[i] = [a - multiplier*b for a, b in zip(matrix[i], matrix[k])]
    residual = Fraction(y[-1]) - sum(row[-1]*Fraction(col[-1]) for row, col in zip(matrix, columns))
    return D(residual.numerator) / D(residual.denominator)


def rolling(name, columns):
    x, *others = columns
    n = len(x)
    if name == 'ConditionalBeta':
        pairs = [(a,b) for a,b,flag in zip(x,*others) if flag == ONE
                 and a is not None and b is not None]
        n = len(pairs)
        if n < 2:
            return None
        a,b = zip(*pairs)
        variance = n*sum(v*v for v in b) - sum(b)**2
        return (n*sum(v*w for v,w in pairs) - sum(a)*sum(b)) / variance if variance else None
    if any(None in col for col in columns):
        return None
    if name == 'RegressionResidual3':
        return regression_residual(x, others)
    if name in ('Rank', 'TsRank'):
        return rank(x, x[-1])
    if name == 'Min':
        return min(x)
    if name == 'Max':
        return max(x)
    if name in ('IdxMax', 'IdxMin'):
        return x.index((max if name == 'IdxMax' else min)(x)) + 1
    if name == 'Product':
        return prod(x)
    if name == 'Sum':
        return sum(x)
    if name == 'Mean':
        return sum(x)/n
    if name == 'WMA':
        return sum(j*v for j,v in enumerate(x, 1)) * 2 / (n*(n+1))
    if name == 'Slope':
        return sum((2*j - n+1)*v for j,v in enumerate(x)) * 6 / (n*(n*n-1)) if n>1 else None
    if name == 'Std':
        return (n*sum(v*v for v in x) - sum(x)**2).sqrt() / n
    if name in ('Cov', 'Corr'):
        y = others[0]
        xy = n*sum(v*w for v,w in zip(x,y)) - sum(x)*sum(y)
        if name == 'Cov':
            return xy / (n*n)
        xx = n*sum(v*v for v in x) - sum(x)**2
        yy = n*sum(v*v for v in y) - sum(y)**2
        return xy / (xx*yy).sqrt() if xx and yy else None
    raise ValueError(name)


def recurrent(name, series, period=None, weight=None):
    state = ONE if name == 'CumProductIf' else None
    values = []
    for cells in zip(*series):
        if None in cells:
            values.append(None)
            continue
        x = cells[0]
        with localcontext() as ctx:
            ctx.prec = 28
            if name == 'CumProductIf':
                if cells[1] == ONE:
                    state *= x
            else:
                state = +x if state is None else (weight*x + (period-weight)*state) / period
        values.append(public(state))
        if name == 'SMA' and state.as_tuple().exponent < -96:
            state = state.quantize(D('1e-96'), rounding=ROUND_HALF_EVEN)
    return values


def evaluate(expression, panel):
    source = expression.replace('$', '').replace('&&', ' and ').replace('||', ' or ')
    cache = {}

    def visit(node):
        # 保留原始十进制字面量，避免 Python AST 的二进制浮点近似。
        key = source[node.col_offset:node.end_col_offset]
        if key not in cache:
            cache[key] = compute(node)
        return cache[key]

    def compute(node):
        if isinstance(node, ast.Name):
            return [fields[node.id] for fields in panel]
        if isinstance(node, ast.Constant):
            return [[D(source[node.col_offset:node.end_col_offset])] * PERIODS for _ in panel]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return pointwise(operator.neg, visit(node.operand))
        if isinstance(node, ast.BinOp):
            return pointwise(BINARY[type(node.op)], visit(node.left), visit(node.right))
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            return pointwise(BINARY[type(node.ops[0])], visit(node.left), visit(node.comparators[0]))
        if isinstance(node, ast.BoolOp):
            predicate = all if isinstance(node.op, ast.And) else any
            return pointwise(lambda *xs: predicate(x > 0 for x in xs), *map(visit, node.values))
        if not isinstance(node, ast.Call):
            raise ValueError(ast.dump(node))
        name, args = node.func.id, node.args
        if name == 'Where':
            return pointwise(lambda c,a,b: None if c is None else (a if c>0 else b),
                             *map(visit,args), allow_null=True)
        if name in POINT:
            return pointwise(POINT[name], *map(visit,args))
        if name in ('CSScale', 'GroupDemean') or (name == 'Rank' and len(args) == 1):
            return cross_section(name, list(map(visit,args)))
        if name == 'SMA':
            return [recurrent(name, [row], args[1].value, args[2].value) for row in visit(args[0])]
        if name == 'CumProductIf':
            return [recurrent(name, series) for series in zip(*map(visit,args))]
        n = args[-1].value
        sources = list(map(visit,args[:-1]))
        if name in ('Ref', 'Delta'):
            delayed = [[None]*n + row[:PERIODS-n] for row in sources[0]]
            return delayed if name == 'Ref' else pointwise(operator.sub, sources[0], delayed)
        return [[None]*(n-1) + [public(rolling(name, [col[t-n:t] for col in series]))
                                 for t in range(n, PERIODS+1)] for series in zip(*sources)]

    return visit(ast.parse(source, mode='eval').body)


def fixed(x):
    return None if x is None else format(x if x else ZERO, '.12f')


def check_predicates():
    flags = [ONE, D(2), -ONE, ZERO, None, ONE, ONE]
    values = [D(2), D(20), D(90), D(40), D(50), None, D(6)]
    predictors = list(map(D, range(7)))
    assert rolling('ConditionalBeta', [values, predictors, flags]) == D(2)/3
    assert recurrent('CumProductIf', [values, flags]) == [2, 2, 2, 2, None, None, 12]


def records(roots):
    check_predicates()
    panel = [market(i) for i in range(INSTRUMENTS)]
    yield dict(panel=panel, periods=PERIODS, sample_times=SAMPLES)
    for root in roots:
        manifest = json.loads((root/'manifest.json').read_bytes())
        for feature in manifest['features']:
            raw = (root/feature['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != feature['sha256']:
                raise ValueError(f"清单摘要不符：{root / feature['file']}")
            factor = json.loads(raw)
            matrix = evaluate(factor['expression'], panel)
            digest = hashlib.sha256()
            defined = 0
            for row in matrix:
                for cell in row:
                    defined += cell is not None
                    digest.update(((fixed(cell) or 'null')+'\n').encode('ascii'))
            if not defined:
                raise ValueError(f"没有确定值：{manifest['factor_set']} {factor['name']}")
            yield dict(factor_set=manifest['factor_set'], name=factor['name'], sha256=digest.hexdigest(),
                       defined=defined, samples=[[fixed(row[t]) for t in SAMPLES] for row in matrix])


if __name__ == '__main__':
    getcontext().prec = 70
    examples = Path(__file__).resolve().parents[5] / 'examples/factor'
    roots = list(map(Path, sys.argv[1:])) or [examples/'worldquant/alpha101', examples/'gtja/alpha191']
    for record in records(roots):
        print(json.dumps(record, default=lambda v: format(v, 'f'), separators=(',', ':')))
